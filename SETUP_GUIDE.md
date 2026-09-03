# CodeVis &mdash; Setup & Run Guide

This guide gets CodeVis running on your own machine from a completely fresh
clone. It assumes basic command-line familiarity but nothing else.

---

## 1. Prerequisites

You need these installed and on your `PATH`:

| Tool | Minimum version | Check with |
|---|---|---|
| Python | 3.10+ | `python3 --version` |
| pip | any recent | `pip3 --version` |
| GCC | any recent | `gcc --version` |
| G++ | any recent | `g++ --version` |
| A modern browser | Chrome/Firefox/Edge/Safari | &mdash; |

You do **not** need Node.js, npm, Docker, or Graphviz to run CodeVis locally
&mdash; the frontend is plain HTML/CSS/JS with no build step, and the only
external asset (Monaco Editor) loads from a CDN in your browser.

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install -y python3 python3-pip gcc g++
```

**macOS:**
```bash
xcode-select --install        # provides gcc/g++ (actually clang, aliased)
brew install python3          # if you don't already have Python 3.10+
```

**Windows:** the sandbox in `backend/execution/sandbox.py` uses the
POSIX-only `resource` module, so the backend must run inside **WSL2**
(Windows Subsystem for Linux), not native Windows Python. Install WSL2 with
Ubuntu, then follow the Linux instructions above *inside* the WSL2 terminal.

---

## 2. Get the code

If you already have the project folder, skip to step 3. Otherwise, clone
your GitHub repo (see `GITHUB_GUIDE.md` if you haven't pushed it yet):

```bash
git clone https://github.com/<your-username>/codevis.git
cd codevis
```

---

## 3. Run the backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows(WSL)/macOS/Linux
pip install -r requirements.txt
```

Copy the environment template (optional &mdash; sensible defaults are built in):

```bash
cp ../.env.example ../.env
```

Start the server:

```bash
python3 app.py
```

You should see:

```
 * Serving Flask app 'app'
 * Running on http://127.0.0.1:5001
```

Leave this terminal running. Verify it's alive in a second terminal:

```bash
curl http://127.0.0.1:5001/api/health
# {"service":"codevis-backend","status":"ok"}
```

### Run the automated tests (recommended)

```bash
cd backend
pip install -r requirements-dev.txt
pytest -v
```

All 70 tests (Python/C/C++ adapters, execution sandbox, API layer) should
pass. If any fail, your `gcc`/`g++`/`python3` versions may differ from the
development environment &mdash; open an issue with the failure output.

---

## 4. Run the frontend

The frontend has zero build step. Any static file server works. From the
project root, in a **new terminal**:

```bash
cd frontend
python3 -m http.server 8080
```

Open **http://localhost:8080/landing.html** for the landing page, or go
straight to **http://localhost:8080/index.html** for the workspace.

> Alternative static servers work identically: `npx serve .`, VS Code's
> "Live Server" extension, `php -S localhost:8080`, nginx, Caddy, etc.
> There's nothing Python-specific about serving these static files.

The frontend talks to the backend at `http://localhost:5001` by default
(see the inline `<script>` at the top of `frontend/index.html`). If you run
the backend on a different port, edit that one line or set
`window.CODEVIS_API_BASE` before `js/main.js` loads.

---

## 5. Try it out

1. Open the workspace (http://localhost:8080/index.html).
2. Click **Examples** and pick "Prime Number Check" (C++) or any other sample.
3. Click **Run & Analyze**.
4. You should see program output at the bottom and an interactive flowchart
   on the right. Click any flowchart node to jump to its source line;
   move your cursor in the editor to see the matching node highlight.

If step 3 shows "Could not reach the CodeVis backend" &mdash; the backend
isn't running, or `CODEVIS_API_BASE` doesn't match its address/port.

---

## 6. Common issues

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'flask'` | venv not activated / deps not installed | Re-run step 3's `pip install -r requirements.txt` inside the activated venv |
| C/C++ code always fails to compile | `gcc`/`g++` not installed or not on PATH | Install per step 1; restart the backend terminal |
| CORS error in browser console | Frontend and backend on different origins with a stricter setup | The bundled Flask app already sends permissive CORS headers (see `app.py`, `add_security_headers`) for local development; tighten this before any public deployment (see `DEPLOYMENT.md`) |
| Flowchart never appears, output works | A real parser limitation was hit | Check the `flowchartError` message shown in the UI &mdash; it's a genuine, specific parser diagnostic, not a placeholder |
| Everything hangs for ~8 seconds then times out | Your program has an infinite loop | Expected behavior &mdash; the sandbox's wall-clock limit (`CODEVIS_WALL_LIMIT`, default 8s) caught it |
| `python3 app.py` fails with a `resource` import error | You're on native Windows, not WSL2 | See the Windows note in step 1 |

---

## 7. Project layout reference

```
codevis/
├── backend/
│   ├── app.py                 # Flask API
│   ├── ir.py                  # Shared intermediate representation
│   ├── samples.py             # Built-in example programs
│   ├── adapters/               # python_adapter.py, c_adapter.py, cpp_adapter.py
│   ├── execution/               # sandbox.py, runners.py
│   ├── tests/                   # pytest suite (70 tests)
│   ├── docker/Dockerfile.execution   # production sandboxing upgrade path
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/
│   ├── index.html              # the workspace
│   ├── landing.html            # marketing/portfolio page
│   ├── css/styles.css
│   └── js/  (api.js, editor.js, flowchart.js, main.js)
├── docs/TECHNICAL_DOCS.md      # full architecture write-up
├── README.md
├── SETUP_GUIDE.md               # this file
├── GITHUB_GUIDE.md
├── DEPLOYMENT.md
├── .env.example
└── LICENSE
```

Next: see `GITHUB_GUIDE.md` to push this project to your own GitHub account.
