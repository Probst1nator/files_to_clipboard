# main.py
import os
import sys
import argparse
import tkinter as tk
from termcolor import colored
import json
from typing import Dict # <-- Added missing import

# Local imports after refactoring
from main_ui import FileCopierApp
from smart_paster import find_files_from_request, build_clipboard_content, IGNORE_DIRS, IGNORE_FILES

try:
    import pyperclip
except ImportError:
    pyperclip = None

CACHE_FILENAME = ".file_copier_cache.json"

def load_cache(path: str) -> Dict[str, float]:
    """Safely loads the file state cache."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return {}

def save_cache(path: str, data: Dict[str, float]):
    """Saves the file state cache."""
    try:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
    except IOError:
        pass # Fail silently if cache can't be written

def get_current_project_state(directory: str) -> Dict[str, float]:
    """Gets a snapshot of modification times for all files in the project."""
    state = {}
    for root, dirs, files in os.walk(directory, topdown=True):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for name in files:
            if name in IGNORE_FILES or name == CACHE_FILENAME:
                continue
            try:
                abs_path = os.path.join(root, name)
                rel_path = os.path.relpath(abs_path, directory).replace('\\', '/')
                state[rel_path] = os.path.getmtime(abs_path)
            except OSError:
                continue # Skip files that can't be accessed
    return state

def run_cli_mode(directory: str, message: str) -> None:
    """Runs the Smart Paster logic in the console with file status."""
    print(colored("🤖 Smart Paster Activated...", "cyan"))

    cache_path = os.path.join(directory, CACHE_FILENAME)
    old_state = load_cache(cache_path)

    found_files_abs, missed_paths = find_files_from_request(message, directory)

    if not found_files_abs and not missed_paths:
        print(colored("No valid file paths found in the provided message.", "yellow"))
        return

    print("-" * 20)
    
    if found_files_abs:
        print(f"Located {len(found_files_abs)} matching file(s):")
        max_len = max(len(os.path.relpath(f, directory)) for f in found_files_abs) if found_files_abs else 0
        
        for f in found_files_abs:
            rel_path = os.path.relpath(f, directory).replace('\\', '/')
            current_mtime = os.path.getmtime(f)
            
            status = ""
            color = "white"

            if rel_path not in old_state:
                status = "(Created)"
                color = "green"
            elif old_state[rel_path] != current_mtime:
                status = "(Modified)"
                color = "yellow"
            else:
                status = "(Unmodified)"
                color = "grey"

            print(f"  ✓ {rel_path:<{max_len}} {colored(status, color, attrs=['dark'] if color=='grey' else [])}")

    else:
        print(colored("No matching files found in the project directory.", "yellow"))

    if missed_paths:
        print(f"Ignored {len(missed_paths)} path(s) not found in project:")
        for p in missed_paths:
            print(colored(f"  - {p}", "grey", attrs=["dark"]))
            
    print("-" * 20)

    if not found_files_abs:
        return

    output_content = build_clipboard_content(found_files_abs, directory)
    
    if pyperclip:
        pyperclip.copy(output_content)
        size_kb = len(output_content) / 1024
        print(colored(f"\n✅ Copied content for {len(found_files_abs)} found file(s) to clipboard! ({size_kb:.1f} KB)", "green", attrs=["bold"]))
    else:
        print(colored("\n--- Final Output (would be copied if `pyperclip` was installed) ---", "cyan"))
        print(output_content)

    # Update the cache for the next run
    new_state = get_current_project_state(directory)
    save_cache(cache_path, new_state)

def main() -> None:
    parser = argparse.ArgumentParser(description="GUI/CLI to select and copy file contents.")
    parser.add_argument("directory", nargs="?", default=".", help="The directory to scan (default: current directory).")
    parser.add_argument("-m", "--message", action="store_true", help="Enable Smart Paster CLI mode. Reads from clipboard.")
    args = parser.parse_args()
    
    if not os.path.isdir(args.directory):
        print(colored(f"Error: Directory '{args.directory}' not found.", "red"))
        sys.exit(1)

    if args.message:
        if pyperclip is None:
            print(colored("Error: pyperclip is not installed. Please install it to use Smart Paster mode:", "red"))
            print(colored("pip install pyperclip", "yellow"))
            sys.exit(1)
        
        try:
            clipboard_content = pyperclip.paste()
            if not clipboard_content or not clipboard_content.strip():
                print(colored("Clipboard is empty. Please copy a message with file paths to use Smart Paster.", "yellow"))
                sys.exit(1)
            run_cli_mode(args.directory, clipboard_content)
        except Exception as e:
            print(colored(f"An unexpected error occurred in Smart Paster mode: {e}", "red"))
            sys.exit(1)
    else:
        root = tk.Tk()
        FileCopierApp(root, args.directory)
        root.mainloop()

if __name__ == "__main__":
    main()