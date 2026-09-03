"""
codevis.adapters.python_adapter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Builds a FlowGraph from real Python source using the standard-library `ast`
module (no regex, no keyword guessing). This is a classic structured
control-flow-graph construction: each statement list is processed against a
set of "incoming dangling edges", and returns the set of dangling edges that
exit the block, which the caller wires to whatever comes next.

Supported: assignments (incl. augmented/annotated), print()/input() as
OUTPUT/INPUT, if/elif/else, for, while, for/while-else, break, continue,
return, nested blocks of arbitrary depth, top-level function definitions
(represented as a single FUNCTION node -- their bodies are not expanded;
see the "Limitations" section of the technical docs).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Optional

from ir import FlowGraph, GraphBuilder, NodeType, truncate_label

Dangling = list[tuple[str, str]]  # (source_node_id, label)


@dataclass
class LoopContext:
    header_id: str          # node to jump to on `continue`
    break_out: Dangling      # accumulates dangling edges produced by `break`


class PythonAnalysisError(Exception):
    pass


def analyze(source: str) -> FlowGraph:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise PythonAnalysisError(f"SyntaxError: {exc.msg} (line {exc.lineno})") from exc

    gb = GraphBuilder()
    start_id = gb.add_node(NodeType.START, "START", line_start=1)
    end_id = gb.add_node(NodeType.END, "END")

    loop_stack: list[LoopContext] = []
    builder = _Builder(gb, loop_stack, end_id)

    incoming: Dangling = [(start_id, "")]
    outgoing = builder.process_block(tree.body, incoming)
    gb.connect(outgoing, end_id)

    return gb.build()


class _Builder:
    def __init__(self, gb: GraphBuilder, loop_stack: list[LoopContext], return_target: str):
        self.gb = gb
        self.loop_stack = loop_stack
        self.return_target = return_target

    # ------------------------------------------------------------------ #
    def process_block(self, stmts: list[ast.stmt], incoming: Dangling) -> Dangling:
        current = incoming
        for stmt in stmts:
            current = self.process_stmt(stmt, current)
            if not current:
                # Everything after an unconditional break/continue/return in
                # the same block is unreachable; stop wiring further nodes
                # into a dead end (still visually rendered, just orphaned).
                remaining = stmts[stmts.index(stmt) + 1 :]
                if remaining:
                    self.gb.warn(
                        "Unreachable code detected after break/continue/return "
                        f"on line {getattr(stmt, 'lineno', '?')}."
                    )
                break
        return current

    # ------------------------------------------------------------------ #
    def process_stmt(self, stmt: ast.stmt, incoming: Dangling) -> Dangling:
        handler = getattr(self, f"_h_{type(stmt).__name__}", None)
        if handler:
            return handler(stmt, incoming)
        # Unsupported construct: represent generically so flow keeps working.
        self.gb.warn(f"'{type(stmt).__name__}' is not fully modeled; shown as a generic step.")
        label = truncate_label(self._safe_unparse(stmt))
        node_id = self.gb.add_node(NodeType.PROCESS, label, stmt.lineno, self._end_line(stmt))
        self.gb.connect(incoming, node_id)
        return [(node_id, "")]

    # ---- simple statements ------------------------------------------- #
    def _h_Assign(self, stmt: ast.Assign, incoming: Dangling) -> Dangling:
        if self._is_input_call(stmt.value):
            return self._make_io_node(stmt, incoming, NodeType.INPUT)
        label = truncate_label(self._safe_unparse(stmt))
        node_id = self.gb.add_node(NodeType.PROCESS, label, stmt.lineno, self._end_line(stmt))
        self.gb.connect(incoming, node_id)
        return [(node_id, "")]

    _h_AugAssign = _h_Assign
    _h_AnnAssign = _h_Assign

    def _h_Expr(self, stmt: ast.Expr, incoming: Dangling) -> Dangling:
        call = stmt.value
        if isinstance(call, ast.Call) and self._call_name(call) == "print":
            return self._make_io_node(stmt, incoming, NodeType.OUTPUT)
        if isinstance(call, ast.Call) and self._is_input_call(call):
            return self._make_io_node(stmt, incoming, NodeType.INPUT)
        label = truncate_label(self._safe_unparse(stmt))
        node_id = self.gb.add_node(NodeType.PROCESS, label, stmt.lineno, self._end_line(stmt))
        self.gb.connect(incoming, node_id)
        return [(node_id, "")]

    def _h_Pass(self, stmt: ast.Pass, incoming: Dangling) -> Dangling:
        return incoming  # no-op: pass control straight through

    def _h_Import(self, stmt: ast.stmt, incoming: Dangling) -> Dangling:
        node_id = self.gb.add_node(NodeType.PROCESS, truncate_label(self._safe_unparse(stmt)), stmt.lineno)
        self.gb.connect(incoming, node_id)
        return [(node_id, "")]

    _h_ImportFrom = _h_Import

    # ---- branching ----------------------------------------------------- #
    def _h_If(self, stmt: ast.If, incoming: Dangling) -> Dangling:
        cond_label = truncate_label(self._safe_unparse(stmt.test))
        node_id = self.gb.add_node(NodeType.DECISION, cond_label, stmt.lineno, stmt.lineno)
        self.gb.connect(incoming, node_id)

        true_out = self.process_block(stmt.body, [(node_id, "Yes")])
        if stmt.orelse:
            false_out = self.process_block(stmt.orelse, [(node_id, "No")])
        else:
            false_out = [(node_id, "No")]
        return true_out + false_out

    # ---- loops ----------------------------------------------------------- #
    def _h_While(self, stmt: ast.While, incoming: Dangling) -> Dangling:
        cond_label = truncate_label(self._safe_unparse(stmt.test))
        header_id = self.gb.add_node(NodeType.LOOP, cond_label, stmt.lineno, stmt.lineno)
        self.gb.connect(incoming, header_id)
        return self._process_loop_body(header_id, stmt.body, stmt.orelse, true_label="Yes", false_label="No")

    def _h_For(self, stmt: ast.For, incoming: Dangling) -> Dangling:
        target = self._safe_unparse(stmt.target)
        it = self._safe_unparse(stmt.iter)
        label = truncate_label(f"for {target} in {it}")
        header_id = self.gb.add_node(NodeType.LOOP, label, stmt.lineno, stmt.lineno)
        self.gb.connect(incoming, header_id)
        return self._process_loop_body(header_id, stmt.body, stmt.orelse, true_label="Next", false_label="Done")

    def _process_loop_body(
        self,
        header_id: str,
        body: list[ast.stmt],
        orelse: list[ast.stmt],
        true_label: str,
        false_label: str,
    ) -> Dangling:
        ctx = LoopContext(header_id=header_id, break_out=[])
        self.loop_stack.append(ctx)
        body_out = self.process_block(body, [(header_id, true_label)])
        self.gb.connect(body_out, header_id, default_label="repeat")
        self.loop_stack.pop()

        normal_exit: Dangling = [(header_id, false_label)]
        if orelse:
            normal_exit = self.process_block(orelse, normal_exit)
        return normal_exit + ctx.break_out

    # ---- jumps ----------------------------------------------------------- #
    def _h_Break(self, stmt: ast.Break, incoming: Dangling) -> Dangling:
        node_id = self.gb.add_node(NodeType.BREAK, "break", stmt.lineno)
        self.gb.connect(incoming, node_id)
        if self.loop_stack:
            self.loop_stack[-1].break_out.append((node_id, ""))
        else:
            self.gb.warn("`break` used outside of a loop.")
        return []

    def _h_Continue(self, stmt: ast.Continue, incoming: Dangling) -> Dangling:
        node_id = self.gb.add_node(NodeType.CONTINUE, "continue", stmt.lineno)
        self.gb.connect(incoming, node_id)
        if self.loop_stack:
            self.gb.connect([(node_id, "")], self.loop_stack[-1].header_id, default_label="repeat")
        else:
            self.gb.warn("`continue` used outside of a loop.")
        return []

    def _h_Return(self, stmt: ast.Return, incoming: Dangling) -> Dangling:
        label = "return " + self._safe_unparse(stmt.value) if stmt.value is not None else "return"
        node_id = self.gb.add_node(NodeType.RETURN, truncate_label(label), stmt.lineno)
        self.gb.connect(incoming, node_id)
        self.gb.connect([(node_id, "")], self.return_target)
        return []

    # ---- functions (not expanded; see docs) ------------------------------ #
    def _h_FunctionDef(self, stmt: ast.FunctionDef, incoming: Dangling) -> Dangling:
        args = ", ".join(a.arg for a in stmt.args.args)
        label = truncate_label(f"def {stmt.name}({args})")
        node_id = self.gb.add_node(
            NodeType.FUNCTION, label, stmt.lineno, self._end_line(stmt), functionName=stmt.name
        )
        self.gb.warn(
            f"Function '{stmt.name}' is shown as a single step; its internal body is not expanded "
            "(see Limitations in the technical docs)."
        )
        self.gb.connect(incoming, node_id)
        return [(node_id, "")]

    _h_AsyncFunctionDef = _h_FunctionDef

    def _h_ClassDef(self, stmt: ast.ClassDef, incoming: Dangling) -> Dangling:
        label = truncate_label(f"class {stmt.name}")
        node_id = self.gb.add_node(NodeType.FUNCTION, label, stmt.lineno, self._end_line(stmt))
        self.gb.warn(f"Class '{stmt.name}' body is not expanded in the flowchart.")
        self.gb.connect(incoming, node_id)
        return [(node_id, "")]

    # ---- helpers ----------------------------------------------------------- #
    @staticmethod
    def _call_name(call: ast.Call) -> Optional[str]:
        if isinstance(call.func, ast.Name):
            return call.func.id
        if isinstance(call.func, ast.Attribute):
            return call.func.attr
        return None

    def _is_input_call(self, node: Optional[ast.AST]) -> bool:
        return isinstance(node, ast.Call) and self._call_name(node) == "input"

    def _make_io_node(self, stmt: ast.stmt, incoming: Dangling, node_type: NodeType) -> Dangling:
        label = truncate_label(self._safe_unparse(stmt))
        node_id = self.gb.add_node(node_type, label, stmt.lineno, self._end_line(stmt))
        self.gb.connect(incoming, node_id)
        return [(node_id, "")]

    @staticmethod
    def _safe_unparse(node: ast.AST) -> str:
        try:
            return ast.unparse(node)
        except Exception:
            return "<expr>"

    @staticmethod
    def _end_line(stmt: ast.stmt) -> int:
        return getattr(stmt, "end_lineno", stmt.lineno) or stmt.lineno
