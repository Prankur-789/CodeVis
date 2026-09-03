import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters.c_adapter import analyze, CAnalysisError
import pytest


def node_types(graph):
    return [n.type.value for n in graph.nodes]


def wrap(body: str) -> str:
    return f"#include <stdio.h>\nint main() {{\n{body}\nreturn 0;\n}}\n"


def test_declaration_and_assignment():
    g = analyze(wrap("int x = 5;\nx = x + 1;"))
    assert node_types(g).count("PROCESS") >= 2


def test_if_else():
    g = analyze(wrap("int x = 1;\nif (x > 0) { x = 1; } else { x = 2; }"))
    decisions = [n for n in g.nodes if n.type.value == "DECISION"]
    assert len(decisions) == 1
    labels = {e.label for e in g.edges if e.source == decisions[0].id}
    assert labels == {"Yes", "No"}


def test_for_loop_and_printf_is_output():
    g = analyze(wrap('for (int i = 0; i < 5; i++) { printf("%d", i); }'))
    assert "LOOP" in node_types(g)
    assert "OUTPUT" in node_types(g)


def test_while_loop():
    g = analyze(wrap("int i = 0;\nwhile (i < 5) { i = i + 1; }"))
    assert "LOOP" in node_types(g)


def test_nested_control_flow():
    body = (
        "for (int i = 0; i < 3; i++) {\n"
        "    if (i == 1) {\n"
        "        for (int j = 0; j < 2; j++) { int y = j; }\n"
        "    }\n"
        "}\n"
    )
    g = analyze(wrap(body))
    assert node_types(g).count("LOOP") == 2
    assert "DECISION" in node_types(g)


def test_break_and_continue():
    body = "for (int i = 0; i < 10; i++) {\n    if (i == 5) { break; }\n    if (i == 2) { continue; }\n}\n"
    g = analyze(wrap(body))
    types = node_types(g)
    assert "BREAK" in types
    assert "CONTINUE" in types


def test_line_numbers_survive_include_stripping():
    src = "#include <stdio.h>\n\nint main() {\n    int x = 5;\n    return 0;\n}\n"
    g = analyze(src)
    decl = next(n for n in g.nodes if n.label == "int x = 5")
    assert decl.line_start == 4  # matches the real line in the original source


def test_compile_error_raises_c_analysis_error():
    with pytest.raises(CAnalysisError):
        analyze(wrap("int x = ;"))


def test_multiple_functions_only_main_expanded_with_warning():
    src = (
        "#include <stdio.h>\n"
        "int helper() { return 1; }\n"
        "int main() { int x = helper(); return 0; }\n"
    )
    g = analyze(src)
    assert any("helper" in w for w in g.warnings)


def test_graph_json_serializable():
    g = analyze(wrap("int x = 1;"))
    json.dumps(g.to_dict())


def test_do_while_loop():
    g = analyze(wrap("int i = 0;\ndo { i = i + 1; } while (i < 5);"))
    assert "LOOP" in node_types(g)
