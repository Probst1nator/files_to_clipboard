# gui_copy_files.py (v9 - Optimized)

import os
import sys
import json
import argparse
import re
import signal
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from typing import Dict, List, Set, Optional, Tuple

try:
    import pyperclip
except ImportError:
    pyperclip = None

# For High-DPI display font rendering on Windows
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except (ImportError, AttributeError):
    pass # Not on Windows or old version

# --- Configuration ---
STATE_FILENAME = ".file_copier_selections.json"
IGNORE_DIRS: Set[str] = {"__pycache__", "node_modules", "venv", "dist", "build", ".git", ".idea", ".vscode"}
IGNORE_FILES: Set[str] = {".DS_Store", STATE_FILENAME, ".gitignore", ".env"}

# Dark theme colors
DARK_BG = "#2b2b2b"
DARK_FG = "#ffffff"
DARK_SELECT_BG = "#404040"
DARK_SELECT_FG = "#ffffff"
DARK_ENTRY_BG = "#3c3c3c"
DARK_BUTTON_BG = "#404040"
DARK_TREE_BG = "#2b2b2b"

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
    try:
        script_path = os.path.abspath(__file__)
        return os.path.dirname(script_path)
    except NameError:
        return os.getcwd()


class FileCopierApp:
    def __init__(self, root: tk.Tk, directory: str):
        self.root = root
        self.directory = os.path.abspath(directory)
        script_dir = get_script_directory()
        self.state_file_path = os.path.join(script_dir, STATE_FILENAME)

        self.root.title(f"File Content Copier - {os.path.basename(self.directory)}")
        self.root.geometry("1200x850") # Increased size slightly for better layout
        self.root.configure(bg=DARK_BG)

        # --- Style Configuration ---
        style = ttk.Style()
        base_font = ("Segoe UI", 10) if sys.platform == "win32" else ("Helvetica", 11)
        
        style.theme_use('clam')
        style.configure('.', font=base_font, background=DARK_BG, foreground=DARK_FG)
        style.configure("TFrame", background=DARK_BG)
        style.configure("TLabel", background=DARK_BG, foreground=DARK_FG)
        style.configure("TEntry", fieldbackground=DARK_ENTRY_BG, background=DARK_ENTRY_BG, 
                       foreground=DARK_FG, bordercolor=DARK_SELECT_BG, insertcolor=DARK_FG)
        style.map("TEntry", bordercolor=[('focus', '#0078d4')])
        style.configure("TButton", background=DARK_BUTTON_BG, foreground=DARK_FG, 
                       bordercolor=DARK_SELECT_BG, focuscolor='none', padding=5)
        style.map("TButton", background=[('active', DARK_SELECT_BG)])
        style.configure("Treeview", background=DARK_TREE_BG, foreground=DARK_FG, 
                       fieldbackground=DARK_TREE_BG, bordercolor=DARK_SELECT_BG, rowheight=25)
        style.map("Treeview", background=[('selected', DARK_SELECT_BG)])
        style.configure("Vertical.TScrollbar", background=DARK_BG, troughcolor=DARK_ENTRY_BG)
        style.configure("Horizontal.TScrollbar", background=DARK_BG, troughcolor=DARK_ENTRY_BG)
        style.configure("TPanedwindow", background=DARK_BG)
        
        self.selected_files_map: Dict[str, bool] = {}
        self.preview_visible = False
        self.all_text_files: List[str] = [] # Cache for all project files
        self._search_job: Optional[str] = None

        # Main container
        self.main_container = ttk.Frame(root, padding=10)
        self.main_container.pack(fill=tk.BOTH, expand=True)

        self.main_pane = ttk.PanedWindow(self.main_container, orient=tk.HORIZONTAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True)

        # --- Left Pane: File Tree ---
        self.tree_frame = ttk.Frame(self.main_pane, padding=(0,0,5,0))
        
        self.search_frame = ttk.Frame(self.tree_frame)
        self.search_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(self.search_frame, text="Filter:").pack(side=tk.LEFT, padx=(0,5))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(self.search_frame, textvariable=self.search_var)
        self.search_entry.pack(fill=tk.X, expand=True, ipady=3)
        self.search_var.trace_add("write", self._debounce_search)
        
        self.exclusion_frame = ttk.Frame(self.tree_frame)
        self.exclusion_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(self.exclusion_frame, text="Exclude (regex):").pack(side=tk.LEFT, padx=(0,5))
        self.exclusion_var = tk.StringVar(value=r"venv/|\.git/|\.idea/|\.vscode/|__pycache__|.*\.log|.*\.json|.*\.csv|.*\.env")
        self.exclusion_entry = ttk.Entry(self.exclusion_frame, textvariable=self.exclusion_var)
        self.exclusion_entry.pack(fill=tk.X, expand=True, ipady=3)
        self.exclusion_var.trace_add("write", self._debounce_search)
        
        self.tree_controls = ttk.Frame(self.tree_frame)
        self.tree_controls.pack(fill=tk.X, pady=(0, 5))
        self.btn_add_folder = ttk.Button(self.tree_controls, text="Add Selected Folder", command=self.add_selected_folder)
        self.btn_add_folder.pack(side=tk.LEFT)
        
        # Add expand/collapse buttons
        self.btn_expand_all = ttk.Button(self.tree_controls, text="Expand All", command=self.expand_all_tree_items)
        self.btn_expand_all.pack(side=tk.LEFT, padx=(5, 0))
        self.btn_collapse_all = ttk.Button(self.tree_controls, text="Collapse All", command=self.collapse_all_tree_items)
        self.btn_collapse_all.pack(side=tk.LEFT, padx=(5, 0))
        
        self.tree = ttk.Treeview(self.tree_frame, show="tree headings")
        self.tree.heading("#0", text="Project Structure", anchor='w')
        
        ysb = ttk.Scrollbar(self.tree_frame, orient='vertical', command=self.tree.yview)
        xsb = ttk.Scrollbar(self.tree_frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscroll=ysb.set, xscroll=xsb.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        xsb.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.main_pane.add(self.tree_frame, weight=2) # Give tree more initial space

        # --- Right Pane: Selected Files ---
        self.selection_frame = ttk.Frame(self.main_pane, padding=(5,0,0,0))
        ttk.Label(self.selection_frame, text="Selected Files (Drag to Reorder)", font=(base_font[0], base_font[1], "bold")).pack(pady=(0, 5), anchor='w')
        
        self.listbox_frame = ttk.Frame(self.selection_frame)
        self.listbox_frame.pack(fill=tk.BOTH, expand=True)
        
        self.listbox = tk.Listbox(self.listbox_frame, selectmode=tk.SINGLE, borderwidth=0, relief="flat",
                                 bg=DARK_TREE_BG, fg=DARK_FG, selectbackground=DARK_SELECT_BG, 
                                 selectforeground=DARK_SELECT_FG, font=base_font, highlightthickness=0)
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
        
        self.main_pane.add(self.selection_frame, weight=3)

        # --- Bottom Frame ---
        self.bottom_frame = ttk.Frame(self.main_container)
        self.bottom_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.status_var = tk.StringVar(value="Ready.")
        self.status_label = ttk.Label(self.bottom_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor='w', padding=5)
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        self.btn_toggle_preview = ttk.Button(self.bottom_frame, text="Show Preview", command=self.toggle_preview)
        self.btn_toggle_preview.pack(side=tk.LEFT, padx=(0, 5))
        
        self.btn_copy = ttk.Button(self.bottom_frame, text="Copy to Clipboard", command=self.copy_to_clipboard, style='Accent.TButton')
        self.btn_copy.pack(side=tk.RIGHT)
        
        style.configure('Accent.TButton', font=(base_font[0], base_font[1], "bold"), 
                       background="#0078d4", foreground=DARK_FG)
        style.map('Accent.TButton', background=[('active', '#106ebe')])

        # --- Preview Frame (initially hidden) ---
        self.preview_frame = ttk.Frame(self.main_container)
        ttk.Label(self.preview_frame, text="Preview", font=(base_font[0], base_font[1], "bold")).pack(anchor='w', pady=(5, 0))
        
        self.preview_text = scrolledtext.ScrolledText(
            self.preview_frame, height=10, wrap=tk.WORD, bg=DARK_ENTRY_BG, fg=DARK_FG, 
            insertbackground=DARK_FG, selectbackground=DARK_SELECT_BG, selectforeground=DARK_SELECT_FG,
            font=("Consolas", 10) if sys.platform == "win32" else ("Monaco", 10),
            borderwidth=0, highlightthickness=1, highlightcolor=DARK_SELECT_BG)
        self.preview_text.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        
        # --- Bindings ---
        self.tree.bind("<Double-1>", self.on_tree_double_click)
        self.listbox.bind("<Double-1>", lambda e: self.remove_selected())
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.listbox.bind("<Button-1>", self.on_drag_start)
        self.listbox.bind("<B1-Motion>", self.on_drag_motion)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.update_preview())
        self.tree.bind('<<TreeviewOpen>>', self.on_tree_expand)

        # **IMPROVEMENT**: Bind Ctrl+A for "Select All"
        self._bind_select_all(self.search_entry)
        self._bind_select_all(self.exclusion_entry)
        self._bind_select_all(self.preview_text)
        
        self.drag_start_index: Optional[int] = None
        
        self._setup_interrupt_handler()

        # --- Population ---
        self._scan_and_cache_all_files()
        self.repopulate_tree()
        self.load_selection_state()
        self.update_selected_count()

    def _bind_select_all(self, widget: tk.Widget):
        """Binds Ctrl+A/Cmd+A to a widget for 'select all' functionality."""
        def select_all(event=None):
            # For Entry and Text widgets
            if isinstance(widget, (ttk.Entry, tk.Entry)):
                widget.select_range(0, 'end')
            elif isinstance(widget, (scrolledtext.ScrolledText, tk.Text)):
                widget.tag_add('sel', '1.0', 'end')
            return "break" # Prevents the event from propagating further

        widget.bind_class("TEntry", "<Control-a>", select_all)
        widget.bind_class("TEntry", "<Command-a>", select_all) # For macOS
        widget.bind("<Control-a>", select_all)
        widget.bind("<Command-a>", select_all) # For macOS

    def _setup_interrupt_handler(self):
        """Sets up a graceful shutdown on Ctrl+C."""
        self.interrupted = False
        original_sigint_handler = signal.getsignal(signal.SIGINT)
        def handle_sigint(signum, frame):
            self.interrupted = True
            if callable(original_sigint_handler):
                original_sigint_handler(signum, frame)
        signal.signal(signal.SIGINT, handle_sigint)
        self.root.after(250, self._check_for_interrupt)

    def _check_for_interrupt(self):
        if self.interrupted:
            self.on_closing()
        else:
            self.root.after(250, self._check_for_interrupt)

    def _scan_and_cache_all_files(self):
        """**IMPROVEMENT**: Scans the entire directory once and caches the file list."""
        self.status_var.set("Scanning project files...")
        self.root.update_idletasks()
        self.all_text_files = []
        exclusion_regex = self._get_exclusion_regex()
        
        for root, dirs, files in os.walk(self.directory, topdown=True):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]
            for filename in files:
                if filename in IGNORE_FILES or (filename.startswith('.') and filename not in {'.env', '.gitignore'}):
                    continue

                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, self.directory)
                normalized_rel_path = rel_path.replace(os.path.sep, '/')

                if exclusion_regex and exclusion_regex.search(normalized_rel_path):
                    continue

                if is_text_file(full_path):
                    self.all_text_files.append(rel_path)
        
        self.all_text_files.sort(key=str.lower)
        self.status_var.set(f"Ready. Found {len(self.all_text_files)} text files.")

    def _debounce_search(self, *args):
        """**IMPROVEMENT**: Delays search to prevent lag while typing."""
        if self._search_job:
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(250, self._perform_filter) # 250ms debounce

    def _perform_filter(self):
        """**IMPROVEMENT**: Filters the cached file list and updates the tree."""
        search_term = self.search_var.get().lower()
        exclusion_regex = self._get_exclusion_regex()
        
        if not search_term and not exclusion_regex:
            self.repopulate_tree() # Show default lazy-loaded tree
            return
        
        filtered_files = []
        for file_path in self.all_text_files:
            # Check against exclusion regex first
            if exclusion_regex and exclusion_regex.search(file_path.replace(os.path.sep, '/')):
                continue
            
            # Check against search term
            if search_term and search_term not in os.path.basename(file_path).lower():
                continue
            
            filtered_files.append(file_path)
            
        self.repopulate_tree(filtered_files)

    def repopulate_tree(self, files_to_display: Optional[List[str]] = None):
        """Repopulates the tree. If files are provided, it's a flat filtered list.
           Otherwise, it shows the default lazy-loaded directory structure."""
        for item in self.tree.get_children():
            self.tree.delete(item)

        if files_to_display is None:
            # Lazy-loading mode (no filter)
            self.tree.bind('<<TreeviewOpen>>', self.on_tree_expand)
            self.process_directory("", self.directory)
            return

        # Filtered mode (flat list, lazy-loading disabled)
        self.tree.unbind('<<TreeviewOpen>>')
        if not files_to_display:
            self.tree.insert("", "end", text="No matching files found.", tags=('info',))
            self.tree.tag_configure('info', foreground='#888888')
            return
            
        nodes = {"": ""} # key: relative path, value: item_id
        for file_path in files_to_display:
            parent_path = ""
            path_parts = file_path.split(os.path.sep)
            
            for i, part in enumerate(path_parts[:-1]):
                current_path = os.path.join(*path_parts[:i+1])
                if current_path not in nodes:
                    parent_node_id = nodes.get(parent_path, "")
                    dir_id = self.tree.insert(parent_node_id, 'end', text=f"📁 {part}", values=[current_path], tags=('folder',), open=True)
                    nodes[current_path] = dir_id
                parent_path = current_path

            file_name = path_parts[-1]
            parent_node_id = nodes.get(parent_path, "")
            self.tree.insert(parent_node_id, 'end', text=f"📄 {file_name}", values=[file_path], tags=('file',))
            
        self.tree.tag_configure('file', foreground='#87CEEB')
        self.tree.tag_configure('folder', foreground='#DDA0DD')

    def _get_exclusion_regex(self) -> Optional[re.Pattern]:
        patterns_str = self.exclusion_var.get()
        if not patterns_str: return None
        try:
            return re.compile(patterns_str, re.IGNORECASE)
        except re.error as e:
            self.status_var.set(f"Invalid exclusion regex: {e}")
            return None

    def process_directory(self, parent_id: str, path: str) -> None:
        children = self.tree.get_children(parent_id)
        for child_id in children:
            if self.tree.item(child_id, "values") == ("dummy",):
                self.tree.delete(child_id)
        
        try: 
            items = sorted(os.listdir(path), key=str.lower)
        except (OSError, PermissionError) as e:
            self.status_var.set(f"Error accessing {path}: {e}")
            return

        exclusion_regex = self._get_exclusion_regex()
        dirs_to_process, files_to_process = [], []
        
        for name in items:
            if name.startswith('.') and name not in {'.env', '.gitignore'}: continue
            if name in IGNORE_FILES: continue

            full_path = os.path.join(path, name)
            rel_path = os.path.relpath(full_path, self.directory)
            if exclusion_regex and exclusion_regex.search(rel_path.replace(os.path.sep, '/')): continue
                
            if os.path.isdir(full_path):
                if name not in IGNORE_DIRS: dirs_to_process.append(name)
            elif is_text_file(full_path):
                files_to_process.append(name)

        for dir_name in dirs_to_process:
            rel_path = os.path.relpath(os.path.join(path, dir_name), self.directory)
            dir_id = self.tree.insert(parent_id, 'end', text=f"📁 {dir_name}", values=[rel_path], tags=('folder',))
            self.tree.insert(dir_id, 'end', text='...', values=['dummy'])

        for file_name in files_to_process:
            rel_path = os.path.relpath(os.path.join(path, file_name), self.directory)
            self.tree.insert(parent_id, 'end', text=f"📄 {file_name}", values=[rel_path], tags=('file',))
        
        self.tree.tag_configure('file', foreground='#87CEEB')
        self.tree.tag_configure('folder', foreground='#DDA0DD')

    # --- Event Handlers and Core Logic (mostly unchanged, but some simplified) ---
    
    def on_tree_expand(self, event: tk.Event) -> None:
        item_id = self.tree.focus()
        children = self.tree.get_children(item_id)
        if children and self.tree.item(children[0], "values") == ("dummy",):
            item_path = self.tree.item(item_id, "values")[0]
            full_path = os.path.join(self.directory, item_path)
            self.process_directory(item_id, full_path)

    def get_all_files_in_folder(self, folder_rel_path: str) -> List[str]:
        """Recursively get all text files in a folder from the cache."""
        # This now filters the cache instead of walking the disk again
        files_in_folder = []
        # Normalize path for reliable matching
        prefix = folder_rel_path.replace(os.path.sep, '/') + '/'
        for file_path in self.all_text_files:
            if file_path.replace(os.path.sep, '/').startswith(prefix):
                files_in_folder.append(file_path)
        return files_in_folder

    def add_selected_folder(self) -> None:
        selection = self.tree.selection()
        if not selection: return
        
        item = self.tree.item(selection[0])
        if 'folder' not in item['tags']:
            self.status_var.set("Please select a folder.")
            return
        
        folder_rel_path = item['values'][0]
        files = self.get_all_files_in_folder(folder_rel_path)
        
        if not files:
            self.status_var.set(f"No text files found in {folder_rel_path}")
            return
        
        added_count = 0
        for file_path in files:
            if file_path not in self.selected_files_map:
                self.listbox.insert(tk.END, file_path)
                self.selected_files_map[file_path] = True
                added_count += 1
        
        self.update_selected_count()
        self.update_preview()
        self.status_var.set(f"Added {added_count} file(s) from {os.path.basename(folder_rel_path)}")

    def on_tree_double_click(self, event: tk.Event) -> None:
        item_id = self.tree.identify_row(event.y)
        if not item_id: return
        item = self.tree.item(item_id)
        
        if 'file' in item['tags']:
            file_path = item['values'][0]
            if file_path not in self.selected_files_map:
                self.listbox.insert(tk.END, file_path)
                self.selected_files_map[file_path] = True
                self.update_selected_count()
                self.update_preview()
        elif 'folder' in item['tags']:
            self.tree.selection_set(item_id)
            self.add_selected_folder()
    
    def remove_selected(self) -> None:
        selection = self.listbox.curselection()
        if selection:
            index = selection[0]
            file_path = self.listbox.get(index)
            self.listbox.delete(index)
            if file_path in self.selected_files_map: del self.selected_files_map[file_path]
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
        if self.preview_visible:
            self.preview_frame.pack_forget()
            self.btn_toggle_preview.configure(text="Show Preview")
            self.preview_visible = False
        else:
            self.preview_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, pady=(10, 0), in_=self.main_container)
            self.btn_toggle_preview.configure(text="Hide Preview")
            self.preview_visible = True
            self.update_preview()

    def update_preview(self) -> None:
        if not self.preview_visible: return
        self.preview_text.delete(1.0, tk.END)
        selected_files = self.listbox.get(0, tk.END)
        if not selected_files:
            self.preview_text.insert(1.0, "No files selected.")
            return
        
        output_str = self.generate_clipboard_content(max_preview_size=200000) # Limit preview size
        self.preview_text.insert(1.0, output_str)
        self.preview_text.see(1.0)

    def generate_clipboard_content(self, max_preview_size: Optional[int] = None) -> str:
        selected_files = self.listbox.get(0, tk.END)
        output_parts, total_size = [], 0
        
        for i, rel_path in enumerate(selected_files):
            if max_preview_size and total_size > max_preview_size:
                remaining = len(selected_files) - i
                output_parts.append(f"\n... and {remaining} more file(s) not shown in preview ...")
                break
                
            try:
                full_path = os.path.join(self.directory, os.path.normpath(rel_path))
                header = f"# {rel_path.replace(os.path.sep, '/')}"
                language_hint = get_language_hint(rel_path)
                with open(full_path, 'r', encoding='utf-8', errors='replace') as f: content = f.read()
                formatted_block = f"{header}\n```{language_hint}\n{content}\n```"
                output_parts.append(formatted_block)
                if max_preview_size: total_size += len(formatted_block)
            except Exception as e:
                error_block = f"# ERROR: Could not read {rel_path}\n```\n{e}\n```"
                output_parts.append(error_block)
                if max_preview_size: total_size += len(error_block)
        
        return "\n\n".join(output_parts)

    def copy_to_clipboard(self) -> None:
        if pyperclip is None:
            messagebox.showerror("Error", "Could not copy. 'pyperclip' library not found.\n\nPlease install it: pip install pyperclip")
            return
        
        if not self.listbox.get(0, tk.END):
            self.status_var.set("No files selected to copy.")
            return
        
        self.status_var.set("Processing and copying...")
        self.root.update_idletasks()
        
        final_output = self.generate_clipboard_content()
        pyperclip.copy(final_output)
        
        size_kb = len(final_output) / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
        self.status_var.set(f"✅ Copied {self.listbox.size()} file(s) to clipboard! ({size_str})")

    def save_selection_state(self) -> None:
        try:
            with open(self.state_file_path, 'w') as f: 
                json.dump({
                    "version": 4, "project_directory": self.directory,
                    "selected_files": list(self.listbox.get(0, tk.END)),
                    "exclusion_pattern": self.exclusion_var.get()
                }, f, indent=2)
        except IOError as e: print(f"Warning: Could not save selection state: {e}")

    def load_selection_state(self) -> None:
        if not os.path.exists(self.state_file_path): return
        try:
            with open(self.state_file_path, 'r') as f: data = json.load(f)
            if data.get("project_directory") != self.directory: return
            if "exclusion_pattern" in data: self.exclusion_var.set(data["exclusion_pattern"])

            for file_path in data.get("selected_files", []):
                full_path = os.path.join(self.directory, os.path.normpath(file_path))
                if os.path.exists(full_path) and file_path not in self.selected_files_map:
                    self.listbox.insert(tk.END, file_path)
                    self.selected_files_map[file_path] = True
            self.update_selected_count()
        except (json.JSONDecodeError, IOError) as e: print(f"Warning: Could not load state file: {e}")

    def on_closing(self) -> None:
        self.save_selection_state()
        self.root.destroy()
    
    def on_drag_start(self, event: tk.Event) -> None:
        self.drag_start_index = event.widget.nearest(event.y)

    def on_drag_motion(self, event: tk.Event) -> None:
        if self.drag_start_index is None: return
        current_index = event.widget.nearest(event.y)
        if current_index != self.drag_start_index:
            item = self.listbox.get(self.drag_start_index)
            self.listbox.delete(self.drag_start_index)
            self.listbox.insert(current_index, item)
            self.drag_start_index = current_index
            self.update_preview()

    def expand_all_tree_items(self) -> None:
        """Expand all tree items recursively."""
        for item_id in self.tree.get_children():
            self._expand_tree_item_recursive(item_id)

    def _expand_tree_item_recursive(self, item_id: str) -> None:
        """Recursively expand a tree item and all its children."""
        # Get item info
        item_info = self.tree.item(item_id)
        
        # Only expand folders (items with 'folder' tag or items that have children)
        if 'folder' in item_info.get('tags', []) or self.tree.get_children(item_id):
            self.tree.item(item_id, open=True)
            
            # If this folder has a dummy child, expand it to load actual contents
            children = self.tree.get_children(item_id)
            if children and len(children) == 1:
                dummy_child = children[0]
                if self.tree.item(dummy_child, "values") == ("dummy",):
                    # Trigger lazy loading by simulating tree expansion
                    item_path = item_info.get('values', [''])[0]
                    if item_path:
                        full_path = os.path.join(self.directory, item_path)
                        self.process_directory(item_id, full_path)
            
            # Recursively expand all children
            for child_id in self.tree.get_children(item_id):
                self._expand_tree_item_recursive(child_id)

    def collapse_all_tree_items(self) -> None:
        """Collapse all tree items recursively."""
        for item_id in self.tree.get_children():
            self._collapse_tree_item_recursive(item_id)

    def _collapse_tree_item_recursive(self, item_id: str) -> None:
        """Recursively collapse a tree item and all its children."""
        # First collapse all children
        for child_id in self.tree.get_children(item_id):
            self._collapse_tree_item_recursive(child_id)
        
        # Then collapse this item if it's a folder
        item_info = self.tree.item(item_id)
        if 'folder' in item_info.get('tags', []) or self.tree.get_children(item_id):
            self.tree.item(item_id, open=False)

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