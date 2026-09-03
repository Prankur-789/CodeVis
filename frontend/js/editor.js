/**
 * codevis/editor.js
 * -----------------
 * Wraps Monaco Editor (the engine behind VS Code) loaded via its AMD CDN
 * bundle. This is the one external runtime dependency in the whole
 * frontend -- justified because building a professional code editor
 * (syntax highlighting, bracket matching, code folding, keyboard
 * shortcuts) from scratch would be reinventing a very large wheel poorly.
 * Everything else in this app (the flowchart renderer, layout engine, API
 * client) is hand-written with zero dependencies.
 */

const MONACO_CDN = "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.0/min/vs";

let monacoLoadPromise = null;

function loadMonaco() {
  if (monacoLoadPromise) return monacoLoadPromise;
  monacoLoadPromise = new Promise((resolve, reject) => {
    if (window.monaco) return resolve(window.monaco);
    const loaderScript = document.createElement("script");
    loaderScript.src = `${MONACO_CDN}/loader.js`;
    loaderScript.onload = () => {
      window.require.config({ paths: { vs: MONACO_CDN } });
      window.require(["vs/editor/editor.main"], () => resolve(window.monaco));
    };
    loaderScript.onerror = () => reject(new Error("Failed to load Monaco Editor from CDN."));
    document.head.appendChild(loaderScript);
  });
  return monacoLoadPromise;
}

const LANGUAGE_MAP = { python: "python", c: "c", cpp: "cpp" };

export async function createEditor(container, { language, value, onChange, onCursorLine }) {
  const monaco = await loadMonaco();

  monaco.editor.defineTheme("codevis-dark", {
    base: "vs-dark",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": "#0d1117",
      "editor.lineHighlightBackground": "#161b22",
      "editorGutter.background": "#0d1117",
      "editorLineNumber.foreground": "#4b5563",
      "editorLineNumber.activeForeground": "#9aa7b3",
    },
  });

  const editor = monaco.editor.create(container, {
    value,
    language: LANGUAGE_MAP[language] || "plaintext",
    theme: "codevis-dark",
    automaticLayout: true,
    fontSize: 14,
    fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
    minimap: { enabled: true },
    scrollBeyondLastLine: false,
    tabSize: 4,
    renderLineHighlight: "all",
    smoothScrolling: true,
    cursorBlinking: "smooth",
    bracketPairColorization: { enabled: true },
  });

  let decorationIds = [];

  editor.onDidChangeModelContent(() => onChange?.(editor.getValue()));
  editor.onDidChangeCursorPosition((e) => onCursorLine?.(e.position.lineNumber));

  return {
    editor,
    getValue: () => editor.getValue(),
    setValue: (v) => editor.setValue(v),
    setLanguage: (lang) => monaco.editor.setModelLanguage(editor.getModel(), LANGUAGE_MAP[lang] || "plaintext"),
    setFontSize: (size) => editor.updateOptions({ fontSize: size }),
    highlightLines: (startLine, endLine) => {
      if (!startLine) {
        decorationIds = editor.deltaDecorations(decorationIds, []);
        return;
      }
      decorationIds = editor.deltaDecorations(decorationIds, [
        {
          range: new monaco.Range(startLine, 1, endLine || startLine, 1),
          options: { isWholeLine: true, className: "codevis-line-highlight" },
        },
      ]);
      editor.revealLineInCenterIfOutsideViewport(startLine);
    },
    layout: () => editor.layout(),
    focus: () => editor.focus(),
  };
}
