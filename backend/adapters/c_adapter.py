"""
codevis.adapters.c_adapter
~~~~~~~~~~~~~~~~~~~~~~~~~~
Builds a FlowGraph from real C source using pycparser, a proper tokenizer +
LALR parser that produces a genuine AST (not a regex heuristic).

pycparser cannot resolve `#include <...>` headers on its own (it has no C
preprocessor / fake libc stubs bundled in this deployment). Since flowchart
generation only needs *control flow*, not the semantics of libc, we strip
preprocessor directive lines before parsing -- but we blank them out
in-place (same line count) rather than deleting them, so every AST node's
line number still matches the line number in the user's original source.
This keeps the source<->flowchart mapping feature accurate.

Only the first function definition found (conventionally `main`) is
expanded into a full flowchart. Other top-level function definitions are
represented as single FUNCTION nodes -- see docs/TECHNICAL_DOCS.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pycparser import c_ast, c_parser
from pycparser.c_parser import ParseError

from ir import FlowGraph, GraphBuilder, NodeType, truncate_label

Dangling = list[tuple[str, str]]

_PREPROCESSOR_LINE = re.compile(r"^\s*#")


def _strip_preprocessor_lines(source: str) -> str:
    """Blank out `#include`/`#define`/etc. lines while preserving line numbers."""
    out_lines = []
    for line in source.splitlines():
        out_lines.append("" if _PREPROCESSOR_LINE.match(line) else line)
    return "\n".join(out_lines)


class CAnalysisError(Exception):
    pass


@dataclass
class LoopContext:
    header_id: str
    continue_target: str
    break_out: Dangling


def analyze(source: str) -> FlowGraph:
    cleaned = _strip_preprocessor_lines(source)
    parser = c_parser.CParser()
    try:
        tree = parser.parse(cleaned, filename="<user_code>")
    except ParseError as exc:
        raise CAnalysisError(str(exc)) from exc
    except Exception as exc:
        raise CAnalysisError(f"{exc}") from exc

    gb = GraphBuilder()
    start_id = gb.add_node(NodeType.START, "START", line_start=1)
    end_id = gb.add_node(NodeType.END, "END")

    func_defs = [ext for ext in tree.ext if isinstance(ext, c_ast.FuncDef)]
    if not func_defs:
        gb.warn("No function definitions found to analyze.")
        gb.connect([(start_id, "")], end_id)
        return gb.build()

    main_func = next((f for f in func_defs if f.decl.name == "main"), func_defs[0])

    builder = _Builder(gb, end_id)
    incoming: Dangling = [(start_id, "")]
    body = main_func.body.block_items or []
    outgoing = builder.process_block(body, incoming)
    gb.connect(outgoing, end_id)

    for f in func_defs:
        if f is not main_func:
            gb.warn(f"Function '{f.decl.name}' is defined but only '{main_func.decl.name}' is visualized.")

    return gb.build()


class _Builder:
    def __init__(self, gb: GraphBuilder, return_target: str):
        self.gb = gb
        self.return_target = return_target
        self.loop_stack: list[LoopContext] = []

    # ------------------------------------------------------------------ #
    def process_block(self, items: list, incoming: Dangling) -> Dangling:
        current = incoming
        for i, item in enumerate(items):
            current = self.process_stmt(item, current)
            if not current and i + 1 < len(items):
                self.gb.warn(f"Unreachable code detected after line {self._line(item)}.")
                break
        return current

    def process_stmt(self, node, incoming: Dangling) -> Dangling:
        handler = getattr(self, f"_h_{type(node).__name__}", None)
        if handler:
            return handler(node, incoming)
        label = truncate_label(self._render(node))
        node_id = self.gb.add_node(NodeType.PROCESS, label, self._line(node))
        self.gb.connect(incoming, node_id)
        return [(node_id, "")]

    # ---- declarations / assignments / calls --------------------------- #
    def _h_Decl(self, node: c_ast.Decl, incoming: Dangling) -> Dangling:
        label = truncate_label(self._render_decl(node))
        node_id = self.gb.add_node(NodeType.PROCESS, label, self._line(node))
        self.gb.connect(incoming, node_id)
        return [(node_id, "")]

    def _h_Assignment(self, node: c_ast.Assignment, incoming: Dangling) -> Dangling:
        label = truncate_label(f"{self._render(node.lvalue)} {node.op} {self._render(node.rvalue)}")
        node_id = self.gb.add_node(NodeType.PROCESS, label, self._line(node))
        self.gb.connect(incoming, node_id)
        return [(node_id, "")]

    def _h_UnaryOp(self, node: c_ast.UnaryOp, incoming: Dangling) -> Dangling:
        label = truncate_label(self._render(node))
        node_id = self.gb.add_node(NodeType.PROCESS, label, self._line(node))
        self.gb.connect(incoming, node_id)
        return [(node_id, "")]

    def _h_FuncCall(self, node: c_ast.FuncCall, incoming: Dangling) -> Dangling:
        name = node.name.name if isinstance(node.name, c_ast.ID) else "call"
        label = truncate_label(self._render(node))
        node_type = NodeType.OUTPUT if name == "printf" else NodeType.INPUT if name == "scanf" else NodeType.PROCESS
        node_id = self.gb.add_node(node_type, label, self._line(node))
        self.gb.connect(incoming, node_id)
        return [(node_id, "")]

    def _h_Compound(self, node: c_ast.Compound, incoming: Dangling) -> Dangling:
        return self.process_block(node.block_items or [], incoming)

    def _h_EmptyStatement(self, node, incoming: Dangling) -> Dangling:
        return incoming

    # ---- branching ------------------------------------------------------ #
    def _h_If(self, node: c_ast.If, incoming: Dangling) -> Dangling:
        cond_label = truncate_label(self._render(node.cond))
        node_id = self.gb.add_node(NodeType.DECISION, cond_label, self._line(node))
        self.gb.connect(incoming, node_id)

        true_items = self._as_list(node.iftrue)
        true_out = self.process_block(true_items, [(node_id, "Yes")])

        if node.iffalse is not None:
            false_items = self._as_list(node.iffalse)
            false_out = self.process_block(false_items, [(node_id, "No")])
        else:
            false_out = [(node_id, "No")]
        return true_out + false_out

    # ---- loops ------------------------------------------------------------ #
    def _h_While(self, node: c_ast.While, incoming: Dangling) -> Dangling:
        cond_label = truncate_label(self._render(node.cond))
        header_id = self.gb.add_node(NodeType.LOOP, cond_label, self._line(node))
        self.gb.connect(incoming, header_id)
        return self._loop_body(header_id, header_id, self._as_list(node.stmt))

    def _h_DoWhile(self, node: c_ast.DoWhile, incoming: Dangling) -> Dangling:
        cond_label = truncate_label(f"do ... while ({self._render(node.cond)})")
        header_id = self.gb.add_node(NodeType.LOOP, cond_label, self._line(node))
        # do-while executes the body before the first check
        self.gb.connect(incoming, header_id)
        return self._loop_body(header_id, header_id, self._as_list(node.stmt), enter_label="Body", exit_label="Done")

    def _h_For(self, node: c_ast.For, incoming: Dangling) -> Dangling:
        init = self._render(node.init) if node.init else ""
        cond = self._render(node.cond) if node.cond else "true"
        nxt = self._render(node.next) if node.next else ""
        current = incoming
        if init:
            init_id = self.gb.add_node(NodeType.PROCESS, truncate_label(init), self._line(node))
            self.gb.connect(current, init_id)
            current = [(init_id, "")]
        header_id = self.gb.add_node(NodeType.LOOP, truncate_label(cond), self._line(node))
        self.gb.connect(current, header_id)

        ctx = LoopContext(header_id=header_id, continue_target=header_id, break_out=[])
        self.loop_stack.append(ctx)
        body_out = self.process_block(self._as_list(node.stmt), [(header_id, "Yes")])
        if nxt:
            incr_id = self.gb.add_node(NodeType.PROCESS, truncate_label(nxt), self._line(node))
            self.gb.connect(body_out, incr_id)
            self.gb.connect([(incr_id, "")], header_id, default_label="repeat")
        else:
            self.gb.connect(body_out, header_id, default_label="repeat")
        self.loop_stack.pop()

        return [(header_id, "No")] + ctx.break_out

    def _loop_body(self, header_id: str, continue_target: str, stmts: list, enter_label="Yes", exit_label="No") -> Dangling:
        ctx = LoopContext(header_id=header_id, continue_target=continue_target, break_out=[])
        self.loop_stack.append(ctx)
        body_out = self.process_block(stmts, [(header_id, enter_label)])
        self.gb.connect(body_out, header_id, default_label="repeat")
        self.loop_stack.pop()
        return [(header_id, exit_label)] + ctx.break_out

    # ---- jumps -------------------------------------------------------------- #
    def _h_Break(self, node: c_ast.Break, incoming: Dangling) -> Dangling:
        node_id = self.gb.add_node(NodeType.BREAK, "break", self._line(node))
        self.gb.connect(incoming, node_id)
        if self.loop_stack:
            self.loop_stack[-1].break_out.append((node_id, ""))
        else:
            self.gb.warn("`break` used outside of a loop.")
        return []

    def _h_Continue(self, node: c_ast.Continue, incoming: Dangling) -> Dangling:
        node_id = self.gb.add_node(NodeType.CONTINUE, "continue", self._line(node))
        self.gb.connect(incoming, node_id)
        if self.loop_stack:
            self.gb.connect([(node_id, "")], self.loop_stack[-1].continue_target, default_label="repeat")
        else:
            self.gb.warn("`continue` used outside of a loop.")
        return []

    def _h_Return(self, node: c_ast.Return, incoming: Dangling) -> Dangling:
        label = "return " + self._render(node.expr) if node.expr is not None else "return"
        node_id = self.gb.add_node(NodeType.RETURN, truncate_label(label), self._line(node))
        self.gb.connect(incoming, node_id)
        self.gb.connect([(node_id, "")], self.return_target)
        return []

    # ---- rendering helpers ---------------------------------------------------- #
    @staticmethod
    def _as_list(stmt) -> list:
        if stmt is None:
            return []
        if isinstance(stmt, c_ast.Compound):
            return stmt.block_items or []
        return [stmt]

    @staticmethod
    def _line(node) -> int:
        return node.coord.line if getattr(node, "coord", None) else 0

    def _render(self, node) -> str:
        if node is None:
            return ""
        return _CRenderer().visit(node)

    def _render_decl(self, node: c_ast.Decl) -> str:
        type_str = _CRenderer().type_str(node.type)
        if node.init is not None:
            return f"{type_str} {node.name} = {self._render(node.init)}"
        return f"{type_str} {node.name}"


class _CRenderer(c_ast.NodeVisitor):
    """Minimal expression -> C source-text renderer for flowchart labels."""

    def visit(self, node) -> str:
        method = getattr(self, f"visit_{type(node).__name__}", None)
        if method:
            return method(node)
        return "<expr>"

    def visit_ID(self, node: c_ast.ID) -> str:
        return node.name

    def visit_Constant(self, node: c_ast.Constant) -> str:
        return str(node.value)

    def visit_BinaryOp(self, node: c_ast.BinaryOp) -> str:
        return f"{self.visit(node.left)} {node.op} {self.visit(node.right)}"

    def visit_UnaryOp(self, node: c_ast.UnaryOp) -> str:
        if node.op in ("p++", "p--"):
            return f"{self.visit(node.expr)}{node.op[1:]}"
        return f"{node.op}{self.visit(node.expr)}"

    def visit_Assignment(self, node: c_ast.Assignment) -> str:
        return f"{self.visit(node.lvalue)} {node.op} {self.visit(node.rvalue)}"

    def visit_ArrayRef(self, node: c_ast.ArrayRef) -> str:
        return f"{self.visit(node.name)}[{self.visit(node.subscript)}]"

    def visit_StructRef(self, node: c_ast.StructRef) -> str:
        return f"{self.visit(node.name)}{node.type}{self.visit(node.field)}"

    def visit_Cast(self, node: c_ast.Cast) -> str:
        return f"({self.type_str(node.to_type)}){self.visit(node.expr)}"

    def visit_FuncCall(self, node: c_ast.FuncCall) -> str:
        name = self.visit(node.name)
        args = ", ".join(self.visit(a) for a in (node.args.exprs if node.args else []))
        return f"{name}({args})"

    def visit_ExprList(self, node: c_ast.ExprList) -> str:
        return ", ".join(self.visit(e) for e in node.exprs)

    def visit_DeclList(self, node: c_ast.DeclList) -> str:
        return ", ".join(self.visit_Decl_inline(d) for d in node.decls)

    def visit_Decl_inline(self, node: c_ast.Decl) -> str:
        base = f"{self.type_str(node.type)} {node.name}"
        if node.init is not None:
            return f"{base} = {self.visit(node.init)}"
        return base

    def visit_InitList(self, node: c_ast.InitList) -> str:
        return "{" + ", ".join(self.visit(e) for e in node.exprs) + "}"

    def type_str(self, type_node) -> str:
        if isinstance(type_node, c_ast.TypeDecl):
            return self.type_str(type_node.type)
        if isinstance(type_node, c_ast.IdentifierType):
            return " ".join(type_node.names)
        if isinstance(type_node, c_ast.PtrDecl):
            return self.type_str(type_node.type) + "*"
        if isinstance(type_node, c_ast.ArrayDecl):
            return self.type_str(type_node.type) + "[]"
        return "auto"
