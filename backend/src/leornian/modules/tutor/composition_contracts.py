"""Presentation proposals only; never execution, grading or publication authority."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from leornian.shared_kernel.contracts import Contract

NodeId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,15}$")]
Brief = Annotated[str, StringConstraints(min_length=1, max_length=400, pattern=r"\S")]
Code = Annotated[str, StringConstraints(min_length=1, max_length=20000, pattern=r"\S")]


class DirectedEdge(Contract):
    source: NodeId
    target: NodeId


class BfsScene(Contract):
    """One shared timeline; adjacency follows the supplied edge order."""

    type: Literal["bfs"]
    nodes: list[NodeId] = Field(min_length=1, max_length=12)
    edges: list[DirectedEdge] = Field(max_length=36)
    start: NodeId
    views: list[Literal["graph", "queue", "code", "variables"]] = Field(
        min_length=1, max_length=4,
        description="Unique views; graph is required. All views share one playback step.",
    )

    @model_validator(mode="after")
    def valid_graph(self):
        if len(set(self.nodes)) != len(self.nodes):
            raise ValueError("Node ids must be unique.")
        if self.start not in self.nodes:
            raise ValueError("Start must name an existing node.")
        pairs = [(edge.source, edge.target) for edge in self.edges]
        if len(set(pairs)) != len(pairs):
            raise ValueError("Directed edges must be unique.")
        if any(a not in self.nodes or b not in self.nodes for a, b in pairs):
            raise ValueError("Edge endpoints must name existing nodes.")
        if "graph" not in self.views or len(set(self.views)) != len(self.views):
            raise ValueError("Views must be unique and include graph.")
        return self


class CodeReviewScene(Contract):
    type: Literal["code_review"]
    prompt: Brief
    code: Code


class PublicCase(Contract):
    input: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    expected: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class CodeRepairScene(Contract):
    type: Literal["code_repair"]
    prompt: Brief
    code: Code
    cases: list[PublicCase] = Field(max_length=12)
    views: list[Literal["editor", "diff", "cases"]] = Field(
        min_length=1, max_length=3,
        description="Unique views; editor is required. Diff compares the draft with original code.",
    )

    @model_validator(mode="after")
    def valid_views(self):
        if "editor" not in self.views or len(set(self.views)) != len(self.views):
            raise ValueError("Views must be unique and include editor.")
        return self


class LearningComposition(Contract):
    """The host separately binds this proposal to an authorized artifact/revision."""

    schema_version: Literal["learning_composition.v1"]
    title: Annotated[str, StringConstraints(min_length=1, max_length=80, pattern=r"\S")]
    scene: Annotated[BfsScene | CodeReviewScene | CodeRepairScene, Field(discriminator="type")]

