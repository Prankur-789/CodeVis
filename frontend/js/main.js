/**
 * codevis/main.js
 * ---------------
 * Application entry point: wires the Monaco editor, the flowchart renderer,
 * the output panel, and the backend API together, including the
 * source-code <-> flowchart-node bidirectional highlight mapping.
 */

import { api, ApiError } from "./api.js";
import { createEditor } from "./editor.js";
import { computeAndRender, getView } from "./flowchart.js";

const DEFAULT_LANGUAGE = "python";

const state = {
  language: DEFAULT_LANGUAGE,
  editorApi: null,
  currentGraph: null,
  currentNodeEl: null,
  fontSize: 14,
  samplesByLanguage: {},
};

const el = (id) => document.getElementById(id);

const STARTER_CODE = {
  python: '# Write Python code, then click "Run & Analyze"\nprint("Hello, CodeVis!")\n',
  c: '#include <stdio.h>\n\nint main() {\n    printf("Hello, CodeVis!\\n");\n    return 0;\n}\n',
  cpp: '#include <iostream>\nusing namespace std;\n\nint main() {\n    cout << "Hello, CodeVis!" << endl;\n    return 0;\n}\n',
};

async function main() {
  wireToolbar();
  wireOutputPanel();
  wireFlowchartControls();
  wireSamplesModal();

  const container = el("monaco-container");
  state.editorApi = await createEditor(container, {
    language: state.language,
    value: STARTER_CODE[state.language],
    onCursorLine: onCursorLineChanged,
  });

  try {
    const { samples } = await api.samples();
    for (const s of samples) {
      (state.samplesByLanguage[s.language] ||= []).push(s);
    }
  } catch (e) {
    console.warn("Could not load samples from backend:", e);
  }

  el("run-btn").addEventListener("click", runAndAnalyze);
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      runAndAnalyze();
    }
  });
}

// --------------------------------------------------------------------- //
// Toolbar: language select, load/save/reset, font size, fullscreen
// --------------------------------------------------------------------- //

function wireToolbar() {
  el("language-select").addEventListener("change", (e) => {
    state.language = e.target.value;
    state.editorApi.setLanguage(state.language);
    state.editorApi.setValue(STARTER_CODE[state.language]);
    clearFlowchart();
    resetOutput();
  });

  el("reset-btn").addEventListener("click", () => {
    state.editorApi.setValue(STARTER_CODE[state.language]);
  });

  el("save-btn").addEventListener("click", () => {
    const ext = { python: "py", c: "c", cpp: "cpp" }[state.language];
    const blob = new Blob([state.editorApi.getValue()], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `codevis_program.${ext}`;
    a.click();
    URL.revokeObjectURL(a.href);
    showToast("Downloaded source file.");
  });

  el("load-btn").addEventListener("click", () => el("load-file-input").click());
  el("load-file-input").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const text = await file.text();
    state.editorApi.setValue(text);
    e.target.value = "";
    showToast(`Loaded ${file.name}`);
  });

  el("font-decrease-btn").addEventListener("click", () => setFontSize(state.fontSize - 1));
  el("font-increase-btn").addEventListener("click", () => setFontSize(state.fontSize + 1));

  el("fullscreen-btn").addEventListener("click", () => {
    document.querySelector(".pane-editor").classList.toggle("editor-fullscreen-active");
    document.body.classList.toggle("editor-fullscreen-open");
    state.editorApi.layout();
  });
}

function setFontSize(size) {
  state.fontSize = Math.max(10, Math.min(24, size));
  state.editorApi.setFontSize(state.fontSize);
}

// --------------------------------------------------------------------- //
// Samples modal
// --------------------------------------------------------------------- //

function wireSamplesModal() {
  el("samples-btn").addEventListener("click", openSamplesModal);
  el("samples-modal-close").addEventListener("click", closeSamplesModal);
  el("samples-modal-backdrop").addEventListener("click", (e) => {
    if (e.target.id === "samples-modal-backdrop") closeSamplesModal();
  });
}

function openSamplesModal() {
  const body = el("samples-modal-body");
  body.innerHTML = "";
  const langOrder = ["python", "c", "cpp"];
  for (const lang of langOrder) {
    const samples = state.samplesByLanguage[lang] || [];
    for (const s of samples) {
      const item = document.createElement("div");
      item.className = "sample-item";
      item.innerHTML = `
        <div class="sample-item-title">
          <span class="lang-badge ${lang}">${lang.toUpperCase()}</span> ${escapeHtml(s.title)}
        </div>
        <div class="sample-item-desc">${escapeHtml(s.description)}</div>
      `;
      item.addEventListener("click", () => {
        state.language = lang;
        el("language-select").value = lang;
        state.editorApi.setLanguage(lang);
        state.editorApi.setValue(s.code);
        closeSamplesModal();
        clearFlowchart();
        resetOutput();
      });
      body.appendChild(item);
    }
  }
  el("samples-modal-backdrop").style.display = "flex";
}

function closeSamplesModal() {
  el("samples-modal-backdrop").style.display = "none";
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

// --------------------------------------------------------------------- //
// Output panel
// --------------------------------------------------------------------- //

function wireOutputPanel() {
  el("output-header").addEventListener("click", () => {
    el("output-panel").classList.toggle("collapsed");
  });
}

function resetOutput() {
  setStatus("idle", "Idle");
  el("output-body").innerHTML = `<div class="output-empty">Run your program to see output here.</div>`;
  el("output-meta").textContent = "";
}

function setStatus(kind, text) {
  const pill = el("status-pill");
  pill.className = `status-pill ${kind}`;
  pill.innerHTML = `<span class="status-dot ${kind === "running" ? "running" : ""}"></span> ${text}`;
}

function renderOutput(execution) {
  const body = el("output-body");
  body.innerHTML = "";
  const addLine = (text, cls) => {
    if (!text) return;
    const div = document.createElement("div");
    div.className = cls;
    div.textContent = text;
    body.appendChild(div);
  };

  if (execution.status === "compile_error") {
    addLine("\u2717 Compilation failed", "output-line-stderr");
    addLine(execution.stderr, "output-line-compiler");
  } else if (execution.status === "timeout") {
    addLine(`\u26A0 Execution exceeded the time limit and was stopped.`, "output-line-stderr");
  } else if (execution.success) {
    addLine("\u2713 Execution completed successfully", "output-line-info");
    addLine(execution.stdout, "output-line-stdout");
  } else {
    addLine("\u2717 Execution failed", "output-line-stderr");
    addLine(execution.stdout, "output-line-stdout");
    addLine(execution.stderr, "output-line-stderr");
  }
  if (execution.compilerOutput && execution.status !== "compile_error") {
    addLine("Compiler warnings:", "output-line-info");
    addLine(execution.compilerOutput, "output-line-compiler");
  }
  if (!body.children.length) {
    body.innerHTML = `<div class="output-empty">(no output)</div>`;
  }

  const statusMap = {
    ok: ["ok", "Success"],
    compile_error: ["error", "Compile Error"],
    runtime_error: ["error", "Runtime Error"],
    syntax_error: ["error", "Syntax Error"],
    timeout: ["timeout", "Timed Out"],
  };
  const [kind, label] = statusMap[execution.status] || ["error", "Error"];
  setStatus(kind, label);
  el("output-meta").textContent = `${execution.executionTime.toFixed(3)}s`;
}

// --------------------------------------------------------------------- //
// Flowchart panel
// --------------------------------------------------------------------- //

function wireFlowchartControls() {
  el("zoom-in-btn").addEventListener("click", () => getView(el("flowchart-svg-wrap"))?.zoomIn());
  el("zoom-out-btn").addEventListener("click", () => getView(el("flowchart-svg-wrap"))?.zoomOut());
  el("zoom-fit-btn").addEventListener("click", () => getView(el("flowchart-svg-wrap"))?.fit());
  el("zoom-reset-btn").addEventListener("click", () => getView(el("flowchart-svg-wrap"))?.reset());
  el("export-svg-btn").addEventListener("click", exportFlowchartSvg);
  document.addEventListener("click", () => hideInspector());
}

function clearFlowchart() {
  state.currentGraph = null;
  const wrap = el("flowchart-svg-wrap");
  wrap.innerHTML = `
    <div class="flow-empty">
      ${iconFlow()}
      <div>Run your program to generate its flowchart</div>
    </div>`;
  hideInspector();
}

function showFlowLoading() {
  el("flowchart-svg-wrap").innerHTML = `<div class="flow-loading"><div class="spinner"></div><div>Analyzing control flow\u2026</div></div>`;
}

function showFlowError(message) {
  el("flowchart-svg-wrap").innerHTML = `
    <div class="flow-error">
      ${iconWarning()}
      <div><strong>Flowchart could not be generated</strong></div>
      <div class="flow-error-detail">${escapeHtml(message)}</div>
    </div>`;
}

function renderFlowchart(graph) {
  state.currentGraph = graph;
  const wrap = el("flowchart-svg-wrap");
  wrap.innerHTML = "";
  const { onNodeClick } = { onNodeClick: onFlowNodeClick };
  computeAndRender(wrap, graph, { onNodeClick });

  requestAnimationFrame(() => getView(wrap)?.fit());
  renderWarningsBanner(graph.warnings);
}

function renderWarningsBanner(warnings) {
  const existing = document.querySelector(".warnings-banner");
  if (existing) existing.remove();
  if (!warnings || warnings.length === 0) return;
  const banner = document.createElement("div");
  banner.className = "warnings-banner";
  banner.innerHTML = `<strong>\u26A0 ${warnings.length} note${warnings.length > 1 ? "s" : ""} about this flowchart</strong>
    <ul>${warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("")}</ul>`;
  el("flowchart-svg-wrap").appendChild(banner);
}

function onFlowNodeClick(node) {
  if (state.currentNodeEl) state.currentNodeEl.classList.remove("selected");
  const nodeEl = document.querySelector(`.fc-node[data-node-id="${node.id}"]`);
  if (nodeEl) {
    nodeEl.classList.add("selected");
    state.currentNodeEl = nodeEl;
  }
  if (node.sourceLineStart) {
    state.editorApi.highlightLines(node.sourceLineStart, node.sourceLineEnd);
  }
  showInspector(node);
}

function onCursorLineChanged(lineNumber) {
  if (!state.currentGraph) return;
  const match = state.currentGraph.nodes.find(
    (n) => n.sourceLineStart && lineNumber >= n.sourceLineStart && lineNumber <= (n.sourceLineEnd || n.sourceLineStart)
  );
  document.querySelectorAll(".fc-node.selected").forEach((n) => n.classList.remove("selected"));
  if (match) {
    const nodeEl = document.querySelector(`.fc-node[data-node-id="${match.id}"]`);
    nodeEl?.classList.add("selected");
  }
}

function showInspector(node) {
  let inspector = el("inspector");
  if (!inspector) {
    inspector = document.createElement("div");
    inspector.id = "inspector";
    inspector.className = "inspector";
    el("flowchart-svg-wrap").appendChild(inspector);
  }
  inspector.style.display = "block";
  const lineText = node.sourceLineStart
    ? node.sourceLineStart === node.sourceLineEnd
      ? `Line ${node.sourceLineStart}`
      : `Lines ${node.sourceLineStart}\u2013${node.sourceLineEnd}`
    : "No source mapping";
  inspector.innerHTML = `
    <button class="icon-btn inspector-close">\u2715</button>
    <div class="inspector-type" style="background:${typeColor(node.type)}22;color:${typeColor(node.type)}">${node.type}</div>
    <div class="inspector-label">${escapeHtml(node.label)}</div>
    <div class="inspector-lines">${lineText}</div>
  `;
  inspector.querySelector(".inspector-close").addEventListener("click", (e) => {
    e.stopPropagation();
    hideInspector();
  });
  inspector.addEventListener("click", (e) => e.stopPropagation());
}

function hideInspector() {
  const inspector = el("inspector");
  if (inspector) inspector.style.display = "none";
  document.querySelectorAll(".fc-node.selected").forEach((n) => n.classList.remove("selected"));
}

function typeColor(type) {
  const map = {
    START: "#3fb950", END: "#f85149", PROCESS: "#4f8cff", DECISION: "#d29922",
    LOOP: "#bc8cff", INPUT: "#39c5cf", OUTPUT: "#39c5cf", FUNCTION: "#768390",
    RETURN: "#f778ba", BREAK: "#f85149", CONTINUE: "#d29922",
  };
  return map[type] || "#4f8cff";
}

function exportFlowchartSvg() {
  const svg = document.querySelector("#flowchart-svg-wrap svg");
  if (!svg) return showToast("Nothing to export yet \u2014 run your program first.");
  const clone = svg.cloneNode(true);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  const style = document.createElement("style");
  style.textContent = document.querySelector("style#fc-export-style")?.textContent || "";
  const serializer = new XMLSerializer();
  const svgStr = serializer.serializeToString(clone);
  const blob = new Blob([svgStr], { type: "image/svg+xml" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "codevis_flowchart.svg";
  a.click();
  URL.revokeObjectURL(a.href);
}

function iconFlow() {
  return `<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="4" y="3" width="7" height="5" rx="1"/><rect x="13" y="16" width="7" height="5" rx="1"/><path d="M7.5 8v4a2 2 0 0 0 2 2h5a2 2 0 0 1 2 2v0"/></svg>`;
}
function iconWarning() {
  return `<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2 1 21h22z"/><line x1="12" y1="9" x2="12" y2="14"/><circle cx="12" cy="17.5" r="0.6" fill="currentColor"/></svg>`;
}

let toastTimer = null;
function showToast(message) {
  let toast = el("toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 2400);
}

// --------------------------------------------------------------------- //
// Run & Analyze
// --------------------------------------------------------------------- //

async function runAndAnalyze() {
  const code = state.editorApi.getValue();
  if (!code.trim()) return showToast("Write some code first.");

  setStatus("running", "Running\u2026");
  el("output-body").innerHTML = "";
  el("run-btn").disabled = true;
  showFlowLoading();
  state.editorApi.highlightLines(null);

  try {
    const result = await api.analyze(state.language, code, el("stdin-input").value);
    renderOutput(result.execution);
    if (result.flowchart) {
      renderFlowchart(result.flowchart);
    } else {
      showFlowError(result.flowchartError || "Unknown error building the flowchart.");
    }
  } catch (e) {
    const message = e instanceof ApiError ? e.message : "Could not reach the CodeVis backend. Is it running?";
    setStatus("error", "Request Failed");
    el("output-body").innerHTML = `<div class="output-line-stderr">${escapeHtml(message)}</div>`;
    showFlowError(message);
  } finally {
    el("run-btn").disabled = false;
  }
}

main();
