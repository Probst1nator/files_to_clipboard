# 📋 File Content Copier

> 🚀 A beautiful GUI tool to quickly copy multiple file contents to your clipboard with syntax highlighting

![Python](https://img.shields.io/badge/python-3.6+-blue.svg) ![License](https://img.shields.io/badge/license-MIT-green.svg)

## ✨ What is this?

Ever needed to share multiple code files in a chat, documentation, or forum post? This tool lets you:
- 🎯 **Select files visually** from a tree view
- 📁 **Add entire folders** with one click
- 👀 **Preview** exactly what will be copied
- 📋 **Copy to clipboard** with proper syntax highlighting
- 💾 **Remember your selection** between sessions

## 🎬 Quick Start

```bash
# Run in current directory
python gui_copy_files.py

# Or specify a directory
python gui_copy_files.py /path/to/your/project
```

## 📸 Features

### 🌳 Smart File Tree
- **Lazy loading** for large projects
- **Ignores** common non-text files (node_modules, __pycache__, etc.)
- **Visual icons** for files 📄 and folders 📁

### 🎯 Flexible Selection
- **Double-click** files to add them
- **Double-click** folders to add all contained files
- **Drag & drop** to reorder your selection
- **Batch operations** with "Add Selected Folder" button

### 👁️ Live Preview
- See exactly what will be copied
- Syntax-highlighted code blocks
- File paths as headers
- Toggle on/off to save screen space

### 📋 Smart Clipboard Format
Output is perfectly formatted for:
- 💬 **AI Chat** (ChatGPT, Claude, etc.)
- 📝 **Markdown** documents
- 📚 **Documentation**
- 💻 **Code reviews**

Example output:
````markdown
# src/main.py
```python
def hello_world():
    print("Hello, World!")
```

# src/utils.py
```python
def format_date(date):
    return date.strftime("%Y-%m-%d")
```
````

### 💾 Persistent State
- Selections are saved automatically
- State file stored next to the script
- Per-project selection memory

## 🛠️ Requirements

```bash
pip install pyperclip
```

> 📝 **Note**: pyperclip is optional but recommended. Without it, you won't be able to copy to clipboard.

## 🎮 Usage Tips

1. **🚀 Quick Add**: Double-click any file or folder to add it instantly
2. **📁 Bulk Add**: Select a folder and click "Add Selected Folder" 
3. **🔄 Reorder**: Drag files in the selection list to reorder them
4. **👀 Preview**: Click "Show Preview" to see what you're about to copy
5. **🗑️ Remove**: Double-click items in the selection list to remove them

## ⚙️ Configuration

The tool automatically ignores:
- 🚫 Binary files
- 📦 Package directories (`node_modules`, `venv`, etc.)
- 🏗️ Build artifacts (`dist`, `build`)
- 🔧 IDE folders (`.idea`, `.vscode`)
- 📝 System files (`.DS_Store`)

## 🤝 Perfect For

- 📤 **Sharing code** with AI assistants
- 📚 **Creating documentation** with code examples  
- 🐛 **Bug reports** with relevant source files
- 👥 **Code reviews** and discussions
- 📖 **Technical blog posts** and tutorials

## 📜 License

MIT License - feel free to use and modify!

---

<p align="center">Made with ❤️ for developers who love clean, organized code sharing</p>
