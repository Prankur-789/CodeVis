# CodeVis — Technical Documentation

This document is the detailed engineering write-up of CodeVis: what it
does, how every layer works, and why each technology decision was made.
It's written to be read start-to-end by someone who wants to understand
(or extend) the whole system.

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Problem Statement](#2-problem-statement)
3. [Objectives](#3-objectives)
4. [Functional Requirements](#4-functional-requirements)
5. [Non-Functional Requirements](#5-non-functional-requirements)
6. [System Architecture](#6-system-architecture)
7. [Frontend Architecture](#7-frontend-architecture)
8. [Backend Architecture](#8-backend-architecture)
9. [Code Execution Architecture](#9-code-execution-architecture)
10. [Security Model](#10-security-model)
11. [Parser Architecture](#11-parser-architecture)
12. [AST / Program Analysis Per Language](#12-ast--program-analysis-per-language)
13. [Intermediate Representation](#13-intermediate-representation)
14. [Flowchart Generation Algorithm](#14-flowchart-generation-algorithm)
15. [Source-to-Flowchart Mapping](#15-source-to-flowchart-mapping)
16. [API Architecture](#16-api-architecture)
17. [Database Usage](#17-database-usage)
18. [Deployment Architecture](#18-deployment-architecture)
19. [Testing Strategy](#19-testing-strategy)
20. [Performance Considerations](#20-performance-considerations)
21. [Limitations](#21-limitations)
22. [Future Improvements](#22-future-improvements)
23. [Technology Decisions Summary](#23-technology-decisions-summary)
24. [Development Process Notes](#24-development-process-notes)

---

## 1. Project Overview

CodeVis is a full-stack web application that lets a user write Python, C,
or C++ source code in a browser-based editor, execute it against a real
compiler/interpreter inside a sandboxed environment, and see an
interactive flowchart of the program's actual control flow, generated
from a real AST rather than pattern-matching.

## 2. Problem Statement

Reading source code and understanding its *execution shape* are different
skills. Beginners frequently trace through code incorrectly — missing
that an `if` without `else` merges back into the next loop iteration, or
that `continue` skips the rest of a loop body but not the loop itself.
Static text doesn't make these relationships visible; a diagram does.

## 3. Objectives

1. Execute real user code safely, for three languages, with clear success/error reporting.
2. Generate flowcharts from genuine program analysis (never regex/keyword heuristics).
3. Make the flowchart interactive and directly traceable back to source lines.
4. Keep the architecture language-agnostic enough that adding a fourth language is an adapter, not a rewrite.
5. Ship something that actually runs, with automated tests proving it, not a description of a system.

## 4. Functional Requirements

- Language-aware code editor with syntax highlighting, folding, bracket matching.
- Execute Python (interpret), C and C++ (compile then run).
- Display stdout, stderr, compiler diagnostics, execution status, and duration, each attributed to the correct stage (compile vs. run).
- Generate a flowchart with distinct node types: START, END, PROCESS, DECISION, LOOP, INPUT, OUTPUT, FUNCTION, RETURN, BREAK, CONTINUE.
- Support: assignments, if/elif/else, for, while, do-while (C/C++), nested loops/conditions, break, continue, return, print/input (and language equivalents).
- Interactive flowchart: pan, zoom, fit, node inspection, SVG export.
- Bidirectional source-line ↔ flowchart-node highlighting.
- Independent, non-misleading error reporting for execution vs. flowchart generation.
- Built-in sample programs per language.

## 5. Non-Functional Requirements

- **Security**: untrusted code must never run with the privileges of the main server process.
- **Reliability**: every adapter and the sandbox must have automated tests that actually execute, not just parse-and-assert-no-exception.
- **Performance**: typical student-scale programs (tens of lines) analyze and render in well under a second; the API is stateless and horizontally scalable.
- **Portability**: the end user needs nothing but a browser; no local Python/GCC/Node/Graphviz installation.
- **Honesty**: any unsupported construct is flagged explicitly (via a `warnings` array), never silently dropped or faked.

## 6. System Architecture

```
Browser (Monaco editor + custom SVG flowchart renderer, ES modules, no bundler)
        │  fetch() JSON over HTTP
        ▼
Flask API (backend/app.py)
        │
        ├─► Language adapter (backend/adapters/*.py) ──► common IR (backend/ir.py)
        │
        └─► Execution sandbox (backend/execution/*.py) ──► gcc / g++ / python3
```

The two backend paths (parsing and execution) are fully independent — a
request to `/api/analyze` runs both and returns both results, but either
can fail without affecting the other. This directly implements the spec
requirement to never conflate "your code doesn't run" with "the
diagram couldn't be built."

## 7. Frontend Architecture

**No build step, by design.** The frontend is plain HTML + hand-written
CSS + ES modules, served as static files. This was a deliberate
architectural choice, not a fallback:

- It matches the deployment requirement that end users need nothing but a
  browser, and it means *developers* working on this repo need nothing but
  a browser and a static file server either — no `npm install`, no
  bundler config, no build cache to go stale.
- The one external dependency is Monaco Editor, loaded from a CDN via its
  AMD loader (`frontend/js/editor.js`). Building a professional code
  editor from scratch would be reinventing a very large, well-solved
  wheel poorly.
- Everything else — the API client (`api.js`), the flowchart layout engine
  and SVG renderer (`flowchart.js`), and the application wiring
  (`main.js`) — is hand-written with zero runtime dependencies, which also
  means it's the part most worth reading if you want to see this
  project's own code rather than a library's.

### Why not React + React Flow + Tailwind?

These are excellent, industry-standard tools, and are the *first* things
most engineers would reach for. They were deliberately not used here
because:

1. React Flow and Tailwind's full feature set assume a bundler (Vite/
   webpack). Introducing one only to satisfy "use React" would add a
   built artifact this project would then need to build, test, and ship —
   without adding capability the vanilla approach doesn't already have at
   this scale (a few dozen DOM nodes, a few event listeners).
2. Hand-writing the flowchart layout (see [§14](#14-flowchart-generation-algorithm))
   is a better demonstration of understanding graph algorithms than
   configuring a library that does it for you — and it's the load-bearing
   "portfolio" piece of this project.
3. Tailwind's utility classes tend toward a recognizable "generic AI
   dashboard" look, which the product spec for this project explicitly
   asked to avoid in favor of a look that reads as *engineered*.

If this project grows a second, more complex UI surface, migrating to a
bundler + component framework is a contained, mechanical change — the
CSS is already organized as reusable component classes, and the JS is
already split into single-responsibility modules.

## 8. Backend Architecture

**Flask, not FastAPI.** FastAPI/uvicorn were not installable in the
sandboxed development environment this project was actually built and
tested in (no outbound network access beyond already-vendored packages).
Rather than write FastAPI code that had never once been executed — which
would directly violate this project's "never fake it" principle — Flask
was used because it was available, has effectively zero heavy transitive
dependencies, and every single endpoint in `app.py` has been run against
real HTTP-shaped requests via Flask's test client during development (see
`backend/tests/test_api.py`).

The backend has three independent layers with no circular dependencies:

- **`ir.py`** — the common intermediate representation and the shared
  `GraphBuilder` helper. Has zero framework dependencies; could be
  extracted into its own package.
- **`adapters/`** — one file per language, each exposing a single
  `analyze(source: str) -> FlowGraph` function and one exception type.
  Adapters know nothing about Flask, HTTP, or the sandbox.
- **`execution/`** — `sandbox.py` (generic resource-limited subprocess
  runner) and `runners.py` (per-language compile+run recipes). Knows
  nothing about parsing or Flask.
- **`app.py`** — the only layer that imports both of the above and wires
  them to HTTP routes.

This separation is what makes the test suite meaningful: each adapter and
the sandbox are tested in complete isolation from Flask and from each
other, in addition to the end-to-end API tests.

## 9. Code Execution Architecture

Each request to `/api/execute` or `/api/analyze`:

1. Creates a fresh temp directory (`execution/sandbox.py::TempWorkspace`).
2. Writes the user's source to a file in that directory.
3. **Python**: runs `python3 -I -B main.py` (isolated mode: ignores
   `PYTHONPATH`/user site-packages; no `.pyc` writing).
4. **C/C++**: compiles with `gcc -std=c11 -O2 -Wall` / `g++ -std=c++17
   -O2 -Wall`, checks the compiler's exit code and stderr *before*
   attempting to run anything, then runs the produced binary.
5. Every subprocess (compiler or program) runs through the same
   `run_subprocess()` helper, which applies resource limits, a wall-clock
   timeout, and guarantees process-group cleanup (see [§10](#10-security-model)).
6. The temp directory is deleted (`shutil.rmtree`) even if execution
   raised an exception, via a context manager.

Compilation and runtime failures are reported through distinct `status`
values (`compile_error` vs. `runtime_error` vs. `timeout` vs.
`syntax_error` for Python) so the frontend never has to guess which stage
failed.

## 10. Security Model

**Threat model**: the code being run is fully untrusted and potentially
adversarial (infinite loops, fork bombs, memory exhaustion, attempts to
read the filesystem or environment).

**What's implemented** (`backend/execution/sandbox.py`):

- Fresh, isolated temp directory per run; deleted afterward unconditionally.
- Stripped environment (`PATH`, `LANG`, `HOME` only — no secrets, no
  inherited application environment variables).
- `RLIMIT_CPU` — hard CPU-time ceiling (default 5s).
- `RLIMIT_AS` — hard address-space/memory ceiling (default 256MB).
- `RLIMIT_FSIZE` — max file size a process can create (10MB).
- `RLIMIT_NPROC` — max number of processes (default 16), mitigating fork bombs.
- `RLIMIT_NOFILE` — max open file descriptors (64).
- A hard wall-clock timeout (default 8s) independent of CPU-time limits,
  so an I/O-bound or sleeping process can't hang a request indefinitely.
- No listening sockets are opened by executed code, and this backend does
  not run behind any credential the executed process could reach.

**A real bug found and fixed during development.** Initial testing used
`subprocess.run(..., timeout=...)`, which on timeout only signals the
*direct child* process. A test program that called `fork()` in a loop
left orphaned descendants alive — under CPU contention from many
siblings, each one individually reaching its own `RLIMIT_CPU` took far
longer in *wall-clock* time than the configured timeout (an 8-second
timeout took over 80 seconds to actually resolve in one measured run, and
in an earlier, unbounded version of the same test, it consumed enough
host resources to crash the development container outright). The fix:
every sandboxed child calls `os.setsid()` to become its own process-group
leader, and both the timeout path and the normal-completion path call
`os.killpg()` on that entire group. A regression test for this exact
scenario lives in `backend/tests/test_execution_sandbox.py` and
`test_api.py`'s bounded-fork test, and both are green.

**Honest limitation**: `setrlimit` + a scratch directory is *process-level*
isolation, not kernel/VM-level isolation. It is sufficient to stop
runaway resource consumption and guarantee wall-clock containment, but it
does not provide the same guarantee as a container or microVM against a
determined sandbox-escape exploit targeting the compiler or interpreter
itself. For a public, multi-tenant deployment, `backend/docker/
Dockerfile.execution` documents (and provides a working image for) the
upgrade path: run the exact same `execution/runners.py` code inside a
container with `--network none`, a read-only root filesystem, a non-root
user, `--cap-drop ALL`, and cgroup-enforced CPU/memory/pid limits as a
second, independent layer on top of the limits already in place. Wiring
the backend to dispatch into that container (rather than running
`gcc`/`python3` directly on the host) is a contained, mechanical change to
`execution/runners.py` and is listed under [Future
Improvements](#22-future-improvements) rather than shipped without being
tested end-to-end in this environment.

## 11. Parser Architecture

Every language plugs into the same contract: a module exposing
`analyze(source: str) -> FlowGraph` and one exception subclass. This is
what makes the system's extensibility claim concrete rather than
aspirational — `app.py`'s `ADAPTERS` and `ANALYSIS_ERRORS` dicts are the
entire integration surface for a new language.

| Language | Parser | Why |
|---|---|---|
| Python | stdlib `ast` module | Zero dependencies, complete grammar coverage, `ast.unparse` for clean label text |
| C | `pycparser` | A mature, real LALR parser producing a genuine AST — not a hand-rolled subset |
| C++ | Custom tokenizer + recursive-descent parser | libclang (the standard way to get a real C++ AST) was not installable in this environment; see [§12](#12-ast--program-analysis-per-language) |

## 12. AST / Program Analysis Per Language

### Python

Uses `ast.parse()` directly. A single recursive `_Builder` class walks
every statement type the spec requires (`Assign`, `AugAssign`, `If`,
`For`, `While`, `Break`, `Continue`, `Return`, `FunctionDef`, etc.) and
constructs the flowchart via the "dangling edge" technique described in
[§14](#14-flowchart-generation-algorithm). `for`/`while`...`else` is
modeled accurately: the `else` block only executes on normal loop
exhaustion, and `break` edges route around it — matching real CPython
semantics.

### C

`pycparser` cannot resolve `#include <...>` on its own (no bundled fake
libc headers in this deployment, no C preprocessor invoked). Since
flowchart generation only needs control flow, not libc semantics,
preprocessor directive lines are **blanked, not deleted**, before
parsing — same line count, so every AST node's line number still matches
the original source exactly. This is what makes source-to-flowchart line
mapping accurate for C even though the file pycparser actually parses
differs textually from what the user wrote. Verified directly in
`test_c_adapter.py::test_line_numbers_survive_include_stripping`.

### C++

libclang was not installable in this environment (no `clang`/`libclang`
package available, no network access to fetch one). Rather than fake C++
support with regex/keyword matching against the whole language — which
the project spec explicitly warns against — `cpp_adapter.py` implements a
genuine tokenizer (`tokenize()`, a single regex-driven lexer producing a
real token stream with accurate line tracking across comments and
multi-line constructs) and a recursive-descent parser
(`_Parser`) for a **documented control-flow subset**: declarations,
assignments, `cout`/`cin` streams, `if`/`else`, `for`/`while`/`do-while`,
`break`/`continue`/`return`, and arbitrarily nested blocks. Constructs
outside that subset (templates, classes, lambdas, operator overloading,
STL algorithms, exceptions) are preserved as opaque `PROCESS` steps rather
than dropped, and every such gap is surfaced through the graph's
`warnings` array — the same honesty contract used everywhere else in this
project.

This is a real single-pass compiler-front-end technique (tokenize once,
parse directly into the target structure), not a shortcut — the tradeoff
being explicitly scoped grammar coverage instead of the full C++ standard.

## 13. Intermediate Representation

Defined in `backend/ir.py`, with zero dependencies on Flask or any
parser library:

```python
class NodeType(str, Enum):
    START, END, PROCESS, DECISION, LOOP, INPUT, OUTPUT, FUNCTION,
    RETURN, BREAK, CONTINUE

@dataclass
class FlowNode:
    id: str; type: NodeType; label: str
    line_start: int | None; line_end: int | None
    metadata: dict

@dataclass
class FlowEdge:
    id: str; source: str; target: str
    label: str; condition: str | None; metadata: dict
```

`GraphBuilder` (also in `ir.py`) is shared by all three adapters and owns
node/edge ID allocation plus the "dangling edge" bookkeeping described
next — this is the concrete mechanism that makes the IR genuinely
language-independent rather than independent in name only.

## 14. Flowchart Generation Algorithm

All three adapters build their control-flow graph using the same
classic technique: **structured CFG construction via dangling edges**.

- Processing a statement (or block of statements) takes a set of
  *incoming* `(source_node_id, label)` pairs representing not-yet-wired
  control-flow entry points, and returns a set of *outgoing* dangling
  pairs representing where control flow exits that statement/block.
- Sequential statements simply thread this set from one statement to the
  next.
- `if`/`else` fans the incoming set out to a DECISION node, processes each
  branch with that branch's own incoming set, and returns the
  concatenation of both branches' outgoing sets — this is what correctly
  creates the classic "diamond merge" shape, including when one branch is
  missing (`if` without `else` simply passes the "No" edge straight
  through to the merge point).
- Loops push a `LoopContext` (tracking the loop header, for `continue`,
  and an accumulator list for `break` edges), process the body with the
  header as their incoming set, wire the body's outgoing set **back** to
  the header (the "repeat" edge), and return the loop's "exit" edge
  concatenated with every accumulated `break` edge. `for`/`while`'s
  `else` clause (Python) is threaded onto the normal-exit path only —
  `break` edges bypass it, matching real semantics.
- `break`/`continue`/`return` terminate the current dangling chain
  (return an empty outgoing set) and instead register their edge against
  the enclosing loop context or the function/program's END node.

This is the same family of algorithm real compilers use to build CFGs for
optimization passes — applied here for visualization rather than
optimization, but with the same correctness properties (every node has a
well-defined true predecessor/successor set; there are no invented
"guessed" arrows).

### Layout (frontend, `frontend/js/flowchart.js`)

A from-scratch Sugiyama-style layered layout, since no bundler-dependent
graph library (dagre, ELK, React Flow) fits this project's zero-build
frontend architecture (see [§7](#7-frontend-architecture)):

1. **Back-edge classification** via DFS from START — any edge to a node
   still on the recursion stack (i.e., a loop's "repeat" edge) is
   classified as a back edge and excluded from rank computation.
2. **Rank assignment** via longest-path layering over the resulting
   acyclic graph (Kahn's-algorithm-style topological processing).
3. **Dummy node insertion** for any edge spanning more than one rank
   (common when if/else branches have different lengths before merging),
   so multi-rank edges route around real nodes instead of through them.
4. **Crossing reduction** via a median/barycenter heuristic, several
   alternating up/down sweeps.
5. **Coordinate assignment**, then **rendering**: each `NodeType` maps to
   a distinct SVG shape (rounded rect for START/END, diamond for
   DECISION/LOOP, parallelogram for INPUT/OUTPUT, notched pentagon for
   RETURN, double-bar rectangle for FUNCTION) with smooth bezier edges;
   back edges are routed as side-arcing curves, the standard hand-drawn-
   flowchart convention for loop-back arrows.
6. **Pan/zoom** via a transformed `<g>` element and manual wheel/drag
   handlers — no library needed for this either.

This algorithm is unit-tested directly against real backend-generated
graphs (see [§19](#19-testing-strategy)), not just visually eyeballed.

## 15. Source-to-Flowchart Mapping

Every `FlowNode` carries `sourceLineStart`/`sourceLineEnd`, populated from
the real AST/token line numbers in every adapter (see [§12](#12-ast--program-analysis-per-language)
for how this stays accurate even after C's `#include`-stripping
preprocessing step). The frontend uses this two ways:

- **Node → source**: clicking a flowchart node calls
  `editor.highlightLines(start, end)`, which applies a Monaco decoration
  and scrolls the line into view.
- **Source → node**: Monaco's cursor-position callback looks up which
  node's line range contains the current line and highlights that node
  in the SVG.

Both directions are implemented against the same data — there's no
separate "simulated" mapping layer.

## 16. API Architecture

See the [README's API table](../README.md#api) for the endpoint list.
Request/response contracts:

**POST `/api/analyze`**
```jsonc
// Request
{ "language": "python" | "c" | "cpp", "code": "...", "stdin": "" }

// Response
{
  "success": true,
  "language": "python",
  "execution": {
    "success": true, "stdout": "...", "stderr": "",
    "status": "ok" | "compile_error" | "runtime_error" | "syntax_error" | "timeout",
    "executionTime": 0.081, "exitCode": 0, "compilerOutput": ""
  },
  "flowchart": { "nodes": [...], "edges": [...], "warnings": [...] } | null,
  "flowchartError": "..." | null
}
```

`flowchart` and `execution` are always both present and always
independently populated — this is the concrete mechanism behind the
"never conflate execution and flowchart errors" requirement, verified by
`test_api.py::test_analyze_decouples_execution_and_flowchart_errors`.

Input validation (`app.py::_validate_request`) rejects non-JSON bodies,
missing/empty code, unsupported languages, and oversized payloads (20,000
character ceiling) with `400` and a specific error message, before any
adapter or subprocess is invoked.

## 17. Database Usage

None. CodeVis is currently stateless by design — every request carries
everything it needs, and nothing needs to persist between requests. This
keeps the backend trivially horizontally scalable (any instance can serve
any request) and removes an entire class of security surface (no user
data at rest). If session sharing or execution history is added (see
[Future Improvements](#22-future-improvements)), a lightweight store
(SQLite for a single instance, Postgres/Redis for multi-instance) would
be introduced at that point — not before it's actually needed.

## 18. Deployment Architecture

See **[DEPLOYMENT.md](../DEPLOYMENT.md)** for concrete step-by-step
instructions. Summary of the shape:

- **Frontend**: static files (`frontend/`) — deployable to any static
  host (GitHub Pages, Netlify, Vercel, S3+CloudFront, nginx). No build
  step means no build pipeline to configure.
- **Backend**: a WSGI app (`backend/app.py:app`) — deployable behind any
  production WSGI server (gunicorn/waitress), on any platform that allows
  spawning subprocesses (`gcc`, `g++`, `python3`) with the ability to set
  process resource limits. This rules out some serverless platforms that
  restrict `fork()`/`setrlimit` — see DEPLOYMENT.md for specifics on
  which free-tier hosts work and which don't, and why.
- **Execution isolation upgrade**: `backend/docker/Dockerfile.execution`
  for platforms that support container-in-container or a dedicated
  execution worker fleet.

## 19. Testing Strategy

Four independent pytest suites (70 tests total), each targeting one
architectural layer in isolation, plus end-to-end API tests:

- **Adapter tests** (`test_python_adapter.py`, `test_c_adapter.py`,
  `test_cpp_adapter.py`): assert on the actual graph structure produced —
  node type counts, specific edge labels/targets (e.g., "the break node's
  outgoing edge must target END, not the loop header"), line-number
  accuracy, and that malformed input raises the adapter's specific
  exception type rather than crashing generically.
- **Sandbox tests** (`test_execution_sandbox.py`): success paths for all
  three languages, compile-error vs. runtime-error separation, CPU-limit
  enforcement with an actual measured wall-clock bound, and the fork-bomb
  regression test described in [§10](#10-security-model).
- **API tests** (`test_api.py`): every endpoint via Flask's test client,
  input-validation edge cases, and the flowchart-only endpoint's
  requirement to *not* execute code (verified by timing an infinite-loop
  request and asserting it returns in under 2 seconds).
- **Frontend layout verification**: the layout engine
  (`frontend/js/flowchart.js`) was validated with Node.js directly against
  real backend-generated graphs for all six built-in samples, checking for
  node-overlap, valid coordinates, and correct rank ordering (see commit
  history / development notes) — not shipped as a permanent test file
  since it requires cross-language fixture generation, but the technique
  is straightforward to re-run (see `SETUP_GUIDE.md` if you want to
  extend this into a permanent CI check).

Run everything: `cd backend && pytest -v`.

## 20. Performance Considerations

- Adapters run in-process, no subprocess overhead — typical analysis of a
  20–40 line program completes in single-digit milliseconds.
- Execution overhead is dominated by process/compiler startup (tens of
  milliseconds for Python, includes a real `gcc`/`g++` invocation for
  C/C++), not by anything in this project's own code.
- The frontend layout algorithm is O(V·E) per crossing-reduction sweep
  with a small constant number of sweeps (4 down + 4 up) — negligible
  for the node counts realistic flowcharts have (single/low-double
  digits to perhaps a few hundred for pathological input).
- The API is stateless, so horizontal scaling is just running more
  backend instances behind a load balancer — no shared state to
  coordinate.

## 21. Limitations

See the [README's Limitations section](../README.md#limitations-documented-honestly-not-hidden)
for the user-facing summary. In engineering terms:

- C++ coverage is a control-flow subset, not the full standard grammar (see [§12](#12-ast--program-analysis-per-language)).
- Function bodies are not expanded inline into the flowchart (all three adapters represent a call/definition as a single FUNCTION node).
- Execution sandboxing is process-level (see [§10](#10-security-model)); the container-based upgrade is documented but not wired into `execution/runners.py` by default.
- No persistent storage — execution history, shareable links, and accounts are unimplemented (by design; see [§17](#17-database-usage)).

## 22. Future Improvements

Roughly in order of expected value-to-effort:

1. Interprocedural flowcharting — expand called functions into the same graph, using the existing `GraphBuilder` with a call-stack instead of a single `return_target`.
2. Wire `backend/docker/Dockerfile.execution` into `execution/runners.py` as a swappable execution backend, behind a feature flag.
3. Java/JavaScript/Go adapters against the existing `ir.py` contract — no other layer needs to change.
4. A WASM-compiled libclang for full-grammar C++ (would let `cpp_adapter.py` be replaced or complemented without touching the IR or frontend).
5. Execution history + shareable session links (would introduce the first persistent store — see [§17](#17-database-usage)).

## 23. Technology Decisions Summary

| Decision | Alternative considered | Why this choice |
|---|---|---|
| Flask over FastAPI | FastAPI/uvicorn | Not installable in the actual build/test environment; shipping untested framework code contradicts this project's core principle |
| Vanilla JS over React | React + React Flow | No-build-step requirement; hand-written layout is the stronger portfolio signal |
| Hand-written CSS over Tailwind | Tailwind CDN | Avoids the "generic AI dashboard" look the spec explicitly warned against; zero extra dependency |
| pycparser for C | Regex / hand-rolled C parser | A mature real parser was available and installable — no reason to reinvent it |
| Custom parser for C++ | pycparser (doesn't support C++), libclang (not installable here) | Documented subset beats a fake full-language claim |
| Hand-written graph layout | dagre / ELK.js via CDN | These fit a bundler-based app; a from-scratch layered layout matches the zero-build architecture and is a stronger demonstration of algorithmic understanding |
| `resource.setrlimit` + process groups | Docker-only sandboxing | Docker wasn't available in the build/test environment; container upgrade path is documented and provided as a Dockerfile, not silently assumed |
| No database | SQLite/Postgres | Nothing in the current feature set needs persistence; added only when a feature actually requires it |

## 24. Development Process Notes

This project was built and verified in a sandboxed environment with **no
outbound network access** for package installation and **no Docker**
available — which directly shaped several decisions above (Flask over
FastAPI, no npm-based frontend tooling, a documented-but-unwired
container upgrade path rather than a live Docker Compose setup). Every
piece of backend logic described in this document was actually executed
during development: all 70 tests pass against real `gcc`/`g++`/`python3`
invocations, and the fork-bomb security bug in [§10](#10-security-model)
was caught by literally running an adversarial test program against the
sandbox, not by inspection. The frontend layout engine was validated with
Node.js against real backend-generated graphs (see [§19](#19-testing-strategy)).
The one part of the stack not runnable in that sandbox — rendering the
actual browser UI — is exactly why the README's Screenshots section says
so explicitly rather than presenting placeholder images as real ones.
