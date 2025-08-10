# 🤖 AI Dev Paster: GUI & CLI File Manager

> A powerful GUI and CLI tool to intelligently gather, format, create, and modify file contents for seamless interaction with AI assistants.

This tool is designed to be your primary interface for preparing code contexts for LLMs and applying their suggestions back to your filesystem. It operates in two powerful modes:

1.  **GUI Mode (`cp` or `python main.py`)**: A rich, visual interface for exploring your project, selecting files, and using AI-powered tools to add files or apply changes.
2.  **CLI Mode (`cp -m`)**: A lightning-fast, literal file getter. It reads a **line-by-line list of file paths** from your clipboard, finds them, and copies their formatted content back.

## ✨ Features

-   🌳 **Smart File Tree**: A lazy-loaded project explorer that intelligently ignores common clutter (`.git`, `node_modules`, etc.).
-   🤖 **AI Studio Pane (GUI Only)**:
    -   **Smart Add**: Paste a natural language prompt (e.g., "get main.py and the css files") to find and add files to your selection.
    -   **Apply Changes**: Paste a response from an AI (containing file blocks) to **create new files or overwrite existing ones** instantly.
-   ⚡ **Predictable CLI with Status**: The `cp -m` command is a simple, fast utility that only reads a list of file paths. It shows you the status of each file:
    -   `(Created)`: The file is new since the last run.
    -   `(Modified)`: The file has changed since the last run.
    -   `(Unmodified)`: The file is unchanged.
-   💾 **Presets & Persistent State**: Save and load complex file selections and exclusion settings per project.
-   👀 **Live Preview & Global Log**: Instantly see a preview of your final clipboard content and a detailed, timestamped log of all actions taken.

## 🚀 Quick Start

**Requirements**:
```bash
pip install pyperclip termcolor