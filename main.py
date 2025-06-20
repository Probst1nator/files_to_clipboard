# gui_copy_files.py (v8 - Enhanced)

import os
import sys
import json
import argparse
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from typing import Dict, List, Set, Optional, Tuple

try:
    import pyperclip
except ImportError:
    pyperclip = None

# --- Configuration ---
STATE_FILENAME = ".file_copier_selections.json"
IGNORE_DIRS: Set[str] = {"__pycache__", "node_modules", "venv", "dist", "build", ".git", ".idea", ".vscode"}
IGNORE_FILES: Set[str] = {".DS_Store", STATE_FILENAME, ".gitignore", ".env"}

# --- Helper Functions ---
def is_text_file(filepath: str) -> bool:
    try:
        with open(filepath, 'rb') as f:
            chunk = f.read(1024)
            return b'\0' not in chunk
    except (IOError, PermissionError):
        return False

def get_language_hint(filename: str) -> str:
    _, extension = os.path.splitext(filename)
    return extension[1:].lower() if extension else ""

def get_script_directory() -> str:
    """Get the directory where this script is located."""
    try:
        script_path = os.path.abspath(__file__)
        return os.path.dirname(script_path)
    except NameError:
        # __file__ is not defined, fallback to current directory
        return os.getcwd()


class FileCopierApp:
    def __init__(self, root: tk.Tk, directory: str):
        self.root = root
        self.directory = os.path.abspath(directory)
        # Save state file next to the script
        script_dir = get_script_directory()
        self.state_file_path = os.path.join(script_dir, STATE_FILENAME)

        self.root.title(f"File Content Copier - {os.path.basename(self.directory)}")
        self.root.geometry("1000x800")
        self.selected_files_map: Dict[str, bool] = {}
        self.preview_visible = False

        # Main container
        self.main_container = ttk.Frame(root)
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.main_pane = ttk.PanedWindow(self.main_container, orient=tk.HORIZONTAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True)

        # --- Left Pane: File Tree ---
        self.tree_frame = ttk.Frame(self.main_pane, padding=5)
        
        # Tree control buttons
        self.tree_controls = ttk.Frame(self.tree_frame)
        self.tree_controls.pack(fill=tk.X, pady=(0, 5))
        self.btn_add_folder = ttk.Button(self.tree_controls, text="Add Selected Folder", command=self.add_selected_folder)
        self.btn_add_folder.pack(side=tk.LEFT)
        
        self.tree = ttk.Treeview(self.tree_frame, show="tree headings")
        self.tree.heading("#0", text="Project Structure", anchor='w')
        
        ysb = ttk.Scrollbar(self.tree_frame, orient='vertical', command=self.tree.yview)
        xsb = ttk.Scrollbar(self.tree_frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscroll=ysb.set, xscroll=xsb.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        xsb.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.main_pane.add(self.tree_frame, weight=1)

        # --- Right Pane: Selected Files ---
        self.selection_frame = ttk.Frame(self.main_pane, padding=5)
        ttk.Label(self.selection_frame, text="Selected Files (Drag to Reorder)", font=("", 10, "bold")).pack(pady=(0, 5), anchor='w')
        
        # Listbox with scrollbar
        self.listbox_frame = ttk.Frame(self.selection_frame)
        self.listbox_frame.pack(fill=tk.BOTH, expand=True)
        
        self.listbox = tk.Listbox(self.listbox_frame, selectmode=tk.SINGLE, background="#f0f0f0", borderwidth=1, relief="sunken")
        listbox_scrollbar = ttk.Scrollbar(self.listbox_frame, orient='vertical', command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=listbox_scrollbar.set)
        
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        listbox_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.controls_frame = ttk.Frame(self.selection_frame)
        self.controls_frame.pack(fill=tk.X, pady=5)
        self.btn_remove = ttk.Button(self.controls_frame, text="Remove", command=self.remove_selected)
        self.btn_remove.pack(side=tk.LEFT, padx=(0, 5))
        self.btn_clear = ttk.Button(self.controls_frame, text="Clear All", command=self.clear_all)
        self.btn_clear.pack(side=tk.LEFT)
        self.selected_count_var = tk.StringVar(value="0 files selected")
        ttk.Label(self.controls_frame, textvariable=self.selected_count_var).pack(side=tk.RIGHT)
        
        self.main_pane.add(self.selection_frame, weight=1)

        # --- Bottom Frame with Controls ---
        self.bottom_frame = ttk.Frame(self.main_container)
        self.bottom_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.status_var = tk.StringVar(value="Ready.")
        self.status_label = ttk.Label(self.bottom_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor='w')
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        self.btn_toggle_preview = ttk.Button(self.bottom_frame, text="Show Preview", command=self.toggle_preview)
        self.btn_toggle_preview.pack(side=tk.LEFT, padx=(0, 5))
        
        self.btn_copy = ttk.Button(self.bottom_frame, text="Copy to Clipboard", command=self.copy_to_clipboard, style='Accent.TButton')
        self.btn_copy.pack(side=tk.RIGHT)
        
        style = ttk.Style()
        style.configure('Accent.TButton', font=("", 10, "bold"))

        # --- Preview Frame (initially hidden) ---
        self.preview_frame = ttk.Frame(self.main_container)
        ttk.Label(self.preview_frame, text="Preview", font=("", 10, "bold")).pack(anchor='w', pady=(5, 0))
        
        self.preview_text = scrolledtext.ScrolledText(
            self.preview_frame, 
            height=10, 
            wrap=tk.WORD, 
            background="#f5f5f5",
            font=("Consolas", 9) if sys.platform == "win32" else ("Monaco", 9)
        )
        self.preview_text.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        # --- Bindings ---
        self.tree.bind("<Double-1>", self.on_tree_double_click)
        self.listbox.bind("<Double-1>", lambda e: self.remove_selected())
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.listbox.bind("<Button-1>", self.on_drag_start)
        self.listbox.bind("<B1-Motion>", self.on_drag_motion)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.update_preview())
        
        # Binding for lazy loading
        self.tree.bind('<<TreeviewOpen>>', self.on_tree_expand)
        
        # Initialize drag variables
        self.drag_start_index: Optional[int] = None
        self.drag_start_item: Optional[str] = None
        
        # --- Population ---
        self.process_directory("", self.directory)
        self.load_selection_state()
        self.update_selected_count()

    def process_directory(self, parent_id: str, path: str) -> None:
        # Clear any dummy node
        children = self.tree.get_children(parent_id)
        for child_id in children:
            if self.tree.item(child_id, "values") == ("dummy",):
                self.tree.delete(child_id)
        
        try: 
            all_items = os.listdir(path)
        except (OSError, PermissionError) as e:
            self.status_var.set(f"Error accessing {path}: {e}")
            return

        dirs_to_process: List[str] = []
        files_to_process: List[str] = []
        
        for name in all_items:
            if name.startswith('.') and name not in {'.env', '.gitignore'}:
                continue
            if name in IGNORE_FILES: 
                continue
            full_path = os.path.join(path, name)
            if os.path.isdir(full_path):
                if name not in IGNORE_DIRS: 
                    dirs_to_process.append(name)
            elif is_text_file(full_path):
                files_to_process.append(name)
        
        dirs_to_process.sort(key=str.lower)
        files_to_process.sort(key=str.lower)

        for dir_name in dirs_to_process:
            full_path = os.path.join(path, dir_name)
            rel_path = os.path.relpath(full_path, self.directory)
            dir_id = self.tree.insert(parent_id, 'end', text=f"📁 {dir_name}", values=[rel_path], tags=('folder',))
            # Insert dummy child to make the folder expandable
            self.tree.insert(dir_id, 'end', text='...', values=['dummy'])

        for file_name in files_to_process:
            full_path = os.path.join(path, file_name)
            rel_path = os.path.relpath(full_path, self.directory)
            self.tree.insert(parent_id, 'end', text=f"📄 {file_name}", values=[rel_path], tags=('file',))
        
        self.tree.tag_configure('file', foreground='#0066cc')
        self.tree.tag_configure('folder', foreground='#333333')

    def on_tree_expand(self, event: tk.Event) -> None:
        """Handler for lazy loading. Fires when a node is expanded via the [+] indicator."""
        item_id = self.tree.focus()
        
        # Check if it has a dummy child node
        children = self.tree.get_children(item_id)
        if children and self.tree.item(children[0], "values") == ("dummy",):
            # Get the path of the item to populate
            item_path = self.tree.item(item_id, "values")[0]
            full_path = os.path.join(self.directory, item_path)
            
            # Populate the node with its actual children
            self.process_directory(item_id, full_path)

    def get_all_files_in_folder(self, folder_path: str) -> List[str]:
        """Recursively get all text files in a folder."""
        all_files: List[str] = []
        
        def scan_directory(path: str) -> None:
            try:
                items = os.listdir(path)
                for name in items:
                    if name.startswith('.') and name not in {'.env', '.gitignore'}:
                        continue
                    if name in IGNORE_FILES:
                        continue
                    
                    full_path = os.path.join(path, name)
                    
                    if os.path.isdir(full_path) and name not in IGNORE_DIRS:
                        scan_directory(full_path)
                    elif os.path.isfile(full_path) and is_text_file(full_path):
                        rel_path = os.path.relpath(full_path, self.directory)
                        all_files.append(rel_path)
            except (OSError, PermissionError):
                pass
        
        scan_directory(folder_path)
        return sorted(all_files, key=str.lower)

    def add_selected_folder(self) -> None:
        """Add all files from the selected folder to the selection."""
        selection = self.tree.selection()
        if not selection:
            self.status_var.set("No folder selected in the tree.")
            return
        
        item_id = selection[0]
        item = self.tree.item(item_id)
        
        # Check if it's a folder
        if 'folder' not in item['tags']:
            self.status_var.set("Please select a folder, not a file.")
            return
        
        folder_rel_path = item['values'][0]
        folder_full_path = os.path.join(self.directory, folder_rel_path)
        
        # Get all files in the folder
        files = self.get_all_files_in_folder(folder_full_path)
        
        if not files:
            self.status_var.set(f"No text files found in {folder_rel_path}")
            return
        
        # Add files to selection
        added_count = 0
        for file_path in files:
            if file_path not in self.selected_files_map:
                self.listbox.insert(tk.END, file_path)
                self.selected_files_map[file_path] = True
                added_count += 1
        
        self.update_selected_count()
        self.update_preview()
        self.status_var.set(f"Added {added_count} file(s) from {folder_rel_path}")

    def on_tree_double_click(self, event: tk.Event) -> None:
        item_id = self.tree.identify_row(event.y)
        if not item_id: 
            return
        item = self.tree.item(item_id)
        
        if 'file' in item['tags']:
            file_path = item['values'][0]
            if file_path not in self.selected_files_map:
                self.listbox.insert(tk.END, file_path)
                self.selected_files_map[file_path] = True
                self.update_selected_count()
                self.update_preview()
        elif 'folder' in item['tags']:
            # Double-clicking a folder adds all its files
            self.tree.selection_set(item_id)
            self.add_selected_folder()
    
    def remove_selected(self) -> None:
        selection = self.listbox.curselection()
        if selection:
            index = selection[0]
            file_path = self.listbox.get(index)
            self.listbox.delete(index)
            if file_path in self.selected_files_map: 
                del self.selected_files_map[file_path]
            self.update_selected_count()
            self.update_preview()

    def clear_all(self) -> None:
        self.listbox.delete(0, tk.END)
        self.selected_files_map.clear()
        self.update_selected_count()
        self.update_preview()

    def update_selected_count(self) -> None:
        count = self.listbox.size()
        self.selected_count_var.set(f"{count} file{'s' if count != 1 else ''} selected")

    def toggle_preview(self) -> None:
        """Toggle the preview pane visibility."""
        if self.preview_visible:
            self.preview_frame.pack_forget()
            self.btn_toggle_preview.configure(text="Show Preview")
            self.preview_visible = False
        else:
            self.preview_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
            self.btn_toggle_preview.configure(text="Hide Preview")
            self.preview_visible = True
            self.update_preview()

    def update_preview(self) -> None:
        """Update the preview text with the content that will be copied."""
        if not self.preview_visible:
            return
        
        self.preview_text.delete(1.0, tk.END)
        
        selected_files = self.listbox.get(0, tk.END)
        if not selected_files:
            self.preview_text.insert(1.0, "No files selected.")
            return
        
        # Generate the same output that would be copied
        output_parts: List[str] = []
        total_size = 0
        max_preview_size = 100000  # Limit preview to 100KB to avoid UI lag
        
        for rel_path in selected_files:
            if total_size > max_preview_size:
                remaining = len(selected_files) - len(output_parts)
                output_parts.append(f"\n... and {remaining} more file(s) ...")
                break
                
            try:
                full_path = os.path.join(self.directory, os.path.normpath(rel_path))
                header = f"# {rel_path.replace(os.path.sep, '/')}"
                language_hint = get_language_hint(rel_path)
                
                with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                
                formatted_block = f"{header}\n```{language_hint}\n{content}\n```"
                output_parts.append(formatted_block)
                total_size += len(formatted_block)
                
            except Exception as e:
                error_block = f"# ERROR: Could not read {rel_path}\n```\n{e}\n```"
                output_parts.append(error_block)
                total_size += len(error_block)
        
        final_output = "\n\n".join(output_parts)
        self.preview_text.insert(1.0, final_output)
        self.preview_text.see(1.0)  # Scroll to top

    def generate_clipboard_content(self) -> str:
        """Generate the content that will be copied to clipboard."""
        selected_files = self.listbox.get(0, tk.END)
        output_parts: List[str] = []
        
        for rel_path in selected_files:
            try:
                full_path = os.path.join(self.directory, os.path.normpath(rel_path))
                header = f"# {rel_path.replace(os.path.sep, '/')}"
                language_hint = get_language_hint(rel_path)
                with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                formatted_block = f"{header}\n```{language_hint}\n{content}\n```"
                output_parts.append(formatted_block)
            except Exception as e:
                output_parts.append(f"# ERROR: Could not read {rel_path}\n```\n{e}\n```")
        
        return "\n\n".join(output_parts)

    def copy_to_clipboard(self) -> None:
        if pyperclip is None:
            messagebox.showerror("Error", "Could not copy to clipboard.\n'pyperclip' library not found.")
            return
        
        selected_files = self.listbox.get(0, tk.END)
        if not selected_files:
            self.status_var.set("No files selected to copy.")
            return
        
        self.status_var.set("Processing and copying...")
        self.root.update_idletasks()
        
        final_output = self.generate_clipboard_content()
        pyperclip.copy(final_output)
        
        # Calculate size for status message
        size_kb = len(final_output) / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
        self.status_var.set(f"✅ Copied {len(selected_files)} file(s) to clipboard! ({size_str})")

    def save_selection_state(self) -> None:
        selected_files = list(self.listbox.get(0, tk.END))
        try:
            with open(self.state_file_path, 'w') as f: 
                json.dump({
                    "version": 2,
                    "project_directory": self.directory,
                    "selected_files": selected_files
                }, f, indent=2)
        except IOError as e:
            print(f"Warning: Could not save selection state. Error: {e}")

    def load_selection_state(self) -> None:
        if os.path.exists(self.state_file_path):
            try:
                with open(self.state_file_path, 'r') as f:
                    data = json.load(f)
                
                # Handle both old and new format
                if isinstance(data, list):
                    # Old format - just a list of files
                    persisted_files = data
                else:
                    # New format with metadata
                    if data.get("project_directory") != self.directory:
                        # Different project, don't load
                        return
                    persisted_files = data.get("selected_files", [])
                
                for file_path in persisted_files:
                    full_path = os.path.join(self.directory, os.path.normpath(file_path))
                    if os.path.exists(full_path) and file_path not in self.selected_files_map:
                        self.listbox.insert(tk.END, file_path)
                        self.selected_files_map[file_path] = True
                
                self.update_selected_count()
                
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load state file. Error: {e}")

    def on_closing(self) -> None:
        self.save_selection_state()
        self.root.destroy()
    
    def on_drag_start(self, event: tk.Event) -> None:
        self.drag_start_index = event.widget.nearest(event.y)
        self.drag_start_item = event.widget.get(self.drag_start_index)

    def on_drag_motion(self, event: tk.Event) -> None:
        if self.drag_start_index is None or self.drag_start_item is None:
            return
        current_index = event.widget.nearest(event.y)
        if current_index != self.drag_start_index:
            event.widget.delete(self.drag_start_index)
            event.widget.insert(current_index, self.drag_start_item)
            self.drag_start_index = current_index
            self.update_preview()


def main() -> None:
    parser = argparse.ArgumentParser(description="GUI to select and copy file contents.")
    parser.add_argument("directory", nargs="?", default=".", help="The directory to scan (default: current directory).")
    args = parser.parse_args()
    
    if not os.path.isdir(args.directory):
        print(f"Error: Directory '{args.directory}' not found.")
        sys.exit(1)
    
    root = tk.Tk()
    app = FileCopierApp(root, args.directory)
    root.mainloop()


if __name__ == "__main__":
    main()
