# main.py
import os
import sys
import argparse
import tkinter as tk
from typing import Dict

# Third-party imports with clear error handling
try:
    from termcolor import colored
except ImportError:
    # Create a dummy function if termcolor is not installed for graceful failure
    def colored(text, *args, **kwargs):
        return text

try:
    import pyperclip
except ImportError:
    pyperclip = None

# Local imports
from main_ui import FileCopierApp
from smart_paster import (
    find_files_from_request,
    build_clipboard_content,
    get_current_project_state,
    get_file_statuses,
    load_cache,
    save_cache,
    CACHE_FILENAME
)

def run_cli_mode(directory: str, message: str) -> None:
    """
    Runs the Smart Paster logic in the console, providing a rich, color-coded status report.
    """
    print(colored("🤖 Smart Paster Activated...", "cyan"))

    # --- Step 1: Load previous state from cache ---
    cache_path = os.path.join(directory, CACHE_FILENAME)
    old_state = load_cache(cache_path)

    # --- Step 2: Find files based on the user's request ---
    found_files_abs, missed_paths = find_files_from_request(message, directory)

    if not found_files_abs and not missed_paths:
        print(colored("No valid file paths or content found in the provided message.", "yellow"))
        return

    # --- Step 3: Get current file states and compare for status ---
    new_state = get_current_project_state(directory)
    file_statuses = get_file_statuses(old_state, new_state)

    print("-" * 20)
    if found_files_abs:
        print(f"Located {len(found_files_abs)} matching file(s):")
        max_len = max(len(os.path.relpath(f, directory)) for f in found_files_abs) if found_files_abs else 0

        for f_abs in found_files_abs:
            rel_path = os.path.relpath(f_abs, directory).replace('\\', '/')
            status_info = file_statuses.get(rel_path, {"status": "Unmodified", "color": "grey"})
            status_text = f"({status_info['status']})"
            attrs = ['dark'] if status_info['color'] == 'grey' else []
            print(f"  ✓ {rel_path:<{max_len}} {colored(status_text, status_info['color'], attrs=attrs)}")
    else:
        print(colored("No matching files found in the project directory.", "yellow"))

    if missed_paths:
        print(f"Ignored {len(missed_paths)} path(s) not found in project:")
        for p in missed_paths:
            print(colored(f"  - {p}", "grey", attrs=["dark"]))
    print("-" * 20)

    if not found_files_abs:
        return

    # --- Step 4: Build content and copy to clipboard ---
    output_content = build_clipboard_content(found_files_abs, directory)
    if pyperclip:
        pyperclip.copy(output_content)
        size_kb = len(output_content) / 1024
        print(colored(f"\n✅ Copied content for {len(found_files_abs)} file(s) to clipboard! ({size_kb:.1f} KB)", "green", attrs=["bold"]))
    else:
        print(colored("\n--- Final Output (would be copied if `pyperclip` was installed) ---", "cyan"))
        print(output_content)

    # --- Step 5: Save the new state for the next run ---
    save_cache(cache_path, new_state)

def main() -> None:
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(description="A powerful GUI/CLI tool to select, combine, and modify file contents.")
    parser.add_argument("directory", nargs="?", default=".", help="The project directory to scan (default: current directory).")
    parser.add_argument("-m", "--message", action="store_true", help="Enable CLI 'Smart Paster' mode. Reads file paths from clipboard.")
    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        print(colored(f"Error: Directory '{args.directory}' not found.", "red"))
        sys.exit(1)

    if args.message:
        # --- CLI Mode ---
        if pyperclip is None:
            print(colored("Error: pyperclip is not installed. Please install it to use Smart Paster mode:", "red"))
            print(colored("pip install pyperclip", "yellow"))
            sys.exit(1)

        try:
            clipboard_content = pyperclip.paste()
            if not clipboard_content or not clipboard_content.strip():
                print(colored("Clipboard is empty. Please copy a message with file paths.", "yellow"))
                sys.exit(1)
            run_cli_mode(args.directory, clipboard_content)
        except Exception as e:
            print(colored(f"An unexpected error occurred in Smart Paster mode: {e}", "red"))
            sys.exit(1)
    else:
        # --- GUI Mode ---
        root = tk.Tk()
        app = FileCopierApp(root, args.directory)
        root.mainloop()

if __name__ == "__main__":
    main()
