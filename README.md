
Jarvis LLM — Local Web Interface

This project provides a clean, local web interface for interacting with locally hosted large language models and a small set of productivity features. The layout follows a minimalist design: dark mode support, a responsive sidebar that saves chat logs locally using the browser cache, quick-action buttons positioned above the input bar for formatting tasks (for example, adding calendar events or staging draft emails), smooth scrollbars, soft shadows, and subtle hover animations to create a calm, focused workspace.

Requirements and setup

You will need Python 3.10 or higher and an Ollama instance to host the local models you want to use. From the project root, create and activate a virtual environment, install the required Python packages, then start the server. Example commands for Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install Flask requests ddgs
python jarvis.py
```

After starting the server, open your browser to http://127.0.0.1:5000 to access the interface.

Notes and troubleshooting

- If PowerShell raises a CommandNotFoundException when you try to add a remote, make sure you run the git command in the correct format, for example: `git remote add origin <URL>` — do not paste a bare web link directly into the prompt.
- If you see a RuntimeWarning that `duckduckgo_search` has been renamed, update your source to import `ddgs` instead.
- If Python raises an `Errno 2` (file not found), double-check for typos such as running `jarivs.py` instead of `jarvis.py` and confirm your current directory with `ls` or `dir`.
- If `git push` fails due to authentication, create a GitHub Personal Access Token (PAT) from your developer settings — GitHub no longer accepts account passwords for pushed authentication.
- Any unclosed socket or SSL warnings in logs are usually harmless background hooks between the web interface and your local model. You can clear them by stopping the server with CTRL+C and restarting it.

If you need additional setup help or want me to expand this README with sections like configuration, running with different models, or deployment notes, tell me which sections to add.
