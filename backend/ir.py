"""
codevis.ir
~~~~~~~~~~
Language-independent intermediate representation (IR) for program flow.

Every language adapter (Python, C, C++, and future languages) must translate
its own AST into this common shape. Nothing downstream of this module
(layout, API responses, tests) needs to know which language produced the
graph -- that's the whole point of having an IR.

    source code --[adapter]--> FlowGraph (FlowNode + FlowEdge) --[API]--> frontend

This module intentionally has zero dependencies on Flask, pycparser, or the
Python ast module, so it can be unit tested and reused in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class NodeType(str, Enum):
    START = "START"
    END = "END"
    PROCESS = "PROCESS"       # assignment / expression statement
    DECISION = "DECISION"     # if / elif / ternary condition
    LOOP = "LOOP"             # for / while / do-while header
    INPUT = "INPUT"           # input() / scanf / cin
    OUTPUT = "OUTPUT"         # print() / printf / cout
    FUNCTION = "FUNCTION"     # a function definition not otherwise expanded
    RETURN = "RETURN"
    BREAK = "BREAK"
    CONTINUE = "CONTINUE"


@dataclass
class FlowNode:
    id: str
    type: NodeType
    label: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value if isinstance(self.type, NodeType) else self.type,
            "label": self.label,
            "sourceLineStart": self.line_start,
            "sourceLineEnd": self.line_end,
            "metadata": self.metadata,
        }


@dataclass
class FlowEdge:
    id: str
    source: str
    target: str
    label: str = ""
    condition: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "label": self.label,
            "condition": self.condition,
            "metadata": self.metadata,
        }


@dataclass
class FlowGraph:
    nodes: list[FlowNode] = field(default_factory=list)
    edges: list[FlowEdge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # unsupported-construct notices

    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "warnings": self.warnings,
        }


class GraphBuilder:
    """
    Shared control-flow-graph construction helper used by every language
    adapter. Encapsulates the parts of CFG construction that have nothing to
    do with any particular source language: node/edge id allocation, and the
    "dangling edge" bookkeeping used to stitch sequential statements, if/else
    branches, and loops together.

    Convention used throughout adapters:
        A "dangling edge set" is a list of (source_node_id, label) tuples
        representing control-flow exits from a block that have not yet been
        connected to whatever comes next. Processing a statement takes the
        current dangling set as its *incoming* connections and returns a new
        dangling set representing control leaving that statement.
    """

    def __init__(self) -> None:
        self.nodes: list[FlowNode] = []
        self.edges: list[FlowEdge] = []
        self.warnings: list[str] = []
        self._node_counter = 0
        self._edge_counter = 0

    def add_node(
        self,
        type_: NodeType,
        label: str,
        line_start: Optional[int] = None,
        line_end: Optional[int] = None,
        **metadata: Any,
    ) -> str:
        self._node_counter += 1
        node_id = f"n{self._node_counter}"
        self.nodes.append(
            FlowNode(
                id=node_id,
                type=type_,
                label=label,
                line_start=line_start,
                line_end=line_end if line_end is not None else line_start,
                metadata=metadata,
            )
        )
        return node_id

    def connect(
        self,
        dangling: list[tuple[str, str]],
        target: str,
        default_label: str = "",
    ) -> None:
        """Wire every dangling (source, label) pair to `target`."""
        for source, label in dangling:
            self._edge_counter += 1
            self.edges.append(
                FlowEdge(
                    id=f"e{self._edge_counter}",
                    source=source,
                    target=target,
                    label=label or default_label,
                )
            )

    def add_edge(self, source: str, target: str, label: str = "", condition: Optional[str] = None) -> str:
        self._edge_counter += 1
        edge_id = f"e{self._edge_counter}"
        self.edges.append(FlowEdge(id=edge_id, source=source, target=target, label=label, condition=condition))
        return edge_id

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def build(self) -> FlowGraph:
        return FlowGraph(nodes=self.nodes, edges=self.edges, warnings=self.warnings)


def truncate_label(text: str, max_len: int = 42) -> str:
    text = " ".join(text.split())  # collapse whitespace/newlines
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "\u2026"
    return text
