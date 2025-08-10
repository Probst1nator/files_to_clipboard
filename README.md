# README.md
# 🤖 AI Dev Paster: GUI & CLI File Manager

> A powerful GUI and CLI tool to intelligently gather, format, create, and modify file contents for seamless interaction with AI assistants.

This tool is designed to be your primary interface for preparing code contexts for LLMs and applying their suggestions back to your filesystem. It operates in two powerful modes:

1.  **GUI Mode (`cp` or `python main.py`)**: A rich, visual interface for exploring your project, selecting files, and using AI-powered tools to add files or apply changes.
2.  **CLI Mode (`cp -m`)**: A lightning-fast "Smart Paster" that reads your clipboard, intelligently finds relevant files (even creating placeholders for new ones), and copies their formatted content back to your clipboard—all in one command.

## ✨ Features

-   🌳 **Smart File Tree**: A lazy-loaded project explorer that intelligently ignores common clutter (`.git`, `node_modules`, etc.).
-   🤖 **AI Studio Pane**:
    -   **Smart Add**: Paste a prompt or a list of files, and the tool will find and add them to your selection.
    -   **Apply Changes**: Paste a response from an AI (containing file blocks) to **create new files or overwrite existing ones** instantly.
-   ⚡ **CLI "Smart Paster"**: Automatically parse your clipboard for file paths, gather content, and copy it back—perfect for shell workflows.
-   📝 **New File Placeholders**: The CLI mode automatically creates empty, formatted blocks for files mentioned in your prompt that don't exist yet.
-   💾 **Presets & Persistent State**: Save and load complex file selections and exclusion settings per project.
-   👀 **Live Preview & Global Log**: Instantly see a preview of your final clipboard content and a detailed, timestamped log of all actions taken.

## 🚀 Quick Start

**Requirements**:
```bash
pip install pyperclip termcolor
```

### 1. Setup Shell Alias (Recommended)

For the best experience, add this function to your `~/.bashrc` or `~/.zshrc`:

```bash
# Custom function to override cp
# - `cp` (no args): Launches the file copier GUI.
# - `cp -m`: Runs the Smart Paster CLI mode.
# - `cp [any other args]`: Behaves like the normal /bin/cp command.
cp() {
    if [ $# -eq 0 ]; then
        # Launch the GUI for the current directory
        python3 /path/to/your/files_to_clipboard/main.py
    elif [ "$1" == "-m" ]; then
        # Run the script in Smart Paster CLI mode
        python3 /path/to/your/files_to_clipboard/main.py -m
    else
        # Use the real 'cp' command
        /bin/cp "$@"
    fi
}
```
> **Remember to run `source ~/.bashrc` or open a new terminal after adding the function!**

### 2. GUI Mode

Launch the beautiful GUI to visually manage your files.

```bash
# With the alias, just type:
cp

# Without the alias:
python main.py [optional/path/to/project]
```

### 3. CLI "Smart Paster" Mode

The fastest way to get code into your clipboard for an AI prompt.

```bash
# 1. Copy a message with filenames to your clipboard, e.g.:
# "Please review main.py and smart_paster.py and create a new file called tests.py"

# 2. Run the command (with the alias):
cp -m
```

The script will automatically find `main.py` and `smart_paster.py`, create a placeholder for `tests.py`, and copy the combined, formatted content back to your clipboard.

## 💡 How to Use

### GUI Mode

1.  **Select Files**: Double-click files/folders in the tree or use the **Smart Add** box to find files from a text prompt.
2.  **Apply AI Changes**: Paste a response from an AI into the **Apply Changes** box and click the button to write files to your disk. The file tree and global log will update automatically.
3.  **Manage & Reorder**: Drag files in the selection list to reorder them.
4.  **Copy**: Click "Copy to Clipboard" to get the final formatted text.

### Output Example

The script generates clean, markdown-formatted output that's perfect for AI assistants.

````markdown
# smart_paster.py
```python
import os
import re

def find_files_from_request(user_request: str, root_directory: str):
    # ... implementation ...
```

# main.py
```python
import argparse
from main_ui import FileCopierApp

def main() -> None:
    # ... implementation ...
```

# tests.py
```python

```
````

## 🎯 Perfect For

-   **AI-Driven Development**: Quickly providing context to and applying changes from LLMs.
-   **Code Reviews**: Assembling all relevant files for a pull request review.
-   **Technical Documentation**: Grabbing code snippets from multiple files.
-   **Bug Reports**: Packaging a reproducible example with all necessary code.

---

<p align="center">Made with ❤️ for developers who love efficient workflows</p>