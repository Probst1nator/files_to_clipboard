# main.py
import os
import sys
import argparse
import tkinter as tk
from termcolor import colored

# Local imports after refactoring
from main_ui import FileCopierApp
from smart_paster import find_files_from_request, build_clipboard_content

try:
    import pyperclip
except ImportError:
    pyperclip = None

def run_cli_mode(directory: str, message: str) -> None:
    """Runs the Smart Paster logic in the console."""
    print(colored("🤖 Smart Paster Activated...", "cyan"))

    found_files_abs, all_parsed_paths = find_files_from_request(message, directory)

    if not all_parsed_paths:
        print(colored("No potential file paths found in the provided message.", "yellow"))
        return

    print("-" * 20)
    if found_files_abs:
        print(f"Located {len(found_files_abs)} matching file(s):")
        for f in found_files_abs:
            print(colored(f"  ✓ {os.path.relpath(f, directory)}", "green"))
    
    missed_paths = [p for p in all_parsed_paths if not any(os.path.relpath(f, directory).replace('\\','/').endswith(p.replace('\\','/')) for f in found_files_abs)]
    if missed_paths:
        print(f"Will create {len(missed_paths)} new file(s):")
        for p in missed_paths:
            print(colored(f"  + {p}", "yellow"))
    print("-" * 20)
    
    # Pass both found files and all parsed paths to generate content with placeholders
    output_content = build_clipboard_content(found_files_abs, all_parsed_paths, directory)
    
    if pyperclip:
        pyperclip.copy(output_content)
        size_kb = len(output_content) / 1024
        print(colored(f"\n✅ Copied content for {len(all_parsed_paths)} path(s) to clipboard! ({size_kb:.1f} KB)", "green", attrs=["bold"]))
    else:
        print(colored("\n--- Final Output (would be copied if `pyperclip` was installed) ---", "cyan"))
        print(output_content)

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