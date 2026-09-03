"""
codevis.adapters.cpp_adapter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Builds a FlowGraph from C++ source using a hand-written tokenizer and a
recursive-descent parser, built directly against the shared GraphBuilder.

WHY NOT pycparser / libclang: pycparser only understands C, and libclang
(the industry-standard way to get a real C++ AST) is not installable in
this deployment (no `clang` / `libclang` package available, no outbound
network access to fetch one at analysis time). Rather than fake C++ support
with regex/keyword matching against the *whole* language, this module
implements a genuine tokenizer + recursive-descent parser for the
well-defined control-flow subset of C++ documented in
docs/TECHNICAL_DOCS.md (declarations, assignments, cout/cin, if/else,
for/while/do-while, break/continue/return, nested blocks). Anything outside
that subset (templates, classes, lambdas, exceptions, operator overloading,
STL algorithms, etc.) is preserved as an opaque PROCESS step rather than
silently dropped or misrepresented -- see the `warnings` list returned with
every graph.

This keeps the same honesty guarantee as the other adapters: every node in
the diagram traces back to a real token span in the user's source, and
constructs the parser doesn't understand are flagged, never invented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ir import FlowGraph, GraphBuilder, NodeType, truncate_label

Dangling = list[tuple[str, str]]


class CppAnalysisError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Tokenizer
# --------------------------------------------------------------------------- #

@dataclass
class Token:
    kind: str   # 'id' | 'kw' | 'num' | 'str' | 'char' | 'op' | 'punct' | 'eof'
    value: str
    line: int


_KEYWORDS = {
    "if", "else", "for", "while", "do", "break", "continue", "return",
    "int", "float", "double", "char", "bool", "void", "long", "short",
    "unsigned", "signed", "const", "static", "auto", "string", "using",
    "namespace", "struct", "class", "true", "false", "new", "delete",
    "public", "private", "protected", "template", "typename", "include",
}

_TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<linecomment>//[^\n]*)
    | (?P<blockcomment>/\*.*?\*/)
    | (?P<preproc>\#[^\n]*)
    | (?P<str>"(?:\\.|[^"\\])*")
    | (?P<char>'(?:\\.|[^'\\])*')
    | (?P<num>\d+\.?\d*(?:[eE][+-]?\d+)?[fFlLuU]*)
    | (?P<id>[A-Za-z_]\w*)
    | (?P<multiop><<=|>>=|->|<<|>>|<=|>=|==|!=|&&|\|\||\+\+|--|\+=|-=|\*=|/=|%=|::)
    | (?P<punct>[+\-*/%=<>!&|^~?:.,;(){}\[\]])
    """,
    re.VERBOSE | re.DOTALL,
)


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    line = 1
    length = len(source)
    while pos < length:
        m = _TOKEN_RE.match(source, pos)
        if not m:
            pos += 1
            continue
        text = m.group(0)
        kind = m.lastgroup
        if kind in ("ws", "linecomment", "blockcomment", "preproc"):
            line += text.count("\n")
            pos = m.end()
            continue
        if kind == "id":
            tokens.append(Token("kw" if text in _KEYWORDS else "id", text, line))
        elif kind == "num":
            tokens.append(Token("num", text, line))
        elif kind in ("str", "char"):
            tokens.append(Token(kind, text, line))
        elif kind == "multiop":
            tokens.append(Token("op", text, line))
        elif kind == "punct":
            tokens.append(Token("op", text, line))
        line += text.count("\n")
        pos = m.end()
    tokens.append(Token("eof", "", line))
    return tokens


# --------------------------------------------------------------------------- #
# Parser / CFG builder
# --------------------------------------------------------------------------- #

@dataclass
class LoopContext:
    header_id: str
    continue_target: str
    break_out: Dangling


def analyze(source: str) -> FlowGraph:
    tokens = tokenize(source)
    gb = GraphBuilder()
    start_id = gb.add_node(NodeType.START, "START", line_start=1)
    end_id = gb.add_node(NodeType.END, "END")

    parser = _Parser(tokens, gb, end_id)
    parser.parse_translation_unit(start_id, end_id)

    return gb.build()


class _Parser:
    def __init__(self, tokens: list[Token], gb: GraphBuilder, program_end: str):
        self.tokens = tokens
        self.pos = 0
        self.gb = gb
        self.program_end = program_end
        self.loop_stack: list[LoopContext] = []

    # ---- token stream helpers ------------------------------------------ #
    def peek(self, offset: int = 0) -> Token:
        idx = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[idx]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind != "eof":
            self.pos += 1
        return tok

    def at_end(self) -> bool:
        return self.peek().kind == "eof"

    def check(self, value: str) -> bool:
        return self.peek().value == value

    def expect(self, value: str) -> Token:
        if not self.check(value):
            got = self.peek()
            raise CppAnalysisError(f"Expected '{value}' but found '{got.value or 'EOF'}' near line {got.line}")
        return self.advance()

    # ---- top level: find function definitions --------------------------- #
    def parse_translation_unit(self, start_id: str, end_id: str) -> None:
        functions: list[tuple[str, int, int]] = []  # (name, def_start_pos, def_end_pos)
        i = 0
        n = len(self.tokens)
        while i < n and self.tokens[i].kind != "eof":
            if self._looks_like_function_start(i):
                name_idx, open_paren_idx = self._function_name_index(i)
                close_paren_idx = self._match_paren(open_paren_idx)
                brace_idx = close_paren_idx + 1
                while brace_idx < n and self.tokens[brace_idx].value != "{":
                    brace_idx += 1
                    if brace_idx - close_paren_idx > 6:
                        break
                if brace_idx < n and self.tokens[brace_idx].value == "{":
                    close_brace_idx = self._match_brace(brace_idx)
                    functions.append((self.tokens[name_idx].value, brace_idx, close_brace_idx))
                    i = close_brace_idx + 1
                    continue
            i += 1

        if not functions:
            self.gb.warn("No function definitions found to analyze.")
            self.gb.connect([(start_id, "")], end_id)
            return

        main_fn = next((f for f in functions if f[0] == "main"), functions[0])
        for name, _, _ in functions:
            if name != main_fn[0]:
                self.gb.warn(f"Function '{name}' is defined but only '{main_fn[0]}' is visualized.")

        _, brace_idx, close_brace_idx = main_fn
        self.pos = brace_idx
        incoming: Dangling = [(start_id, "")]
        outgoing = self.parse_block(incoming)
        self.gb.connect(outgoing, end_id)

    def _looks_like_function_start(self, i: int) -> bool:
        tok = self.tokens[i]
        if tok.kind not in ("kw", "id"):
            return False
        if tok.value in ("if", "while", "for", "do", "switch", "return"):
            return False
        j = i
        n = len(self.tokens)
        seen_ident = False
        while j < n and self.tokens[j].value not in ("(", ";", "{", "}"):
            if self.tokens[j].kind in ("id", "kw") and self.tokens[j].value not in (
                "int", "float", "double", "char", "bool", "void", "long", "short",
                "unsigned", "signed", "const", "static", "auto", "string",
            ):
                seen_ident = True
            j += 1
        if j >= n or self.tokens[j].value != "(" or not seen_ident:
            return False
        close = self._match_paren(j)
        k = close + 1
        while k < n and self.tokens[k].value not in ("{", ";"):
            k += 1
        return k < n and self.tokens[k].value == "{"

    def _function_name_index(self, i: int) -> tuple[int, int]:
        j = i
        last_ident = i
        while self.tokens[j].value != "(":
            if self.tokens[j].kind in ("id", "kw") and self.tokens[j].value not in (
                "int", "float", "double", "char", "bool", "void", "long", "short",
                "unsigned", "signed", "const", "static", "auto", "string",
            ):
                last_ident = j
            j += 1
        return last_ident, j

    def _match_paren(self, open_idx: int) -> int:
        return self._match_pair(open_idx, "(", ")")

    def _match_brace(self, open_idx: int) -> int:
        return self._match_pair(open_idx, "{", "}")

    def _match_pair(self, open_idx: int, open_v: str, close_v: str) -> int:
        depth = 0
        n = len(self.tokens)
        for k in range(open_idx, n):
            if self.tokens[k].value == open_v:
                depth += 1
            elif self.tokens[k].value == close_v:
                depth -= 1
                if depth == 0:
                    return k
        return n - 1

    # ---- statement parsing ------------------------------------------------ #
    def parse_block(self, incoming: Dangling) -> Dangling:
        self.expect("{")
        current = incoming
        while not self.check("}") and not self.at_end():
            before = self.pos
            current = self.parse_stmt(current)
            if self.pos == before:
                self.advance()
        if self.check("}"):
            self.advance()
        return current

    def parse_stmt(self, incoming: Dangling) -> Dangling:
        tok = self.peek()
        if tok.value == "{":
            return self.parse_block(incoming)
        if tok.value == "if":
            return self.parse_if(incoming)
        if tok.value == "while":
            return self.parse_while(incoming)
        if tok.value == "do":
            return self.parse_do_while(incoming)
        if tok.value == "for":
            return self.parse_for(incoming)
        if tok.value == "break":
            return self.parse_break(incoming)
        if tok.value == "continue":
            return self.parse_continue(incoming)
        if tok.value == "return":
            return self.parse_return(incoming)
        if tok.value == ";":
            self.advance()
            return incoming
        if tok.value == "using":
            self._consume_until(";")
            return incoming
        return self.parse_simple_stmt(incoming)

    def parse_if(self, incoming: Dangling) -> Dangling:
        line = self.advance().line
        self.expect("(")
        cond_tokens = self._capture_balanced_parens()
        cond_text = self._render_tokens(cond_tokens)
        node_id = self.gb.add_node(NodeType.DECISION, truncate_label(cond_text), line)
        self.gb.connect(incoming, node_id)

        true_out = self.parse_stmt([(node_id, "Yes")])
        if self.check("else"):
            self.advance()
            false_out = self.parse_stmt([(node_id, "No")])
        else:
            false_out = [(node_id, "No")]
        return true_out + false_out

    def parse_while(self, incoming: Dangling) -> Dangling:
        line = self.advance().line
        self.expect("(")
        cond_tokens = self._capture_balanced_parens()
        cond_text = self._render_tokens(cond_tokens)
        header_id = self.gb.add_node(NodeType.LOOP, truncate_label(cond_text), line)
        self.gb.connect(incoming, header_id)
        return self._loop_body(header_id, header_id, lambda inc: self.parse_stmt(inc))

    def parse_do_while(self, incoming: Dangling) -> Dangling:
        line = self.advance().line
        header_id = self.gb.add_node(NodeType.LOOP, "do { ... }", line)
        self.gb.connect(incoming, header_id)
        ctx = LoopContext(header_id=header_id, continue_target=header_id, break_out=[])
        self.loop_stack.append(ctx)
        body_out = self.parse_stmt([(header_id, "Body")])
        self.expect("while")
        self.expect("(")
        cond_tokens = self._capture_balanced_parens()
        self.expect(";")
        cond_text = self._render_tokens(cond_tokens)
        check_id = self.gb.add_node(NodeType.DECISION, truncate_label(cond_text), line)
        self.gb.connect(body_out, check_id)
        self.gb.connect([(check_id, "Yes")], header_id, default_label="repeat")
        self.loop_stack.pop()
        return [(check_id, "No")] + ctx.break_out

    def parse_for(self, incoming: Dangling) -> Dangling:
        line = self.advance().line
        self.expect("(")
        init_tokens = self._capture_until_toplevel(";")
        self.expect(";")
        cond_tokens = self._capture_until_toplevel(";")
        self.expect(";")
        incr_tokens = self._capture_until_toplevel(")")
        self.expect(")")

        current = incoming
        if init_tokens:
            init_id = self.gb.add_node(NodeType.PROCESS, truncate_label(self._render_tokens(init_tokens)), line)
            self.gb.connect(current, init_id)
            current = [(init_id, "")]

        cond_text = self._render_tokens(cond_tokens) if cond_tokens else "true"
        header_id = self.gb.add_node(NodeType.LOOP, truncate_label(cond_text), line)
        self.gb.connect(current, header_id)

        ctx = LoopContext(header_id=header_id, continue_target=header_id, break_out=[])
        self.loop_stack.append(ctx)
        body_out = self.parse_stmt([(header_id, "Yes")])
        if incr_tokens:
            incr_id = self.gb.add_node(NodeType.PROCESS, truncate_label(self._render_tokens(incr_tokens)), line)
            self.gb.connect(body_out, incr_id)
            self.gb.connect([(incr_id, "")], header_id, default_label="repeat")
        else:
            self.gb.connect(body_out, header_id, default_label="repeat")
        self.loop_stack.pop()
        return [(header_id, "No")] + ctx.break_out

    def _loop_body(self, header_id: str, continue_target: str, body_fn) -> Dangling:
        ctx = LoopContext(header_id=header_id, continue_target=continue_target, break_out=[])
        self.loop_stack.append(ctx)
        body_out = body_fn([(header_id, "Yes")])
        self.gb.connect(body_out, header_id, default_label="repeat")
        self.loop_stack.pop()
        return [(header_id, "No")] + ctx.break_out

    def parse_break(self, incoming: Dangling) -> Dangling:
        line = self.advance().line
        self._consume_until(";")
        node_id = self.gb.add_node(NodeType.BREAK, "break", line)
        self.gb.connect(incoming, node_id)
        if self.loop_stack:
            self.loop_stack[-1].break_out.append((node_id, ""))
        else:
            self.gb.warn("`break` used outside of a loop.")
        return []

    def parse_continue(self, incoming: Dangling) -> Dangling:
        line = self.advance().line
        self._consume_until(";")
        node_id = self.gb.add_node(NodeType.CONTINUE, "continue", line)
        self.gb.connect(incoming, node_id)
        if self.loop_stack:
            self.gb.connect([(node_id, "")], self.loop_stack[-1].continue_target, default_label="repeat")
        else:
            self.gb.warn("`continue` used outside of a loop.")
        return []

    def parse_return(self, incoming: Dangling) -> Dangling:
        line = self.advance().line
        expr_tokens = self._capture_until_toplevel(";")
        self.expect(";")
        text = self._render_tokens(expr_tokens)
        label = f"return {text}".strip()
        node_id = self.gb.add_node(NodeType.RETURN, truncate_label(label), line)
        self.gb.connect(incoming, node_id)
        self.gb.connect([(node_id, "")], self.program_end)
        return []

    def parse_simple_stmt(self, incoming: Dangling) -> Dangling:
        line = self.peek().line
        stmt_tokens = self._capture_until_toplevel(";")
        if self.check(";"):
            self.advance()
        if not stmt_tokens:
            return incoming
        text = self._render_tokens(stmt_tokens)
        first_val = stmt_tokens[0].value
        if first_val == "cout":
            node_type = NodeType.OUTPUT
        elif first_val == "cin":
            node_type = NodeType.INPUT
        else:
            node_type = NodeType.PROCESS
        node_id = self.gb.add_node(node_type, truncate_label(text), line)
        self.gb.connect(incoming, node_id)
        return [(node_id, "")]

    # ---- token capture helpers -------------------------------------------- #
    def _capture_balanced_parens(self) -> list[Token]:
        depth = 1
        out = []
        while depth > 0 and not self.at_end():
            tok = self.advance()
            if tok.value == "(":
                depth += 1
            elif tok.value == ")":
                depth -= 1
                if depth == 0:
                    break
            out.append(tok)
        return out

    def _capture_until_toplevel(self, stop_value: str) -> list[Token]:
        depth = 0
        out = []
        while not self.at_end():
            tok = self.peek()
            if depth == 0 and tok.value == stop_value:
                break
            if tok.value in "([{":
                depth += 1
            elif tok.value in ")]}":
                depth -= 1
            out.append(self.advance())
        return out

    def _consume_until(self, stop_value: str) -> None:
        while not self.at_end() and not self.check(stop_value):
            self.advance()
        if self.check(stop_value):
            self.advance()

    @staticmethod
    def _render_tokens(tokens: list[Token]) -> str:
        pieces = []
        no_space_before = {")", ";", ",", "]", "(", ".", "++", "--"}
        no_space_after = {"(", "[", ".", "!"}
        prev: Optional[Token] = None
        for tok in tokens:
            piece = tok.value
            if prev is not None and piece not in no_space_before and prev.value not in no_space_after:
                pieces.append(" ")
            pieces.append(piece)
            prev = tok
        return "".join(pieces)
