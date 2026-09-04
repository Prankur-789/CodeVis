# CodeVis

**Write Code. See Logic. Understand Flow.**

An interactive multi-language code execution and visualization platform
that turns Python, C, and C++ source code into real, interactive control-flow
diagrams — backed by genuine parsers and a sandboxed execution engine, not
mocked output.

```
Write code → Run it safely → See real output → See its actual logic, visually
```

---

## Why this exists

Many beginners can read source code line by line but struggle to see the
*shape* of a program's control flow: which branch runs when, how a loop
actually repeats, where a `break` really goes. CodeVis closes that gap by
generating a flowchart directly from a real Abstract Syntax Tree of the
code you wrote and ran — every node traces back to an exact line of your
source.

Useful for: students, programming beginners, interview prep, algorithm
learning, and quickly explaining what a piece of code does.

---

## What's real here (and what isn't)

This project follows one rule throughout: **never fake it**. Concretely:

| Feature | Real implementation |
|---|---|
| Python flowcharts | Built from the standard-library `ast` module (real AST) |
| C flowcharts | Built from `pycparser` (real AST, real LALR parser) |
| C++ flowcharts | A hand-written tokenizer + recursive-descent parser for a documented control-flow subset (no libclang available in the target environment — see [Technical Docs](docs/TECHNICAL_DOCS.md#c-parsing)) |
| Code execution | Real `gcc`/`g++` compilation and real CPython interpretation, sandboxed with actual OS resource limits |
| Errors | Real compiler diagnostics and real interpreter tracebacks, never placeholder text |
| Tests | 70 automated tests across 4 suites, all passing against the actual code (see [Testing](#testing)) |

Where something is genuinely out of scope (e.g., full C++ template support,
multi-function interprocedural flowcharting), it's documented as a
limitation and flagged live in the UI via the `warnings` field — never
silently misrepresented.

---

## Features

- **Professional code editor** — Monaco Editor (VS Code's engine): syntax
  highlighting, bracket matching, code folding, minimap, font-size
  controls, fullscreen mode, load/save/reset, built-in examples.
- **Real sandboxed execution** — CPU time, memory, process-count, and
  wall-clock limits enforced via `resource.setrlimit` + process-group
  kill, with a fresh temp directory and automatic cleanup per run.
- **Interactive flowcharts** — pan, zoom, fit-to-screen, node inspection,
  SVG export — rendered by a from-scratch layered graph layout engine.
- **Bidirectional source mapping** — click a flowchart node to highlight
  its source lines; move your cursor to highlight the matching node.
- **Decoupled error handling** — execution errors and flowchart-generation
  errors are always reported independently, so a parser limitation never
  looks like "your code is broken" and vice versa.
- **Zero build step frontend** — plain HTML/CSS/ES-module JS. No npm
  install required to run it; open a static file server and go.

---

## Screenshots

> This build was produced and tested in an offline development sandbox
> with no browser available to capture real screenshots. Run
> `SETUP_GUIDE.md` locally and the workspace looks like the ASCII layout
> below in practice — replace this section with real screenshots once
> you've run it.

```
┌─────────────────────────────────────────────────────────────────┐
│  CodeVis            [Python ▼]  [▶ Run & Analyze]  Examples ...  │
├──────────────────────────────┬──────────────────────────────────┤
│  1  numbers = [1,2,3,4,5]     │            ( START )             │
│  2  total = 0                 │                │                 │
│  3  for number in numbers:    │        [ numbers = [...] ]       │
│  4      if number % 2 == 0:   │                │                 │
│  5          total += number   │             ◇ i < 5 ◇            │
│  6  print("Sum =", total)     │            ╱      ╲              │
│                                │         Yes        No           │
├────────────────────────────────────────────────────────────────┤
│ ✓ Execution completed successfully        Sum = 6                │
└─────────────────────────────────────────────────────────────────┘
```

**(**Live demo:** [🚀 Try CodeVis Live](https://codevis-frontend.onrender.com/)

---

## Quick start

```bash
git clone https://github.com/<your-username>/codevis.git
cd codevis/backend && pip install -r requirements.txt && python3 app.py
# in a second terminal:
cd codevis/frontend && python3 -m http.server 8080
# open http://localhost:8080/index.html
```

Full walkthrough with troubleshooting: **[SETUP_GUIDE.md](SETUP_GUIDE.md)**.
Publishing this to your own GitHub account: **[GITHUB_GUIDE.md](GITHUB_GUIDE.md)**.

---

## Architecture at a glance

```
                    ┌──────────────────────────┐
                    │   Frontend (no build)    │
                    │  Monaco editor + custom  │
                    │  SVG flowchart renderer  │
                    └────────────┬─────────────┘
                                 │ HTTP / JSON
                    ┌────────────▼─────────────┐
                    │      Flask API layer     │
                    │  /api/analyze, /execute, │
                    │  /flowchart, /samples    │
                    └──────┬─────────────┬─────┘
                           │             │
              ┌────────────▼──┐    ┌─────▼──────────────┐
              │ Language       │    │ Execution sandbox   │
              │ adapters       │    │ (resource limits,    │
              │ → common IR    │    │  temp dirs, timeouts) │
              │ (FlowNode/Edge)│    └──────────────────────┘
              └────────────────┘
                python_adapter.py  (stdlib ast)
                c_adapter.py       (pycparser)
                cpp_adapter.py     (custom recursive-descent parser)
```

Full write-up of every layer, every technology decision and why it was
made, the security threat model, and the parser internals:
**[docs/TECHNICAL_DOCS.md](docs/TECHNICAL_DOCS.md)**.

---

## API

All endpoints return JSON. Full request/response shapes are in the
technical docs; summary:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness check |
| GET | `/api/languages` | Supported languages + parser/execution strategy |
| GET | `/api/samples?language=python` | Built-in example programs |
| POST | `/api/analyze` | Execute code **and** build its flowchart |
| POST | `/api/execute` | Execute code only |
| POST | `/api/flowchart` | Build the flowchart only (no execution) |

Example:
```bash
curl -X POST http://localhost:5001/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"language": "python", "code": "print(1 + 1)"}'
```

---

## Security model (summary)

Untrusted code never runs in the main application process. Each run gets:
CPU-time limit, memory limit (`RLIMIT_AS`), process-count limit, open-file
limit, a fresh temp directory, a stripped environment, and a hard
wall-clock timeout enforced by killing the **entire process group** (not
just the direct child — a real fork-bomb wall-clock-containment bug was
found and fixed during development; see
[docs/TECHNICAL_DOCS.md](docs/TECHNICAL_DOCS.md#security-model)).

This is honest process-level isolation, not kernel/VM-level isolation. A
container-based upgrade path (`backend/docker/Dockerfile.execution`) is
included and documented for multi-tenant production deployments.

---

## Testing

```bash
cd backend
pip install -r requirements-dev.txt
pytest -v
```

70 tests across 4 suites, all passing against real execution:

| Suite | Tests | Covers |
|---|---|---|
| `test_python_adapter.py` | 19 | Every construct in the spec: assign, if/elif/else, for/while(+else), break/continue, return, nesting, functions, source-line mapping |
| `test_c_adapter.py` | 11 | Same coverage via pycparser, plus line-number preservation across `#include` stripping |
| `test_cpp_adapter.py` | 15 | Tokenizer correctness, full control-flow subset, the spec's own prime-number sample end-to-end |
| `test_execution_sandbox.py` | 12 | Success/error/timeout paths, CPU/memory limits, **and a regression test for the fork-bomb wall-clock bug** |
| `test_api.py` | 13 | Every endpoint, error responses, and the execution/flowchart-error decoupling contract |

---

## Limitations (documented honestly, not hidden)

- **C++ parsing** covers a well-defined control-flow subset (declarations,
  assignments, cout/cin, if/else, loops, break/continue/return) rather
  than the full standard grammar — templates, classes, lambdas, and STL
  algorithms are preserved as opaque steps, flagged via `warnings`, not
  silently misrepresented.
- **Function bodies are not expanded** into the flowchart — a called
  function appears as a single step. Full interprocedural flowcharting is
  on the roadmap.
- **Execution sandboxing is process-level**, not container/VM-level. See
  the Security Model section above and the technical docs for the
  production upgrade path.
- No screenshots are embedded in this README (see the Screenshots section)
  because this build was produced in an offline sandbox with no browser.

---

## Future roadmap

- Interprocedural flowcharting (expand called functions, not just show them as steps)
- Java / JavaScript / Go adapters against the existing common IR
- Containerized execution workers for multi-tenant hosting
- Shareable session links, execution history
- WASM-compiled libclang for full-grammar C++ support

---

## License

MIT — see [LICENSE](LICENSE).
