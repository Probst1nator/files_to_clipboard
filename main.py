import os
import sys
import json
import argparse
import re
import signal
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog
from typing import Dict, List, Set, Optional, Tuple, Any
import base64
import hashlib
import threading
import time
import requests
from pathlib import Path
import shutil
import subprocess
import fnmatch

try:
    import pyperclip
except ImportError:
    pyperclip = None

try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False

# For High-DPI display font rendering on Windows
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except (ImportError, AttributeError):
    pass # Not on Windows or old version

# --- Configuration ---
DEFAULT_PRESET_NAME = "default"
CONFIG_FILENAME = ".file_copier_config.json" 
VECTOR_DB_PATH = ".file_copier_vectordb"
OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_EMBEDDING_MODEL = "bge-m3"
IGNORE_DIRS: Set[str] = {"__pycache__", "node_modules", "venv", "dist", "build", ".git", ".idea", ".vscode", VECTOR_DB_PATH}
IGNORE_FILES: Set[str] = {".DS_Store", CONFIG_FILENAME, ".gitignore", ".env"}

# Dark theme colors
DARK_BG = "#2b2b2b"
DARK_FG = "#ffffff"
DARK_SELECT_BG = "#404040"
DARK_SELECT_FG = "#ffffff"
DARK_ENTRY_BG = "#3c3c3c"
DARK_BUTTON_BG = "#404040"
DARK_TREE_BG = "#2b2b2b"

# --- System Spec Helpers ---
def system_has_cuda() -> bool:
    if not shutil.which("nvidia-smi"): return False
    try:
        subprocess.check_output("nvidia-smi", shell=True, stderr=subprocess.STDOUT)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def get_cpu_core_count() -> int:
    return os.cpu_count() or 1

def should_disable_auto_indexing() -> Tuple[bool, str]:
    has_cuda = system_has_cuda()
    cpu_cores = get_cpu_core_count()
    if not has_cuda and cpu_cores < 8:
        return True, (f"System has no CUDA-enabled GPU and fewer than 8 CPU cores ({cpu_cores}).\n\n"
                      "To prevent high background CPU usage, automatic indexing is disabled.")
    return False, ""

# --- Vector Database Manager (unchanged, omitted for brevity) ---
class VectorDatabaseManager:
    def __init__(self, directory: str, db_path: str, embedding_model: str = DEFAULT_EMBEDDING_MODEL):
        self.directory, self.embedding_model, self.db_path = directory, embedding_model, db_path
        self.client, self.collection, self.ollama_available = None, None, False
        if not CHROMADB_AVAILABLE: raise ImportError("ChromaDB missing: pip install chromadb")
        self._initialize_database()
    def _initialize_database(self):
        try:
            os.makedirs(self.db_path, exist_ok=True)
            self.client = chromadb.PersistentClient(path=self.db_path)
            collection_name = f"files_{hashlib.md5(self.directory.encode()).hexdigest()[:8]}"
            try: self.collection = self.client.get_collection(name=collection_name)
            except Exception: self.collection = self.client.create_collection(name=collection_name)
        except Exception as e: raise RuntimeError(f"Failed to init vector DB: {e}")
    def connect_async(self, sc, cc): threading.Thread(target=self._connect_worker, args=(sc, cc), daemon=True).start()
    def _connect_worker(self, status_callback, completion_callback):
        try:
            r = requests.get(f"{OLLAMA_BASE_URL}/api/version", timeout=5)
            if r.status_code == 200:
                self.ollama_available = True
                status_callback(f"Ollama connected. Checking model '{self.embedding_model}'...")
                self._ensure_model_available(status_callback)
                completion_callback(True, f"Vector DB ready with model '{self.embedding_model}'.")
            else: self.ollama_available = False; completion_callback(False, "Ollama is not running.")
        except requests.exceptions.RequestException: self.ollama_available = False; completion_callback(False, f"Could not connect to Ollama.")
        except Exception as e: self.ollama_available = False; completion_callback(False, f"Model error: {e}")
    def _ensure_model_available(self, status_callback):
        try:
            if requests.post(f"{OLLAMA_BASE_URL}/api/embed", json={"model": self.embedding_model, "input": "t"}, timeout=10).status_code == 200:
                status_callback(f"Model '{self.embedding_model}' is available."); return
            status_callback(f"Model '{self.embedding_model}' not found. Pulling...")
            pull_response = requests.post(f"{OLLAMA_BASE_URL}/api/pull", json={"model": self.embedding_model}, stream=True, timeout=300)
            pull_response.raise_for_status()
            for line in pull_response.iter_lines():
                if not line: continue
                data = json.loads(line)
                if 'error' in data: raise RuntimeError(data['error'])
                if 'status' in data:
                    s = data['status']
                    if 'total' in data and 'completed' in data:
                        p = (data['completed'] / data['total']) * 100 if data['total'] > 0 else 0
                        status_callback(f"Downloading model: {p:.1f}%")
                    else: status_callback(f"Status: {s}")
            if requests.post(f"{OLLAMA_BASE_URL}/api/embed", json={"model": self.embedding_model, "input": "t"}, timeout=10).status_code != 200:
                raise RuntimeError("Model pull finished but model is still not available.")
            status_callback(f"Model '{self.embedding_model}' successfully installed.")
        except requests.exceptions.RequestException as e: raise RuntimeError(f"Failed to communicate with Ollama: {e}")
    def generate_embedding(self, text: str) -> Optional[List[float]]:
        if not self.ollama_available: return None
        try:
            r = requests.post(f"{OLLAMA_BASE_URL}/api/embed", json={"model": self.embedding_model, "input": text}, timeout=30)
            if r.status_code == 200: return r.json().get("embeddings", [None])[0]
        except requests.exceptions.RequestException as e: print(f"Embedding error: {e}")
        return None
    def add_file_to_index(self, file_path: str, content: str, metadata: Dict[str, Any]):
        if not self.collection: return False
        try:
            embedding = self.generate_embedding(content)
            if embedding is None: return False
            self.collection.upsert(ids=[hashlib.md5(file_path.encode()).hexdigest()], embeddings=[embedding], documents=[content], metadatas=[metadata])
            return True
        except Exception as e: print(f"Index add error: {e}"); return False
    def get_indexed_files(self) -> Dict[str, float]:
        if not self.collection: return {}
        try:
            results = self.collection.get(include=['metadatas'])
            return {m['file_path']: m.get('indexed_at', 0) for m in results['metadatas'] if m and 'file_path' in m}
        except Exception as e: print(f"Index fetch error: {e}"); return {}
    def get_files_to_index(self, all_files: List[str]) -> Tuple[List[str], List[str]]:
        indexed, to_index, to_remove = self.get_indexed_files(), [], []
        for fp in all_files:
            full_path = os.path.join(self.directory, os.path.normpath(fp))
            try:
                if not os.path.exists(full_path): continue
                if os.path.splitext(fp)[1].lower() in {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}: continue
                mtime = os.path.getmtime(full_path)
                if fp not in indexed or mtime > indexed[fp]: to_index.append(fp)
            except Exception as e: print(f"File check error {fp}: {e}")
        current_set = set(all_files)
        for indexed_fp in indexed.keys():
            if indexed_fp not in current_set and not os.path.exists(os.path.join(self.directory, os.path.normpath(indexed_fp))):
                to_remove.append(indexed_fp)
        return to_index, to_remove
    def remove_file_from_index(self, file_path: str) -> bool:
        if not self.collection: return False
        try: self.collection.delete(ids=[hashlib.md5(file_path.encode()).hexdigest()]); return True
        except Exception as e: print(f"Index remove error: {e}"); return False
    def search_similar_files(self, query: str, n_results: int = 50) -> List[Dict[str, Any]]:
        if not self.collection or not self.ollama_available: return []
        try:
            q_embed = self.generate_embedding(query)
            if q_embed is None: return []
            results = self.collection.query(query_embeddings=[q_embed], n_results=n_results)
            return [{"file_path": m["file_path"], "content": d, "distance": dist, "metadata": m} for m, d, dist in zip(results["metadatas"][0], results["documents"][0], results["distances"][0])] if results.get("ids") else []
        except Exception as e: print(f"Search error: {e}"); return []
    def auto_index_files(self, all_files: List[str], progress_callback=None, completion_callback=None):
        def worker():
            try:
                to_index, to_remove = self.get_files_to_index(all_files)
                to_index.sort(key=lambda p: (p.count(os.path.sep), p.lower()))
                total_ops = len(to_index) + len(to_remove)
                if total_ops == 0:
                    if completion_callback: completion_callback(0, 0, 0, 0)
                    return
                indexed_c, removed_c, op_c = 0, 0, 0
                for fp in to_remove:
                    if self.remove_file_from_index(fp): removed_c += 1
                    op_c += 1;
                    if progress_callback: progress_callback(op_c, total_ops, "removing")
                for fp in to_index:
                    full_path = os.path.join(self.directory, os.path.normpath(fp))
                    try:
                        with open(full_path, 'r', encoding='utf-8', errors='replace') as f: content = f.read()
                        if content.strip():
                            meta = {"file_path": fp, "file_name": os.path.basename(fp), "file_ext": os.path.splitext(fp)[1], "indexed_at": time.time(), "file_size": len(content), "file_mtime": os.path.getmtime(full_path)}
                            if self.add_file_to_index(fp, content, meta): indexed_c += 1
                    except Exception as e: print(f"Indexing error {fp}: {e}")
                    op_c += 1
                    if progress_callback: progress_callback(op_c, total_ops, "indexing")
                if completion_callback: completion_callback(indexed_c, len(to_index), removed_c, len(to_remove))
            except Exception as e:
                print(f"Auto-index worker error: {e}")
                if completion_callback: completion_callback(0, 0, 0, 0)
        threading.Thread(target=worker, daemon=True).start()
    def get_index_stats(self) -> Dict[str, Any]:
        if not self.collection: return {"indexed_files": 0, "ollama_available": False}
        try: return {"indexed_files": self.collection.count(), "ollama_available": self.ollama_available, "embedding_model": self.embedding_model}
        except Exception: return {"indexed_files": 0, "ollama_available": self.ollama_available}


# --- Helper Functions (unchanged) ---
def is_text_file(filepath: str) -> bool:
    try:
        with open(filepath, 'rb') as f: return b'\0' not in f.read(1024)
    except (IOError, PermissionError): return False

def is_includable_file(filepath: str) -> bool:
    if os.path.splitext(filepath)[1].lower() in {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}: return True
    return is_text_file(filepath)

def get_language_hint(filename: str) -> str:
    return os.path.splitext(filename)[1][1:].lower()

def get_script_directory() -> str:
    try: return os.path.dirname(os.path.abspath(__file__))
    except NameError: return os.getcwd()

class FileCopierApp:
    def __init__(self, root: tk.Tk, directory: str):
        # --- UI Initialization (omitted for brevity) ---
        self.root = root
        self.directory = os.path.abspath(directory)
        self.config_file_path = os.path.join(get_script_directory(), CONFIG_FILENAME)
        self.vector_db_path = os.path.join(get_script_directory(), VECTOR_DB_PATH)
        self.root.title(f"File Copier - {os.path.basename(self.directory)}")
        self.root.geometry("1400x900")
        self.root.configure(bg=DARK_BG)
        self.vector_db, self.vector_search_enabled, self.vector_search_mode = None, False, False
        self.search_results, self.indexing_thread, self.is_indexing = [], None, False
        self._initialize_vector_db()
        style = ttk.Style()
        base_font = ("Segoe UI", 10) if sys.platform == "win32" else ("Helvetica", 11)
        style.theme_use('clam')
        style.configure('.', font=base_font, background=DARK_BG, foreground=DARK_FG)
        style.configure("TFrame", background=DARK_BG)
        style.configure("TLabel", background=DARK_BG, foreground=DARK_FG)
        style.configure("TCombobox", fieldbackground=DARK_ENTRY_BG, background=DARK_ENTRY_BG, foreground=DARK_FG, bordercolor=DARK_SELECT_BG, insertcolor=DARK_FG, arrowcolor=DARK_FG)
        style.map('TCombobox', fieldbackground=[('readonly', DARK_ENTRY_BG)])
        style.configure("TEntry", fieldbackground=DARK_ENTRY_BG, background=DARK_ENTRY_BG, foreground=DARK_FG, bordercolor=DARK_SELECT_BG, insertcolor=DARK_FG)
        style.map("TEntry", bordercolor=[('focus', '#0078d4')])
        style.configure("TButton", background=DARK_BUTTON_BG, foreground=DARK_FG, bordercolor=DARK_SELECT_BG, focuscolor='none', padding=5)
        style.map("TButton", background=[('active', DARK_SELECT_BG)])
        style.configure("Treeview", background=DARK_TREE_BG, foreground=DARK_FG, fieldbackground=DARK_TREE_BG, bordercolor=DARK_SELECT_BG, rowheight=25)
        style.map("Treeview", background=[('selected', DARK_SELECT_BG)])
        style.configure("Vertical.TScrollbar", background=DARK_BG, troughcolor=DARK_ENTRY_BG)
        style.configure("Horizontal.TScrollbar", background=DARK_BG, troughcolor=DARK_ENTRY_BG)
        style.configure("TPanedwindow", background=DARK_BG)
        style.configure("TCheckbutton", background=DARK_BG, foreground=DARK_FG, focuscolor='none')
        style.map("TCheckbutton", background=[('active', DARK_BG)])
        self.selected_files_map: Dict[str, bool] = {}
        self.preview_visible = False
        self.all_text_files: List[str] = []
        self._search_job: Optional[str] = None
        self._auto_save_job: Optional[str] = None
        self.full_config: Dict[str, Dict] = {}
        self.project_data: Dict[str, any] = {}
        self.presets: Dict[str, Dict] = {}
        self.main_container = ttk.Frame(root, padding=10)
        self.main_container.pack(fill=tk.BOTH, expand=True)
        self.main_pane = ttk.PanedWindow(self.main_container, orient=tk.HORIZONTAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True)
        self.tree_frame = ttk.Frame(self.main_pane, padding=(0,0,5,0))
        self.search_frame = ttk.Frame(self.tree_frame)
        self.search_frame.pack(fill=tk.X, pady=(0, 5))
        self.search_label = ttk.Label(self.search_frame, text="Filter:")
        self.search_label.pack(side=tk.LEFT, padx=(0,5))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(self.search_frame, textvariable=self.search_var)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3, padx=(0, 5))
        self.search_var.trace_add("write", self._debounce_search)
        self.search_entry.bind("<Return>", self._on_search_enter)
        self.vector_toggle_var = tk.BooleanVar()
        self.vector_toggle = ttk.Checkbutton(self.search_frame, text="Vector", variable=self.vector_toggle_var, command=self._on_vector_toggle)
        self.vector_toggle.pack(side=tk.RIGHT, padx=(5, 0))
        self.vector_controls_frame = ttk.Frame(self.tree_frame)
        self.vector_status_var = tk.StringVar()
        self.vector_status_label = ttk.Label(self.vector_controls_frame, textvariable=self.vector_status_var, foreground="#aaaaaa", font=("Segoe UI", 9))
        self.vector_status_label.pack(fill=tk.X, pady=(0, 5))
        self.exclusion_main_frame = ttk.Frame(self.tree_frame)
        self.exclusion_main_frame.pack(fill=tk.X, pady=(0, 10))
        self.advanced_exclude_var = tk.BooleanVar(value=False)
        self.advanced_exclude_toggle = ttk.Checkbutton(self.exclusion_main_frame, text="Advanced Exclusions (Regex)", variable=self.advanced_exclude_var, command=self._toggle_exclude_mode)
        self.advanced_exclude_toggle.pack(anchor='w')
        self.simple_exclude_frame = ttk.Frame(self.exclusion_main_frame)
        ttk.Label(self.simple_exclude_frame, text="Exclude Dirs:").grid(row=0, column=0, sticky='w', pady=(5,0))
        self.exclude_dirs_var = tk.StringVar(value="venv .git .idea .vscode __pycache__ node_modules dist build")
        self.exclude_dirs_entry = ttk.Entry(self.simple_exclude_frame, textvariable=self.exclude_dirs_var)
        self.exclude_dirs_entry.grid(row=0, column=1, sticky='ew', pady=(5,0), padx=(5,0))
        ttk.Label(self.simple_exclude_frame, text="Exclude Files:").grid(row=1, column=0, sticky='w', pady=(2,0))
        self.exclude_patterns_var = tk.StringVar(value="*.log *.json *.csv *.env .DS_Store .gitignore")
        self.exclude_patterns_entry = ttk.Entry(self.simple_exclude_frame, textvariable=self.exclude_patterns_var)
        self.exclude_patterns_entry.grid(row=1, column=1, sticky='ew', pady=(2,0), padx=(5,0))
        self.simple_exclude_frame.grid_columnconfigure(1, weight=1)
        self.advanced_exclude_frame = ttk.Frame(self.exclusion_main_frame)
        ttk.Label(self.advanced_exclude_frame, text="Exclude (regex):").pack(side=tk.LEFT, padx=(0,5), pady=(5,0))
        self.exclusion_var = tk.StringVar(value=r"venv/|\.git/|\.idea/|\.vscode/|__pycache__|/node_modules/|/build/|/dist/|.*\.log$|.*\.json$|.*\.csv$|.*\.env$")
        self.exclusion_entry = ttk.Entry(self.advanced_exclude_frame, textvariable=self.exclusion_var)
        self.exclusion_entry.pack(fill=tk.X, expand=True, ipady=3, pady=(5,0))
        self.exclude_dirs_var.trace_add("write", self._debounce_search)
        self.exclude_patterns_var.trace_add("write", self._debounce_search)
        self.exclusion_var.trace_add("write", self._debounce_search)
        self._toggle_exclude_mode()
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
        ttk.Label(self.selection_frame, text="Selected Files (Drag to Reorder)", font=("Segoe UI", 10, "bold")).pack(pady=(0, 5), anchor='w')
        self.listbox_frame = ttk.Frame(self.selection_frame)
        self.listbox_frame.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(self.listbox_frame, selectmode=tk.SINGLE, borderwidth=0, relief="flat", bg=DARK_TREE_BG, fg=DARK_FG, selectbackground=DARK_SELECT_BG, selectforeground=DARK_SELECT_FG, font=("Segoe UI", 10), highlightthickness=0)
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
        self.preview_frame = ttk.Frame(self.main_container)
        preview_header_frame = ttk.Frame(self.preview_frame)
        preview_header_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(preview_header_frame, text="Preview", font=(base_font[0], base_font[1], "bold")).pack(side=tk.LEFT, anchor='w')
        self.preview_stats_var = tk.StringVar(value="")
        ttk.Label(preview_header_frame, textvariable=self.preview_stats_var, foreground="#aaaaaa").pack(side=tk.RIGHT, anchor='e')
        self.preview_text = scrolledtext.ScrolledText(self.preview_frame, height=10, wrap=tk.WORD, bg=DARK_ENTRY_BG, fg=DARK_FG, insertbackground=DARK_FG, selectbackground=DARK_SELECT_BG, selectforeground=DARK_SELECT_FG, font=("Consolas", 10) if sys.platform == "win32" else ("Monaco", 10), borderwidth=0, highlightthickness=1, highlightcolor=DARK_SELECT_BG)
        self.preview_text.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        # Bindings & Population
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
        self._bind_select_all(self.exclude_dirs_entry)
        self._bind_select_all(self.exclude_patterns_entry)
        self._bind_select_all(self.preview_text)
        self.drag_start_index: Optional[int] = None
        self._setup_interrupt_handler()

        self.load_project_config()
        self._scan_and_cache_all_files()
        self.load_preset_into_ui()
        self._update_vector_status()
        
        if self.vector_db:
            self.root.after(500, self._start_background_vector_tasks)

    # --- START OF MODIFIED/NEW METHODS ---

    def _get_color_for_similarity(self, similarity: float) -> str:
        """
        Calculates a color in a smooth red-yellow-green gradient.
        - 0.0 = Red (#ff0000)
        - 0.5 = Yellow (#ffff00)
        - 1.0 = Green (#00ff00)
        """
        # Clamp the value to the valid range [0.0, 1.0]
        similarity = max(0.0, min(1.0, similarity))

        # Define the key color points
        red_color = (255, 0, 0)
        yellow_color = (255, 255, 0)
        green_color = (0, 255, 0)

        if similarity < 0.5:
            # Interpolate between Red and Yellow
            # `local_pos` will be a value from 0.0 to 1.0 representing the position within this segment
            local_pos = similarity * 2.0
            start_color = red_color
            end_color = yellow_color
        else:
            # Interpolate between Yellow and Green
            # `local_pos` will be a value from 0.0 to 1.0 representing the position within this segment
            local_pos = (similarity - 0.5) * 2.0
            start_color = yellow_color
            end_color = green_color
        
        # Linear interpolation: R = R1 * (1 - t) + R2 * t
        r = int(start_color[0] * (1 - local_pos) + end_color[0] * local_pos)
        g = int(start_color[1] * (1 - local_pos) + end_color[1] * local_pos)
        b = int(start_color[2] * (1 - local_pos) + end_color[2] * local_pos)

        return f"#{r:02x}{g:02x}{b:02x}"

    def _display_search_results(self, results: List[Dict[str, Any]]):
        """Display search results with color-coded similarity."""
        for item in self.tree.get_children(): self.tree.delete(item)
        if not results:
            self.tree.insert("", "end", text="No similar files found", tags=('info',))
            self.tree.tag_configure('info', foreground='#888888'); return
        
        nodes, configured_tags = {"": ""}, set()

        for result in results:
            file_path = result["file_path"]
            distance = result.get("distance", 2.0)
            similarity = 1.0 - (distance / 2.0)

            parent_path, path_parts = "", file_path.split(os.path.sep)
            for i, part in enumerate(path_parts[:-1]):
                current_path = os.path.join(*path_parts[:i+1])
                if current_path not in nodes:
                    nodes[current_path] = self.tree.insert(nodes.get(parent_path, ""), 'end', text=f"📁 {part}", values=[current_path], tags=('folder',), open=True)
                parent_path = current_path
            
            hex_color = self._get_color_for_similarity(similarity)
            color_tag = f"sim_{hex_color[1:]}"
            if color_tag not in configured_tags:
                self.tree.tag_configure(color_tag, foreground=hex_color)
                configured_tags.add(color_tag)

            display_text = f"📄 {path_parts[-1]} (sim: {similarity:.3f})"
            self.tree.insert(nodes.get(parent_path, ""), 'end', text=display_text, values=[file_path], tags=(color_tag,))
        
        self.tree.tag_configure('folder', foreground='#DDA0DD')

    def on_tree_double_click(self, event: tk.Event) -> None:
        """Adds a file to the selection list on double-click."""
        item_id = self.tree.identify_row(event.y)
        if not item_id: return
        item = self.tree.item(item_id)
        tags = item.get('tags', [])
        
        is_file = 'file' in tags or (tags and tags[0].startswith('sim_'))
        
        if is_file:
            file_path = item['values'][0]
            if file_path not in self.selected_files_map:
                self.listbox.insert(tk.END, file_path)
                self.selected_files_map[file_path] = True
                self.update_selected_count()
                self.update_preview()
                self._debounce_auto_save()
        elif 'folder' in tags:
            self.tree.selection_set(item_id)
            self.add_selected_folder()
            
    def repopulate_tree(self, files_to_display: Optional[List[str]] = None):
        """FIXED: Always clears the tree before repopulating to prevent stale UI elements."""
        # This is the critical fix for the stale folder bug.
        for item in self.tree.get_children():
            self.tree.delete(item)

        if files_to_display is None:
            # Re-enable lazy loading for the default view
            self.tree.bind('<<TreeviewOpen>>', self.on_tree_expand)
            self.process_directory("", self.directory)
            return

        # Disable lazy loading for filtered/search views
        self.tree.unbind('<<TreeviewOpen>>')
        
        if not files_to_display:
            self.tree.insert("", "end", text="No matching files found.", tags=('info',))
            self.tree.tag_configure('info', foreground='#888888')
            return

        nodes = {"": ""}
        for file_path in files_to_display:
            parent_path, path_parts = "", file_path.split(os.path.sep)
            for i, part in enumerate(path_parts[:-1]):
                current_path = os.path.join(*path_parts[:i+1])
                if current_path not in nodes:
                    parent_node_id = nodes.get(parent_path, "")
                    dir_id = self.tree.insert(parent_node_id, 'end', text=f"📁 {part}", values=[current_path], tags=('folder',), open=True)
                    nodes[current_path] = dir_id
                parent_path = current_path
            self.tree.insert(nodes.get(parent_path, ""), 'end', text=f"📄 {path_parts[-1]}", values=[file_path], tags=('file',))
        
        self.tree.tag_configure('file', foreground='#87CEEB')
        self.tree.tag_configure('folder', foreground='#DDA0DD')

    def collapse_all_tree_items(self) -> None:
        """FIXED: Correctly iterates over top-level items to prevent the crash."""
        for item in self.tree.get_children():
            self.tree.item(item, open=False)

    # --- Other Methods (unchanged, using stubs for brevity) ---
    def _toggle_exclude_mode(self):
        if self.advanced_exclude_var.get(): self.simple_exclude_frame.pack_forget(); self.advanced_exclude_frame.pack(fill=tk.X, expand=True)
        else: self.advanced_exclude_frame.pack_forget(); self.simple_exclude_frame.pack(fill=tk.X, expand=True)
        self._debounce_search()
    def auto_save_current_preset(self):
        name = self.preset_var.get()
        if not name: return
        data = {"selected_files": list(self.listbox.get(0, tk.END)), "filter_text": self.search_var.get(), "advanced_exclude_mode": self.advanced_exclude_var.get(), "exclude_dirs": self.exclude_dirs_var.get(), "exclude_patterns": self.exclude_patterns_var.get(), "exclusion_regex": self.exclusion_var.get()}
        if self.presets.get(name) != data: self.presets[name] = data; self.save_config()
    def load_preset_into_ui(self):
        name = self.preset_var.get()
        if not name or name not in self.presets: return
        self.status_var.set(f"Loading preset '{name}'..."); self.root.update_idletasks()
        data = self.presets[name]
        self.search_var.set(data.get("filter_text", ""))
        is_adv = data.get("advanced_exclude_mode", "exclusion_regex" in data and "exclude_dirs" not in data)
        self.advanced_exclude_var.set(is_adv)
        self.exclude_dirs_var.set(data.get("exclude_dirs", "venv .git .idea .vscode __pycache__ node_modules dist build"))
        self.exclude_patterns_var.set(data.get("exclude_patterns", "*.log *.json *.csv *.env .DS_Store .gitignore"))
        self.exclusion_var.set(data.get("exclusion_regex", r"venv/|\.git/"))
        self._toggle_exclude_mode()
        self._perform_filter(from_preset_load=True)
        self.clear_all(auto_save=False)
        added = 0
        for fp in data.get("selected_files", []):
            if os.path.exists(os.path.join(self.directory, os.path.normpath(fp))) and fp not in self.selected_files_map:
                self.listbox.insert(tk.END, fp); self.selected_files_map[fp] = True; added += 1
        self.update_selected_count(); self.update_preview(); self.status_var.set(f"Loaded preset '{name}'. ({added}/{len(data.get('selected_files', []))} files).")
    def _get_exclusion_regex(self) -> Optional[re.Pattern]:
        if self.advanced_exclude_var.get():
            p_str = self.exclusion_var.get()
            if not p_str: return None
            try: return re.compile(p_str, re.IGNORECASE)
            except re.error as e: self.status_var.set(f"Regex Error: {e}"); return None
        else:
            dirs = self.exclude_dirs_var.get().split()
            files = self.exclude_patterns_var.get().split()
            parts = []
            if dirs: parts.append(r"(^|/|\\)(" + "|".join(re.escape(d) for d in dirs) + r")(/|\\)")
            if files: parts.append("|".join(fnmatch.translate(p) for p in files))
            if not parts: return None
            try: return re.compile("|".join(f"({p})" for p in parts), re.IGNORECASE)
            except re.error as e: self.status_var.set(f"Internal Regex Error: {e}"); return None
    def _scan_and_cache_all_files(self):
        self.status_var.set("Scanning project files..."); self.root.update_idletasks()
        self.all_text_files = []
        regex = self._get_exclusion_regex()
        for root, dirs, files in os.walk(self.directory, topdown=True):
            dirs[:] = [d for d in dirs if not (regex and regex.search(os.path.join(os.path.relpath(root, self.directory), d).replace(os.path.sep, '/') + '/'))]
            for filename in files:
                rp = os.path.relpath(os.path.join(root, filename), self.directory)
                if regex and regex.search(rp.replace(os.path.sep, '/')): continue
                if is_includable_file(os.path.join(root, filename)): self.all_text_files.append(rp)
        self.all_text_files.sort(key=str.lower)
        self.status_var.set(f"Ready. Found {len(self.all_text_files)} includable files.")
    def _perform_filter(self, from_preset_load: bool = False):
        search_term = self.search_var.get().lower()
        current_exclusion_state = (self.advanced_exclude_var.get(), self.exclude_dirs_var.get(), self.exclude_patterns_var.get(), self.exclusion_var.get())
        if not hasattr(self, '_last_exclusion_state') or self._last_exclusion_state != current_exclusion_state:
            self._last_exclusion_state = current_exclusion_state
            self._scan_and_cache_all_files()
        
        # Determine the final list of files to show
        if search_term:
            files_to_show = [f for f in self.all_text_files if search_term in os.path.basename(f).lower()]
            self.repopulate_tree(files_to_show)
        else:
            # If search is empty, go back to lazy-loading view
            self.repopulate_tree(None)
        
        if not from_preset_load: self._debounce_auto_save()
    def on_closing(self): self.auto_save_current_preset(); self.root.destroy()
    def _start_background_vector_tasks(self):
        if not self.vector_db: return
        sc = lambda m: self.root.after(0, lambda: self.status_var.set(m))
        cc = lambda s, m: self.root.after(0, lambda: [self.status_var.set(m), self._update_vector_status(), self._on_vector_db_ready(s)])
        self.vector_db.connect_async(sc, cc)
    def _on_vector_db_ready(self, success: bool):
        if not success: self.vector_search_enabled = False; self._update_vector_status(); return
        self.vector_search_enabled = True; self._update_vector_status()
        disable, reason = should_disable_auto_indexing()
        if disable: self.status_var.set("⚠️ Auto-indexing disabled."); messagebox.showwarning("Auto-Indexing Disabled", reason, parent=self.root); return
        self.root.after(1000, lambda: self._start_continuous_indexing(initial_run=True))
    def _initialize_vector_db(self):
        try: self.vector_db = VectorDatabaseManager(self.directory, self.vector_db_path)
        except Exception as e: self.vector_search_enabled = False; self.vector_db = None; print(f"Vector search disabled: {e}")
    def _on_vector_toggle(self):
        self.vector_search_mode = self.vector_toggle_var.get()
        self.search_label.configure(text="Search:" if self.vector_search_mode else "Filter:")
        if self.vector_search_mode:
            if not self.vector_db: messagebox.showerror("Vector Search", "Vector DB not initialized."); self.vector_toggle_var.set(False); self.vector_search_mode = False; return
            self.vector_controls_frame.pack(fill=tk.X, pady=(0, 10), after=self.search_frame)
            if not self.vector_db.ollama_available: self.status_var.set("Connecting to Ollama...")
        else: self.vector_controls_frame.pack_forget()
        self._update_vector_status(); self._perform_filter_or_search()
    def _start_continuous_indexing(self, initial_run: bool = False):
        if not self.vector_search_enabled or not (initial_run or self.vector_search_mode) or self.is_indexing:
            if not self.is_indexing: self.root.after(30000, self._start_continuous_indexing)
            return
        self.is_indexing = True; self._scan_and_cache_all_files()
        pc = lambda c, t, p: self.root.after(0, lambda: self.status_var.set(f"Updating index: {c}/{t}"))
        def cc(ic, tic, rc, trc):
            self.is_indexing = False; status = "✅ Index up to date"
            ops = [f"indexed {ic}" if ic > 0 else None, f"removed {rc}" if rc > 0 else None]
            if any(ops): status = f"✅ Index updated: {', '.join(filter(None, ops))}."
            self.root.after(0, lambda: [self.status_var.set(status), self._update_vector_status(), self.root.after(30000, self._start_continuous_indexing)])
        self.vector_db.auto_index_files(self.all_text_files, pc, cc)
    def _on_search_enter(self, event):
        if self.vector_search_mode: self._perform_vector_search()
    def _update_vector_status(self):
        if not self.vector_db: self.vector_status_var.set("Vector DB not initialized."); return
        if not self.vector_db.ollama_available: self.vector_status_var.set(f"Ollama not connected. Model: {self.vector_db.embedding_model}"); return
        stats = self.vector_db.get_index_stats()
        status_text = f"Indexing... ({stats.get('indexed_files', 0)} files)" if self.is_indexing else f"Index ready: {stats.get('indexed_files', 0)} files"
        self.vector_status_var.set(f"{status_text} with {stats.get('embedding_model', 'N/A')}")
    def _perform_vector_search(self):
        if not self.vector_search_enabled or not self.vector_search_mode: return
        query = self.search_var.get().strip()
        if not query:
            for item in self.tree.get_children(): self.tree.delete(item)
            self.tree.insert("", "end", text="Enter a search query above", tags=('info',)); self.tree.tag_configure('info', foreground='#888888'); return
        self.status_var.set("Performing semantic search...")
        def sw():
            results = self.vector_db.search_similar_files(query, n_results=100)
            self.root.after(0, lambda: [self._display_search_results(results), self.status_var.set(f"Found {len(results)} semantically similar files")])
        threading.Thread(target=sw, daemon=True).start()
    def _debounce_search(self, *args):
        if self._search_job: self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(300, self._perform_filter_or_search)
    def _perform_filter_or_search(self):
        if self.vector_search_mode: self._perform_vector_search()
        else: self._perform_filter()
    def load_project_config(self):
        try:
            if os.path.exists(self.config_file_path):
                with open(self.config_file_path, 'r', encoding='utf-8') as f: self.full_config = json.load(f)
        except (json.JSONDecodeError, IOError): self.full_config = {}
        if self.directory not in self.full_config: self.full_config[self.directory] = {"presets": {DEFAULT_PRESET_NAME: {}}, "last_active_preset": DEFAULT_PRESET_NAME}
        self.project_data = self.full_config[self.directory]; self.presets = self.project_data['presets']
        if DEFAULT_PRESET_NAME not in self.presets: self.presets[DEFAULT_PRESET_NAME] = {}
        self.update_preset_combobox(); last_active = self.project_data.get("last_active_preset", DEFAULT_PRESET_NAME)
        self.preset_var.set(last_active if last_active in self.presets else DEFAULT_PRESET_NAME)
    def save_config(self, quiet: bool = True):
        self.project_data['last_active_preset'] = self.preset_var.get()
        try:
            with open(self.config_file_path, 'w', encoding='utf-8') as f: json.dump(self.full_config, f, indent=4)
            if not quiet: self.status_var.set(f"Preset '{self.preset_var.get()}' saved.")
        except IOError as e: messagebox.showerror("Config Error", f"Could not save config: {e}")
    def _debounce_auto_save(self, *args):
        if self._auto_save_job: self.root.after_cancel(self._auto_save_job)
        self._auto_save_job = self.root.after(1500, self.auto_save_current_preset)
    def update_preset_combobox(self):
        names = sorted([p for p in self.presets.keys() if p != DEFAULT_PRESET_NAME], key=str.lower)
        names.insert(0, DEFAULT_PRESET_NAME); self.preset_combobox['values'] = names
    def save_current_as_preset(self):
        name = simpledialog.askstring("Save New Preset", "Enter a name:", parent=self.root)
        if not name or not name.strip(): return
        name = name.strip()
        if name in self.presets and not messagebox.askyesno("Confirm Overwrite", f"Preset '{name}' exists. Overwrite?", parent=self.root): return
        self.auto_save_current_preset() # Save current state to active preset first
        self.presets[name] = self.presets[self.preset_var.get()] # Copy data to new name
        self.update_preset_combobox(); self.preset_var.set(name); self.save_config(quiet=False)
    def on_preset_selected(self, event=None): self.load_preset_into_ui(); self._debounce_auto_save()
    def remove_selected_preset(self):
        name = self.preset_var.get()
        if name == DEFAULT_PRESET_NAME: messagebox.showerror("Action Denied", "Default preset cannot be removed."); return
        if messagebox.askyesno("Confirm Deletion", f"Delete preset '{name}'?", parent=self.root):
            if name in self.presets: del self.presets[name]; self.update_preset_combobox(); self.preset_var.set(DEFAULT_PRESET_NAME); self.load_preset_into_ui(); self.save_config(quiet=True)
    def _bind_select_all(self, w: tk.Widget):
        def sa(e=None):
            if isinstance(w, (ttk.Entry, tk.Entry)): w.select_range(0, 'end')
            elif isinstance(w, (scrolledtext.ScrolledText, tk.Text)): w.tag_add('sel', '1.0', 'end')
            return "break"
        w.bind("<Control-a>", sa); w.bind("<Command-a>", sa)
    def _setup_interrupt_handler(self):
        self.interrupted = False; h = signal.getsignal(signal.SIGINT)
        def hi(s, f): self.interrupted = True; h(s, f)
        try: signal.signal(signal.SIGINT, hi)
        except (ValueError, TypeError): pass
        self.root.after(250, self._check_for_interrupt)
    def _check_for_interrupt(self):
        if self.interrupted: self.on_closing()
        else: self.root.after(250, self._check_for_interrupt)
    def process_directory(self, parent_id: str, path: str) -> None:
        for cid in self.tree.get_children(parent_id):
            if self.tree.item(cid, "values") == ("dummy",): self.tree.delete(cid)
        try: items = sorted(os.listdir(path), key=str.lower)
        except (OSError, PermissionError): return
        regex = self._get_exclusion_regex()
        for name in items:
            fp = os.path.join(path, name)
            rp = os.path.relpath(fp, self.directory)
            if regex and regex.search(rp.replace(os.path.sep, '/')): continue
            if os.path.isdir(fp): did = self.tree.insert(parent_id, 'end', text=f"📁 {name}", values=[rp], tags=('folder',)); self.tree.insert(did, 'end', text='...', values=['dummy'])
            elif is_includable_file(fp): self.tree.insert(parent_id, 'end', text=f"📄 {name}", values=[rp], tags=('file',))
        self.tree.tag_configure('file', foreground='#87CEEB'); self.tree.tag_configure('folder', foreground='#DDA0DD')
    def on_tree_expand(self, event: tk.Event) -> None:
        item_id = self.tree.focus(); children = self.tree.get_children(item_id)
        if children and self.tree.item(children[0], "values") == ("dummy",):
            self.process_directory(item_id, os.path.join(self.directory, self.tree.item(item_id, "values")[0]))
    def get_all_files_in_folder(self, path: str) -> List[str]: return [f for f in self.all_text_files if f.replace(os.path.sep, '/').startswith(path.replace(os.path.sep, '/') + '/')]
    def add_selected_folder(self) -> None:
        if not self.tree.selection(): return
        item = self.tree.item(self.tree.selection()[0])
        if 'folder' not in item['tags']: return
        path, files, count = item['values'][0], self.get_all_files_in_folder(item['values'][0]), 0
        for fp in files:
            if fp not in self.selected_files_map: self.listbox.insert(tk.END, fp); self.selected_files_map[fp] = True; count += 1
        self.update_selected_count(); self.update_preview(); self._debounce_auto_save(); self.status_var.set(f"Added {count} file(s) from {os.path.basename(path)}")
    def remove_selected(self) -> None:
        if self.listbox.curselection():
            idx = self.listbox.curselection()[0]; fp = self.listbox.get(idx); self.listbox.delete(idx)
            if fp in self.selected_files_map: del self.selected_files_map[fp]
            self.update_selected_count(); self.update_preview(); self._debounce_auto_save()
    def clear_all(self, auto_save: bool = True) -> None:
        self.listbox.delete(0, tk.END); self.selected_files_map.clear(); self.update_selected_count(); self.update_preview()
        if auto_save: self._debounce_auto_save()
    def update_selected_count(self) -> None: c = self.listbox.size(); self.selected_count_var.set(f"{c} file{'s' if c != 1 else ''} selected")
    def toggle_preview(self) -> None:
        self.preview_visible = not self.preview_visible
        if self.preview_visible: self.preview_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, pady=(10, 0), in_=self.main_container); self.update_preview()
        else: self.preview_frame.pack_forget()
        self.btn_toggle_preview.configure(text="Hide Preview" if self.preview_visible else "Show Preview")
    def update_preview(self) -> None:
        if not self.preview_visible: return
        self.preview_text.delete(1.0, tk.END)
        if not self.listbox.get(0, tk.END): self.preview_text.insert(1.0, "No files selected."); self.preview_stats_var.set("L: 0 | C: 0"); return
        out = self.generate_clipboard_content(max_preview_size=200000)
        self.preview_stats_var.set(f"L: {len(out.splitlines()):,} | C: {len(out):,}"); self.preview_text.insert(1.0, out); self.preview_text.see(1.0)
    def generate_clipboard_content(self, max_preview_size: Optional[int] = None) -> str:
        parts, size = [], 0
        for i, rp in enumerate(self.listbox.get(0, tk.END)):
            if max_preview_size and size > max_preview_size: parts.append(f"\n... and {self.listbox.size() - i} more ..."); break
            try:
                fp = os.path.join(self.directory, os.path.normpath(rp))
                if os.path.splitext(rp)[1].lower() == '.png':
                    with open(fp, 'rb') as f: b64 = base64.b64encode(f.read()).decode('ascii')
                    block = f"# {rp.replace(os.path.sep, '/')} (base64 PNG)\n```base64\n{b64}\n```"
                else:
                    with open(fp, 'r', encoding='utf-8', errors='replace') as f: content = f.read()
                    block = f"# {rp.replace(os.path.sep, '/')}\n```{get_language_hint(rp)}\n{content}\n```"
                parts.append(block);
                if max_preview_size: size += len(block)
            except Exception as e: parts.append(f"# ERROR: Could not read {rp}\n```{e}\n```")
        return "\n\n".join(parts)
    def copy_to_clipboard(self) -> None:
        if pyperclip is None: messagebox.showerror("Error", "Install pyperclip: pip install pyperclip"); return
        if not self.listbox.get(0, tk.END): self.status_var.set("No files selected."); return
        self.status_var.set("Processing..."); self.root.update_idletasks()
        out = self.generate_clipboard_content(); pyperclip.copy(out)
        size_kb = len(out) / 1024
        self.status_var.set(f"✅ Copied {self.listbox.size()} file(s) to clipboard! ({size_kb:.1f} KB)")
    def on_drag_start(self, event: tk.Event) -> None: self.drag_start_index = event.widget.nearest(event.y)
    def on_drag_motion(self, event: tk.Event) -> None:
        if self.drag_start_index is not None:
            ci = event.widget.nearest(event.y)
            if ci != self.drag_start_index:
                item = self.listbox.get(self.drag_start_index); self.listbox.delete(self.drag_start_index); self.listbox.insert(ci, item)
                self.drag_start_index = ci; self.update_preview(); self._debounce_auto_save()
    def expand_all_tree_items(self) -> None: [self._expand_tree_item_recursive(item) for item in self.tree.get_children()]
    def _expand_tree_item_recursive(self, item_id: str) -> None:
        if self.tree.get_children(item_id):
            self.tree.item(item_id, open=True)
            if self.tree.item(self.tree.get_children(item_id)[0], "values") == ("dummy",): self.process_directory(item_id, os.path.join(self.directory, self.tree.item(item_id, 'values')[0]))
            [self._expand_tree_item_recursive(child) for child in self.tree.get_children(item_id)]

def main() -> None:
    parser = argparse.ArgumentParser(description="GUI to select and copy file contents with vector search capabilities.")
    parser.add_argument("directory", nargs="?", default=".", help="The directory to scan (default: current directory).")
    args = parser.parse_args()
    if not os.path.isdir(args.directory): print(f"Error: Directory '{args.directory}' not found."); sys.exit(1)
    root = tk.Tk(); app = FileCopierApp(root, args.directory); root.mainloop()

if __name__ == "__main__":
    main()