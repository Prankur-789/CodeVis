"""
codevis.app
~~~~~~~~~~~
Flask application exposing CodeVis's API.

Why Flask, not FastAPI: FastAPI/uvicorn were not available to install in the
environment this project was built and tested in (no outbound network
access to PyPI beyond already-vendored packages), and shipping code that
has never actually been run is exactly the kind of "fake it" shortcut this
project explicitly rejects. Flask is in the standard toolbox, has zero
heavy transitive dependencies, and every endpoint below has been executed
end-to-end against real requests during development (see backend/tests/).
Swapping to FastAPI later is a mechanical, contained change -- the adapters,
sandbox, and IR have no framework dependency at all.

Endpoints
---------
GET  /api/health              liveness check
GET  /api/languages           supported languages + their capabilities
GET  /api/samples             built-in example programs
POST /api/analyze             execute code AND build its flowchart
POST /api/execute             execute code only (no flowchart)
POST /api/flowchart           build the flowchart only (no execution)
"""

from __future__ import annotations

import time

from flask import Flask, jsonify, request
from flask.wrappers import Response

from adapters import c_adapter, cpp_adapter, python_adapter
from execution.runners import RUNNERS
from samples import SAMPLES

MAX_CODE_LENGTH = 20_000  # characters; generous for student/interview-scale programs

ADAPTERS = {
    "python": python_adapter,
    "c": c_adapter,
    "cpp": cpp_adapter,
}

ANALYSIS_ERRORS = {
    "python": python_adapter.PythonAnalysisError,
    "c": c_adapter.CAnalysisError,
    "cpp": cpp_adapter.CppAnalysisError,
}

LANGUAGE_INFO = {
    "python": {
        "id": "python",
        "displayName": "Python",
        "monacoId": "python",
        "fileExtension": ".py",
        "parserStrategy": "Python stdlib `ast` module (full statement-level AST)",
        "executionStrategy": "CPython 3, isolated mode (-I)",
    },
    "c": {
        "id": "c",
        "displayName": "C",
        "monacoId": "c",
        "fileExtension": ".c",
        "parserStrategy": "pycparser (real AST; #include lines blanked, not deleted, to preserve line numbers)",
        "executionStrategy": "gcc -std=c11, then run the compiled binary",
    },
    "cpp": {
        "id": "cpp",
        "displayName": "C++",
        "monacoId": "cpp",
        "fileExtension": ".cpp",
        "parserStrategy": "Hand-written tokenizer + recursive-descent parser (documented control-flow subset)",
        "executionStrategy": "g++ -std=c++17, then run the compiled binary",
    },
}


def create_app() -> Flask:
    app = Flask(__name__)

    @app.after_request
    def add_security_headers(resp: Response) -> Response:
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "service": "codevis-backend"})

    @app.route("/api/languages", methods=["GET"])
    def languages():
        return jsonify({"languages": list(LANGUAGE_INFO.values())})

    @app.route("/api/samples", methods=["GET"])
    def samples():
        lang = request.args.get("language")
        if lang:
            return jsonify({"samples": [s for s in SAMPLES if s["language"] == lang]})
        return jsonify({"samples": SAMPLES})

    @app.route("/api/analyze", methods=["POST", "OPTIONS"])
    def analyze():
        if request.method == "OPTIONS":
            return "", 204
        payload, error = _validate_request()
        if error:
            return error
        language, code, stdin_data = payload

        exec_result = RUNNERS[language](code, stdin_data)
        flowchart, flow_error = _build_flowchart(language, code)

        return jsonify(
            {
                "success": exec_result.success,
                "language": language,
                "execution": exec_result.to_dict(),
                "flowchart": flowchart,
                "flowchartError": flow_error,
            }
        )

    @app.route("/api/execute", methods=["POST", "OPTIONS"])
    def execute():
        if request.method == "OPTIONS":
            return "", 204
        payload, error = _validate_request()
        if error:
            return error
        language, code, stdin_data = payload
        result = RUNNERS[language](code, stdin_data)
        return jsonify({"success": result.success, "language": language, "execution": result.to_dict()})

    @app.route("/api/flowchart", methods=["POST", "OPTIONS"])
    def flowchart_only():
        if request.method == "OPTIONS":
            return "", 204
        payload, error = _validate_request(require_code_only=True)
        if error:
            return error
        language, code, _ = payload
        flowchart, flow_error = _build_flowchart(language, code)
        return jsonify({"success": flow_error is None, "language": language, "flowchart": flowchart, "flowchartError": flow_error})

    @app.errorhandler(404)
    def not_found(_e):
        return jsonify({"success": False, "error": "Not found"}), 404

    @app.errorhandler(500)
    def internal_error(_e):
        return jsonify({"success": False, "error": "Internal server error"}), 500

    return app


def _validate_request(require_code_only: bool = False):
    if not request.is_json:
        return None, (jsonify({"success": False, "error": "Request body must be JSON."}), 400)
    data = request.get_json(silent=True) or {}
    language = data.get("language")
    code = data.get("code")
    stdin_data = data.get("stdin", "") or ""

    if language not in ADAPTERS:
        return None, (
            jsonify({"success": False, "error": f"Unsupported language '{language}'. "
                                                  f"Supported: {list(ADAPTERS)}"}),
            400,
        )
    if not isinstance(code, str) or not code.strip():
        return None, (jsonify({"success": False, "error": "`code` must be a non-empty string."}), 400)
    if len(code) > MAX_CODE_LENGTH:
        return None, (
            jsonify({"success": False, "error": f"Code exceeds the {MAX_CODE_LENGTH}-character limit."}),
            400,
        )
    if not isinstance(stdin_data, str):
        return None, (jsonify({"success": False, "error": "`stdin` must be a string."}), 400)

    return (language, code, stdin_data), None


def _build_flowchart(language: str, code: str):
    adapter = ADAPTERS[language]
    error_type = ANALYSIS_ERRORS[language]
    try:
        graph = adapter.analyze(code)
        return graph.to_dict(), None
    except error_type as exc:
        return None, str(exc)
    except Exception as exc:  # pragma: no cover - last-resort safety net
        return None, f"Flowchart generation failed unexpectedly: {exc}"


app = create_app()

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
