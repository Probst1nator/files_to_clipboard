import os
import sys
import json
import argparse
import re
import signal
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog
from typing import Dict, List, Set, Optional, Tuple
import base64

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
PRIMARY_PRESET_NAME = "primary"
# NEW: A single config file stored next to the script.
CONFIG_FILENAME = ".file_copier_config.json" 
IGNORE_DIRS: Set[str] = {"__pycache__", "node_modules", "venv", "dist", "build", ".git", ".idea", ".vscode"}
IGNORE_FILES: Set[str] = {".DS_Store", CONFIG_FILENAME, ".gitignore", ".env"}

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

def is_includable_file(filepath: str) -> bool:
    """
    Returns True if the file should be included in the selectable list (text or supported binary types).
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext in {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}:
        return True
    return is_text_file(filepath)

def get_language_hint(filename: str) -> str:
    _, extension = os.path.splitext(filename)
    return extension[1:].lower() if extension else ""

def get_script_directory() -> str:
    try:
        # Favour the actual script location
        script_path = os.path.abspath(__file__)
        return os.path.dirname(script_path)
    except NameError:
        # Fallback for environments where __file__ is not defined (e.g. some frozen apps)
        return os.getcwd()


class FileCopierApp:
    def __init__(self, root: tk.Tk, directory: str):
        self.root = root
        self.directory = os.path.abspath(directory)
        
        # CHANGED: The config file path is now relative to the script's location.
        self.config_file_path = os.path.join(get_script_directory(), CONFIG_FILENAME)

        self.root.title(f"File Content Copier - {os.path.basename(self.directory)}")
        self.root.geometry("1200x850")
        self.root.configure(bg=DARK_BG)

        # --- Style Configuration ---
        style = ttk.Style()
        base_font = ("Segoe UI", 10) if sys.platform == "win32" else ("Helvetica", 11)
        
        style.theme_use('clam')
        style.configure('.', font=base_font, background=DARK_BG, foreground=DARK_FG)
        style.configure("TFrame", background=DARK_BG)
        style.configure("TLabel", background=DARK_BG, foreground=DARK_FG)
        style.configure("TCombobox", fieldbackground=DARK_ENTRY_BG, background=DARK_ENTRY_BG,
                       foreground=DARK_FG, bordercolor=DARK_SELECT_BG, insertcolor=DARK_FG,
                       arrowcolor=DARK_FG)
        style.map('TCombobox', fieldbackground=[('readonly', DARK_ENTRY_BG)])
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
        self._auto_save_job: Optional[str] = None
        
        # NEW: State management variables
        self.full_config: Dict[str, Dict] = {} # Holds data for all projects
        self.project_data: Dict[str, any] = {} # Holds data for the current project
        self.presets: Dict[str, Dict] = {}     # A direct reference to the presets within project_data

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
        self.main_pane.add(self.tree_frame, weight=2)

        # --- Right Pane: Selected Files ---
        self.selection_frame = ttk.Frame(self.main_pane, padding=(5,0,0,0))
        
        self.preset_frame = ttk.Frame(self.selection_frame)
        self.preset_frame.pack(fill=tk.X, pady=(0, 15))
        ttk.Label(self.preset_frame, text="Preset:").pack(side=tk.LEFT, padx=(0, 5))
        self.preset_var = tk.StringVar()
        self.preset_combobox = ttk.Combobox(self.preset_frame, textvariable=self.preset_var, state="readonly")
        self.preset_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.btn_save_as_preset = ttk.Button(self.preset_frame, text="Save As...", command=self.save_current_as_preset, width=10)
        self.btn_save_as_preset.pack(side=tk.LEFT, padx=(5, 0))
        self.btn_remove_preset = ttk.Button(self.preset_frame, text="Remove", command=self.remove_selected_preset, width=8)
        self.btn_remove_preset.pack(side=tk.LEFT, padx=(5, 0))

        ttk.Label(self.selection_frame, text="Selected Files (Drag to Reorder)", font=(base_font[0], base_font[1], "bold")).pack(pady=(0, 5), anchor='w')
        self.listbox_frame = ttk.Frame(self.selection_frame)
        self.listbox_frame.pack(fill=tk.BOTH, expand=True)
        
        self.listbox = tk.Listbox(self.listbox_frame, selectmode=tk.SINGLE, borderwidth=0, relief="flat", bg=DARK_TREE_BG, fg=DARK_FG, selectbackground=DARK_SELECT_BG, selectforeground=DARK_SELECT_FG, font=base_font, highlightthickness=0)
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
        style.configure('Accent.TButton', font=(base_font[0], base_font[1], "bold"), background="#0078d4", foreground=DARK_FG)
        style.map('Accent.TButton', background=[('active', '#106ebe')])

        # --- Preview Frame ---
        self.preview_frame = ttk.Frame(self.main_container)
        
        preview_header_frame = ttk.Frame(self.preview_frame)
        preview_header_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(preview_header_frame, text="Preview", font=(base_font[0], base_font[1], "bold")).pack(side=tk.LEFT, anchor='w')
        self.preview_stats_var = tk.StringVar(value="")
        ttk.Label(preview_header_frame, textvariable=self.preview_stats_var, foreground="#aaaaaa").pack(side=tk.RIGHT, anchor='e')
        
        self.preview_text = scrolledtext.ScrolledText(self.preview_frame, height=10, wrap=tk.WORD, bg=DARK_ENTRY_BG, fg=DARK_FG, insertbackground=DARK_FG, selectbackground=DARK_SELECT_BG, selectforeground=DARK_SELECT_FG, font=("Consolas", 10) if sys.platform == "win32" else ("Monaco", 10), borderwidth=0, highlightthickness=1, highlightcolor=DARK_SELECT_BG)
        self.preview_text.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        
        # --- Bindings & Population ---
        self.tree.bind("<Double-1>", self.on_tree_double_click)
        self.listbox.bind("<Double-1>", lambda e: self.remove_selected())
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.listbox.bind("<Button-1>", self.on_drag_start)
        self.listbox.bind("<B1-Motion>", self.on_drag_motion)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.update_preview())
        self.tree.bind('<<TreeviewOpen>>', self.on_tree_expand)
        self.preset_combobox.bind("<<ComboboxSelected>>", self.on_preset_selected)
        self._bind_select_all(self.search_entry)
        self._bind_select_all(self.exclusion_entry)
        self._bind_select_all(self.preview_text)
        self.drag_start_index: Optional[int] = None
        self._setup_interrupt_handler()

        # Initialize exclusion pattern tracking
        self._last_exclusion_pattern = self.exclusion_var.get()
        
        self.load_project_config()
        self._scan_and_cache_all_files()
        self.load_preset_into_ui()

    # --- Config and Preset Management ---
    def load_project_config(self):
        """Loads the single config file and isolates the data for the current project."""
        try:
            if os.path.exists(self.config_file_path):
                with open(self.config_file_path, 'r', encoding='utf-8') as f:
                    self.full_config = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self.status_var.set(f"Warning: Could not load config: {e}")
            self.full_config = {}

        if self.directory not in self.full_config:
            # First time seeing this project, create a default entry.
            default_primary_preset = {"selected_files": [], "filter_text": "", "exclusion_regex": self.exclusion_var.get()}
            self.full_config[self.directory] = {
                "presets": {PRIMARY_PRESET_NAME: default_primary_preset},
                "last_active_preset": PRIMARY_PRESET_NAME
            }

        self.project_data = self.full_config[self.directory]
        self.presets = self.project_data['presets'] # Reference to the project's presets

        # Ensure primary preset exists for this project
        if PRIMARY_PRESET_NAME not in self.presets:
            self.presets[PRIMARY_PRESET_NAME] = {"selected_files": [], "filter_text": "", "exclusion_regex": self.exclusion_var.get()}
        
        self.update_preset_combobox()
        last_active = self.project_data.get("last_active_preset", PRIMARY_PRESET_NAME)
        self.preset_var.set(last_active if last_active in self.presets else PRIMARY_PRESET_NAME)

    def save_config(self, quiet: bool = True):
        """Saves the entire configuration object back to the single file."""
        self.project_data['last_active_preset'] = self.preset_var.get()
        try:
            with open(self.config_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.full_config, f, indent=4)
            if not quiet:
                self.status_var.set(f"Changes saved to preset '{self.preset_var.get()}'.")
        except IOError as e:
            self.status_var.set(f"Error: Could not save config: {e}")
            messagebox.showerror("Config Error", f"Could not save config to file:\n{e}")

    def _debounce_auto_save(self, *args):
        if self._auto_save_job: self.root.after_cancel(self._auto_save_job)
        self._auto_save_job = self.root.after(1500, self.auto_save_current_preset)

    def auto_save_current_preset(self):
        """Saves the current UI state to the active preset in memory and then saves the config to disk."""
        current_preset_name = self.preset_var.get()
        if not current_preset_name: return

        preset_data = {"selected_files": list(self.listbox.get(0, tk.END)), "filter_text": self.search_var.get(), "exclusion_regex": self.exclusion_var.get()}
        
        if self.presets.get(current_preset_name) != preset_data:
            self.presets[current_preset_name] = preset_data
            self.save_config()

    def update_preset_combobox(self):
        preset_names = list(self.presets.keys())
        if PRIMARY_PRESET_NAME in preset_names: preset_names.remove(PRIMARY_PRESET_NAME)
        preset_names.sort(key=str.lower); preset_names.insert(0, PRIMARY_PRESET_NAME)
        current_selection = self.preset_var.get()
        self.preset_combobox['values'] = preset_names
        if current_selection in preset_names: self.preset_var.set(current_selection)

    def save_current_as_preset(self):
        preset_name = simpledialog.askstring("Save New Preset", "Enter a name for this new preset:", parent=self.root)
        if not preset_name or not preset_name.strip(): self.status_var.set("Preset save cancelled."); return
        preset_name = preset_name.strip()
        if preset_name in self.presets and not messagebox.askyesno("Confirm Overwrite", f"A preset named '{preset_name}' already exists. Overwrite?", parent=self.root):
            self.status_var.set("Preset save cancelled."); return
        preset_data = {"selected_files": list(self.listbox.get(0, tk.END)), "filter_text": self.search_var.get(), "exclusion_regex": self.exclusion_var.get()}
        self.presets[preset_name] = preset_data
        self.update_preset_combobox()
        self.preset_var.set(preset_name)
        self.save_config(quiet=False) # Save immediately and give feedback
        self.status_var.set(f"Preset '{preset_name}' saved and is now active.")

    def on_preset_selected(self, event=None):
        """Handles combobox selection, loading the new preset."""
        self.load_preset_into_ui()
        self._debounce_auto_save() # Save the change of active preset

    def load_preset_into_ui(self):
        """Loads the files and filters from the currently selected preset in the combobox."""
        preset_name = self.preset_var.get()
        if not preset_name or preset_name not in self.presets: return
        self.status_var.set(f"Loading preset '{preset_name}'..."); self.root.update_idletasks()
        preset_data = self.presets[preset_name]
        self.search_var.set(preset_data.get("filter_text", "")); self.exclusion_var.set(preset_data.get("exclusion_regex", ""))
        self._perform_filter(from_preset_load=True) # Prevent double auto-save
        self.clear_all(auto_save=False)
        selected_files, files_added_count = preset_data.get("selected_files", []), 0
        for file_path in selected_files:
            full_path = os.path.join(self.directory, os.path.normpath(file_path))
            if os.path.exists(full_path) and file_path not in self.selected_files_map:
                self.listbox.insert(tk.END, file_path); self.selected_files_map[file_path] = True; files_added_count += 1
            else: print(f"Preset file not found, skipping: {file_path}")
        self.update_selected_count(); self.update_preview()
        self.status_var.set(f"Loaded preset '{preset_name}'. ({files_added_count}/{len(selected_files)} files found).")

    def remove_selected_preset(self):
        preset_name = self.preset_var.get()
        if not preset_name: self.status_var.set("No preset selected to remove."); return
        if preset_name == PRIMARY_PRESET_NAME:
            messagebox.showerror("Action Denied", f"The '{PRIMARY_PRESET_NAME}' preset cannot be removed.", parent=self.root); return
        if messagebox.askyesno("Confirm Deletion", f"Are you sure you want to delete the preset '{preset_name}'?", parent=self.root):
            if preset_name in self.presets:
                del self.presets[preset_name]
                self.update_preset_combobox()
                self.status_var.set(f"Preset '{preset_name}' removed. Reverting to '{PRIMARY_PRESET_NAME}'.")
                self.preset_var.set(PRIMARY_PRESET_NAME)
                self.load_preset_into_ui()
                self.save_config(quiet=True)

    def _bind_select_all(self, widget: tk.Widget):
        def select_all(event=None):
            if isinstance(widget, (ttk.Entry, tk.Entry)): widget.select_range(0, 'end')
            elif isinstance(widget, (scrolledtext.ScrolledText, tk.Text)): widget.tag_add('sel', '1.0', 'end')
            return "break"
        widget.bind_class("TEntry", "<Control-a>", select_all); widget.bind_class("TEntry", "<Command-a>", select_all)
        widget.bind("<Control-a>", select_all); widget.bind("<Command-a>", select_all)

    def _setup_interrupt_handler(self):
        self.interrupted = False; original_sigint_handler = signal.getsignal(signal.SIGINT)
        def handle_sigint(signum, frame): self.interrupted = True; original_sigint_handler(signum, frame)
        try: signal.signal(signal.SIGINT, handle_sigint)
        except (ValueError, TypeError): pass
        self.root.after(250, self._check_for_interrupt)

    def _check_for_interrupt(self):
        if self.interrupted: self.on_closing()
        else: self.root.after(250, self._check_for_interrupt)

    def _scan_and_cache_all_files(self):
        self.status_var.set("Scanning project files..."); self.root.update_idletasks(); self.all_text_files = []
        exclusion_regex = self._get_exclusion_regex()
        for root, dirs, files in os.walk(self.directory, topdown=True):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]
            for filename in files:
                if filename in IGNORE_FILES: continue
                full_path = os.path.join(root, filename); rel_path = os.path.relpath(full_path, self.directory)
                normalized_rel_path = rel_path.replace(os.path.sep, '/')
                if exclusion_regex and exclusion_regex.search(normalized_rel_path): continue
                if is_includable_file(full_path): self.all_text_files.append(rel_path)
        self.all_text_files.sort(key=str.lower)
        self.status_var.set(f"Ready. Found {len(self.all_text_files)} text/binary files.")

    def _debounce_search(self, *args):
        if self._search_job: self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(250, self._perform_filter)

    def _perform_filter(self, from_preset_load: bool = False):
        search_term = self.search_var.get().lower()
        exclusion_regex = self._get_exclusion_regex()
        
        # Check if exclusion pattern has changed - if so, we need to rescan files
        current_exclusion_pattern = self.exclusion_var.get()
        if not hasattr(self, '_last_exclusion_pattern'):
            self._last_exclusion_pattern = current_exclusion_pattern
        elif self._last_exclusion_pattern != current_exclusion_pattern:
            self._last_exclusion_pattern = current_exclusion_pattern
            # Exclusion pattern changed, need to rescan to pick up previously excluded files
            self.status_var.set("Exclusion pattern changed, rescanning files...")
            self.root.update_idletasks()
            self._scan_and_cache_all_files()
            # Update the exclusion_regex after rescanning
            exclusion_regex = self._get_exclusion_regex()
        
        filtered_files = [f for f in self.all_text_files if not (exclusion_regex and exclusion_regex.search(f.replace(os.path.sep, '/'))) and not (search_term and search_term not in os.path.basename(f).lower())]
        self.repopulate_tree(filtered_files if search_term or self._get_exclusion_regex() else None)
        if not from_preset_load: self._debounce_auto_save()

    def repopulate_tree(self, files_to_display: Optional[List[str]] = None):
        for item in self.tree.get_children(): self.tree.delete(item)
        if files_to_display is None:
            self.tree.bind('<<TreeviewOpen>>', self.on_tree_expand); self.process_directory("", self.directory); return
        self.tree.unbind('<<TreeviewOpen>>')
        if not files_to_display: self.tree.insert("", "end", text="No matching files found.", tags=('info',)); self.tree.tag_configure('info', foreground='#888888'); return
        nodes = {"": ""}
        for file_path in files_to_display:
            parent_path, path_parts = "", file_path.split(os.path.sep)
            for i, part in enumerate(path_parts[:-1]):
                current_path = os.path.join(*path_parts[:i+1])
                if current_path not in nodes:
                    parent_node_id = nodes.get(parent_path, ""); dir_id = self.tree.insert(parent_node_id, 'end', text=f"📁 {part}", values=[current_path], tags=('folder',), open=True)
                    nodes[current_path] = dir_id
                parent_path = current_path
            self.tree.insert(nodes.get(parent_path, ""), 'end', text=f"📄 {path_parts[-1]}", values=[file_path], tags=('file',))
        self.tree.tag_configure('file', foreground='#87CEEB'); self.tree.tag_configure('folder', foreground='#DDA0DD')

    def _get_exclusion_regex(self) -> Optional[re.Pattern]:
        patterns_str = self.exclusion_var.get()
        if not patterns_str: return None
        try: return re.compile(patterns_str, re.IGNORECASE)
        except re.error as e: self.status_var.set(f"Invalid exclusion regex: {e}"); return None

    def process_directory(self, parent_id: str, path: str) -> None:
        for child_id in self.tree.get_children(parent_id):
            if self.tree.item(child_id, "values") == ("dummy",): self.tree.delete(child_id)
        try: items = sorted(os.listdir(path), key=str.lower)
        except (OSError, PermissionError) as e: self.status_var.set(f"Error accessing {path}: {e}"); return
        exclusion_regex, dirs_to_process, files_to_process = self._get_exclusion_regex(), [], []
        for name in items:
            if name in IGNORE_FILES: continue
            full_path = os.path.join(path, name); rel_path = os.path.relpath(full_path, self.directory)
            if exclusion_regex and exclusion_regex.search(rel_path.replace(os.path.sep, '/')): continue
            if os.path.isdir(full_path):
                if name not in IGNORE_DIRS and not name.startswith('.'): dirs_to_process.append(name)
            elif is_includable_file(full_path) and not name.startswith('.'): files_to_process.append(name)
        for dir_name in dirs_to_process:
            rel_path = os.path.relpath(os.path.join(path, dir_name), self.directory); dir_id = self.tree.insert(parent_id, 'end', text=f"📁 {dir_name}", values=[rel_path], tags=('folder',)); self.tree.insert(dir_id, 'end', text='...', values=['dummy'])
        for file_name in files_to_process:
            rel_path = os.path.relpath(os.path.join(path, file_name), self.directory); self.tree.insert(parent_id, 'end', text=f"📄 {file_name}", values=[rel_path], tags=('file',))
        self.tree.tag_configure('file', foreground='#87CEEB'); self.tree.tag_configure('folder', foreground='#DDA0DD')

    def on_tree_expand(self, event: tk.Event) -> None:
        item_id = self.tree.focus(); children = self.tree.get_children(item_id)
        if children and self.tree.item(children[0], "values") == ("dummy",):
            item_path = self.tree.item(item_id, "values")[0]; full_path = os.path.join(self.directory, item_path); self.process_directory(item_id, full_path)

    def get_all_files_in_folder(self, folder_rel_path: str) -> List[str]:
        prefix = folder_rel_path.replace(os.path.sep, '/') + '/'; return [f for f in self.all_text_files if f.replace(os.path.sep, '/').startswith(prefix)]

    def add_selected_folder(self) -> None:
        selection = self.tree.selection();
        if not selection: return
        item = self.tree.item(selection[0])
        if 'folder' not in item['tags']: self.status_var.set("Please select a folder."); return
        folder_rel_path, files, added_count = item['values'][0], self.get_all_files_in_folder(item['values'][0]), 0
        if not files: self.status_var.set(f"No text files found in {folder_rel_path}"); return
        for file_path in files:
            if file_path not in self.selected_files_map:
                self.listbox.insert(tk.END, file_path); self.selected_files_map[file_path] = True; added_count += 1
        self.update_selected_count(); self.update_preview(); self._debounce_auto_save()
        self.status_var.set(f"Added {added_count} file(s) from {os.path.basename(folder_rel_path)}")

    def on_tree_double_click(self, event: tk.Event) -> None:
        item_id = self.tree.identify_row(event.y);
        if not item_id: return
        item = self.tree.item(item_id)
        if 'file' in item['tags']:
            file_path = item['values'][0]
            if file_path not in self.selected_files_map:
                self.listbox.insert(tk.END, file_path); self.selected_files_map[file_path] = True; self.update_selected_count(); self.update_preview(); self._debounce_auto_save()
        elif 'folder' in item['tags']: self.tree.selection_set(item_id); self.add_selected_folder()
    
    def remove_selected(self) -> None:
        selection = self.listbox.curselection()
        if selection:
            index = selection[0]; file_path = self.listbox.get(index); self.listbox.delete(index)
            if file_path in self.selected_files_map: del self.selected_files_map[file_path]
            self.update_selected_count(); self.update_preview(); self._debounce_auto_save()

    def clear_all(self, auto_save: bool = True) -> None:
        self.listbox.delete(0, tk.END); self.selected_files_map.clear()
        self.update_selected_count(); self.update_preview()
        if auto_save: self._debounce_auto_save()

    def update_selected_count(self) -> None:
        count = self.listbox.size(); self.selected_count_var.set(f"{count} file{'s' if count != 1 else ''} selected")

    def toggle_preview(self) -> None:
        if self.preview_visible: self.preview_frame.pack_forget(); self.btn_toggle_preview.configure(text="Show Preview"); self.preview_visible = False
        else: self.preview_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, pady=(10, 0), in_=self.main_container); self.btn_toggle_preview.configure(text="Hide Preview"); self.preview_visible = True; self.update_preview()

    def update_preview(self) -> None:
        if not self.preview_visible: return
        self.preview_text.delete(1.0, tk.END)
        if not self.listbox.get(0, tk.END):
            self.preview_text.insert(1.0, "No files selected."); self.preview_stats_var.set("Lines: 0 | Chars: 0"); return
        output_str = self.generate_clipboard_content(max_preview_size=200000)
        line_count, char_count = len(output_str.splitlines()), len(output_str)
        self.preview_stats_var.set(f"Lines: {line_count:,} | Chars: {char_count:,}")
        self.preview_text.insert(1.0, output_str); self.preview_text.see(1.0)

    def generate_clipboard_content(self, max_preview_size: Optional[int] = None) -> str:
        selected_files, output_parts, total_size = self.listbox.get(0, tk.END), [], 0
        for i, rel_path in enumerate(selected_files):
            if max_preview_size and total_size > max_preview_size:
                output_parts.append(f"\n... and {len(selected_files) - i} more file(s) not shown in preview ..."); break
            try:
                full_path = os.path.join(self.directory, os.path.normpath(rel_path))
                ext = os.path.splitext(rel_path)[1].lower()
                if ext == '.png':
                    with open(full_path, 'rb') as f:
                        b64 = base64.b64encode(f.read()).decode('ascii')
                    formatted_block = f"# {rel_path.replace(os.path.sep, '/')} (base64 PNG)\n```base64\n{b64}\n```"
                else:
                    header, language_hint = f"# {rel_path.replace(os.path.sep, '/')}" , get_language_hint(rel_path)
                    with open(full_path, 'r', encoding='utf-8', errors='replace') as f: content = f.read()
                    formatted_block = f"{header}\n```{language_hint}\n{content}\n```"
                output_parts.append(formatted_block)
                if max_preview_size: total_size += len(formatted_block)
            except Exception as e:
                error_block = f"# ERROR: Could not read {rel_path}\n```\n{e}\n```"; output_parts.append(error_block)
                if max_preview_size: total_size += len(error_block)
        return "\n\n".join(output_parts)

    def copy_to_clipboard(self) -> None:
        if pyperclip is None:
            messagebox.showerror("Error", "Could not copy. 'pyperclip' not found.\nPlease install it: pip install pyperclip"); return
        if not self.listbox.get(0, tk.END): self.status_var.set("No files selected to copy."); return
        self.status_var.set("Processing and copying..."); self.root.update_idletasks()
        final_output = self.generate_clipboard_content(); pyperclip.copy(final_output)
        size_kb = len(final_output) / 1024; size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
        self.status_var.set(f"✅ Copied {self.listbox.size()} file(s) to clipboard! ({size_str})")

    def on_closing(self) -> None:
        if self._auto_save_job: self.root.after_cancel(self._auto_save_job)
        self.auto_save_current_preset(); self.root.destroy()
    def on_drag_start(self, event: tk.Event) -> None: self.drag_start_index = event.widget.nearest(event.y)
    def on_drag_motion(self, event: tk.Event) -> None:
        if self.drag_start_index is None: return
        current_index = event.widget.nearest(event.y)
        if current_index != self.drag_start_index:
            item = self.listbox.get(self.drag_start_index); self.listbox.delete(self.drag_start_index); self.listbox.insert(current_index, item)
            self.drag_start_index = current_index; self.update_preview(); self._debounce_auto_save()

    def expand_all_tree_items(self) -> None: [self._expand_tree_item_recursive(item) for item in self.tree.get_children()]
    def _expand_tree_item_recursive(self, item_id: str) -> None:
        if 'folder' in self.tree.item(item_id, 'tags') or self.tree.get_children(item_id):
            self.tree.item(item_id, open=True)
            children = self.tree.get_children(item_id)
            if children and self.tree.item(children[0], "values") == ("dummy",):
                item_path = self.tree.item(item_id, 'values')[0]
                if item_path: self.process_directory(item_id, os.path.join(self.directory, item_path))
            [self._expand_tree_item_recursive(child) for child in self.tree.get_children(item_id)]

    def collapse_all_tree_items(self) -> None: [self._collapse_tree_item_recursive(item) for item in self.tree.get_children()]
    def _collapse_tree_item_recursive(self, item_id: str) -> None:
        [self._collapse_tree_item_recursive(child) for child in self.tree.get_children(item_id)]
        if 'folder' in self.tree.item(item_id, 'tags') or self.tree.get_children(item_id): self.tree.item(item_id, open=False)

def main() -> None:
    parser = argparse.ArgumentParser(description="GUI to select and copy file contents.")
    parser.add_argument("directory", nargs="?", default=".", help="The directory to scan (default: current directory).")
    args = parser.parse_args()
    if not os.path.isdir(args.directory): print(f"Error: Directory '{args.directory}' not found."); sys.exit(1)
    root = tk.Tk(); app = FileCopierApp(root, args.directory); root.mainloop()

if __name__ == "__main__":
    main()