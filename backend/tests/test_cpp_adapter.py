import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters.cpp_adapter import analyze, tokenize


def node_types(graph):
    return [n.type.value for n in graph.nodes]


def wrap(body: str) -> str:
    return f"#include <iostream>\nusing namespace std;\nint main() {{\n{body}\nreturn 0;\n}}\n"


def test_tokenizer_handles_stream_operators():
    toks = tokenize('cout << "hi" << endl;')
    values = [t.value for t in toks if t.kind != "eof"]
    assert values == ["cout", "<<", '"hi"', "<<", "endl", ";"]


def test_tokenizer_preserves_line_numbers_across_comments():
    src = "int x = 1; // comment\nint y = 2;"
    toks = [t for t in tokenize(src) if t.kind != "eof"]
    y_tok = next(t for t in toks if t.value == "y")
    assert y_tok.line == 2


def test_declaration_and_assignment():
    g = analyze(wrap("int x = 5;\nx = x + 1;"))
    assert node_types(g).count("PROCESS") >= 2


def test_cout_is_output_node():
    g = analyze(wrap('cout << "hello";'))
    assert "OUTPUT" in node_types(g)


def test_cin_is_input_node():
    g = analyze(wrap("int x;\ncin >> x;"))
    assert "INPUT" in node_types(g)


def test_if_else_branches():
    g = analyze(wrap("int x = 1;\nif (x > 0) { x = 1; } else { x = 2; }"))
    decisions = [n for n in g.nodes if n.type.value == "DECISION"]
    assert len(decisions) == 1
    labels = {e.label for e in g.edges if e.source == decisions[0].id}
    assert labels == {"Yes", "No"}


def test_for_loop_with_nested_if():
    body = (
        "int count = 0;\n"
        "for (int i = 1; i <= 17; i++) {\n"
        "    if (17 % i == 0) { count++; }\n"
        "}\n"
    )
    g = analyze(wrap(body))
    assert "LOOP" in node_types(g)
    assert "DECISION" in node_types(g)


def test_while_loop():
    g = analyze(wrap("int i = 0;\nwhile (i < 5) { i++; }"))
    assert "LOOP" in node_types(g)


def test_do_while_loop():
    g = analyze(wrap("int i = 0;\ndo { i++; } while (i < 5);"))
    assert "LOOP" in node_types(g)


def test_break_and_continue():
    body = "for (int i = 0; i < 10; i++) {\n    if (i == 5) { break; }\n    if (i == 2) { continue; }\n}\n"
    g = analyze(wrap(body))
    types = node_types(g)
    assert "BREAK" in types
    assert "CONTINUE" in types


def test_nested_loops():
    body = "for (int i = 0; i < 3; i++) {\n    for (int j = 0; j < 3; j++) { int y = i * j; }\n}\n"
    g = analyze(wrap(body))
    assert node_types(g).count("LOOP") == 2


def test_line_numbers_match_source():
    src = "#include <iostream>\nusing namespace std;\n\nint main() {\n    int x = 5;\n    return 0;\n}\n"
    g = analyze(src)
    decl = next(n for n in g.nodes if n.label == "int x = 5")
    assert decl.line_start == 5


def test_unsupported_function_flagged_not_expanded():
    src = (
        "#include <iostream>\nusing namespace std;\n"
        "int helper() { return 1; }\n"
        "int main() { int x = helper(); return 0; }\n"
    )
    g = analyze(src)
    assert any("helper" in w for w in g.warnings)


def test_graph_json_serializable():
    g = analyze(wrap("int x = 1;"))
    json.dumps(g.to_dict())


def test_the_spec_prime_sample_end_to_end():
    src = (
        "#include <iostream>\nusing namespace std;\n\n"
        "int main() {\n"
        "    int number = 17;\n"
        "    int count = 0;\n\n"
        "    for (int i = 1; i <= number; i++) {\n"
        "        if (number % i == 0) {\n"
        "            count++;\n"
        "        }\n"
        "    }\n\n"
        "    if (count == 2) {\n"
        '        cout << "Prime Number" << endl;\n'
        "    } else {\n"
        '        cout << "Not a Prime Number" << endl;\n'
        "    }\n\n"
        "    return 0;\n}\n"
    )
    g = analyze(src)
    assert node_types(g).count("LOOP") == 1
    assert node_types(g).count("DECISION") == 2
    assert node_types(g).count("OUTPUT") == 2
    assert g.warnings == []
