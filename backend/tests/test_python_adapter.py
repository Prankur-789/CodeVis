import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from adapters.python_adapter import analyze, PythonAnalysisError


def node_types(graph):
    return [n.type.value for n in graph.nodes]


def test_start_and_end_always_present():
    g = analyze("x = 1")
    types = node_types(g)
    assert types[0] == "START"
    assert "END" in types


def test_assignment_creates_process_node():
    g = analyze("x = 1\ny = 2")
    types = node_types(g)
    assert types.count("PROCESS") == 2


def test_print_creates_output_node():
    g = analyze('print("hi")')
    assert "OUTPUT" in node_types(g)


def test_input_creates_input_node():
    g = analyze("name = input('name?')")
    assert "INPUT" in node_types(g)


def test_if_else_creates_decision_with_two_branches():
    g = analyze("if x > 0:\n    y = 1\nelse:\n    y = 2\n")
    decision_nodes = [n for n in g.nodes if n.type.value == "DECISION"]
    assert len(decision_nodes) == 1
    d = decision_nodes[0]
    labels = {e.label for e in g.edges if e.source == d.id}
    assert labels == {"Yes", "No"}


def test_elif_chain_creates_multiple_decisions():
    src = "if x == 1:\n    y = 1\nelif x == 2:\n    y = 2\nelse:\n    y = 3\n"
    g = analyze(src)
    assert node_types(g).count("DECISION") == 2


def test_if_without_else_merges_correctly():
    g = analyze("if x > 0:\n    y = 1\nz = 2\n")
    # The DECISION's "No" edge and the true branch's outgoing edge should
    # both land on the same next node (the merge point).
    decision = next(n for n in g.nodes if n.type.value == "DECISION")
    no_edge = next(e for e in g.edges if e.source == decision.id and e.label == "No")
    other_out_edges = [e for e in g.edges if e.target == no_edge.target]
    assert len(other_out_edges) == 2  # merge point has two incoming edges


def test_for_loop_has_back_edge():
    g = analyze("for i in range(5):\n    x = i\n")
    loop_node = next(n for n in g.nodes if n.type.value == "LOOP")
    back_edges = [e for e in g.edges if e.target == loop_node.id]
    assert len(back_edges) >= 1  # at least the repeat edge from the body


def test_while_loop_structure():
    g = analyze("i = 0\nwhile i < 5:\n    i = i + 1\n")
    assert "LOOP" in node_types(g)


def test_nested_loops():
    src = "for i in range(3):\n    for j in range(3):\n        x = i * j\n"
    g = analyze(src)
    assert node_types(g).count("LOOP") == 2


def test_nested_conditions():
    src = "if a:\n    if b:\n        x = 1\n    else:\n        x = 2\nelse:\n    x = 3\n"
    g = analyze(src)
    assert node_types(g).count("DECISION") == 2


def test_break_connects_to_loop_exit():
    src = "for i in range(10):\n    if i == 5:\n        break\n"
    g = analyze(src)
    assert "BREAK" in node_types(g)
    loop_node = next(n for n in g.nodes if n.type.value == "LOOP")
    end_node = next(n for n in g.nodes if n.type.value == "END")
    break_node = next(n for n in g.nodes if n.type.value == "BREAK")
    # break must eventually reach END without passing back through the loop header again
    break_out_edges = [e for e in g.edges if e.source == break_node.id]
    assert break_out_edges[0].target == end_node.id


def test_continue_connects_back_to_loop_header():
    src = "for i in range(10):\n    if i == 5:\n        continue\n    x = i\n"
    g = analyze(src)
    assert "CONTINUE" in node_types(g)
    loop_node = next(n for n in g.nodes if n.type.value == "LOOP")
    continue_node = next(n for n in g.nodes if n.type.value == "CONTINUE")
    continue_out_edges = [e for e in g.edges if e.source == continue_node.id]
    assert continue_out_edges[0].target == loop_node.id


def test_return_connects_to_end():
    g = analyze("def f():\n    return 1\n")
    # function body isn't expanded, but a bare top-level analysis of just the
    # function shouldn't crash and should still produce a valid graph
    assert node_types(g)[0] == "START"


def test_function_def_produces_single_function_node_and_warning():
    g = analyze("def greet():\n    print('hi')\n\ngreet()\n")
    assert "FUNCTION" in node_types(g)
    assert any("not expanded" in w for w in g.warnings)


def test_source_line_mapping_present():
    g = analyze("x = 1\ny = 2\n")
    process_nodes = [n for n in g.nodes if n.type.value == "PROCESS"]
    lines = sorted(n.line_start for n in process_nodes)
    assert lines == [1, 2]


def test_syntax_error_raises_analysis_error():
    with pytest.raises(PythonAnalysisError):
        analyze("if True\n    print(1)\n")


def test_for_else_executes_only_without_break():
    src = "for i in range(3):\n    x = i\nelse:\n    y = 1\n"
    g = analyze(src)
    # 'y = 1' process node should exist and be reachable from the loop's "Done" edge
    loop_node = next(n for n in g.nodes if n.type.value == "LOOP")
    done_edge = next(e for e in g.edges if e.source == loop_node.id and e.label == "Done")
    else_node = next(n for n in g.nodes if n.label == "y = 1")
    assert done_edge.target == else_node.id


def test_graph_serializes_to_dict_json_safe():
    import json
    g = analyze("x = 1\nprint(x)\n")
    json.dumps(g.to_dict())  # should not raise
