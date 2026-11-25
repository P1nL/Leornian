"""Versioned composition data: explicit component ports, no expression language."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from leornian.modules.tutor.composition_catalog import (
    COMPONENT_BY_NAME,
    CompositionComponent,
    CompositionState,
    ItemId,
    Key,
    Label,
    Number,
)
from leornian.modules.tutor.composition_contracts import BfsScene, DirectedEdge, NodeId
from leornian.shared_kernel.contracts import Contract


class BinarySearchInput(Contract):
    type: Literal["binary_search"]
    values: list[int] = Field(min_length=1, max_length=40)
    target_state: Key

    @model_validator(mode="after")
    def sorted_values(self):
        if self.values != sorted(self.values):
            raise ValueError("Binary search requires sorted input.")
        return self


class BracketsInput(Contract):
    type: Literal["brackets"]
    text: Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[()\[\]{}]+$")]


class BfsInput(Contract):
    type: Literal["bfs"]
    nodes: list[NodeId] = Field(min_length=1, max_length=12)
    edges: list[DirectedEdge] = Field(max_length=36)
    start: NodeId

    @model_validator(mode="after")
    def graph(self):
        BfsScene.model_validate({
            **self.model_dump(), "views": ["graph"],
        })
        return self


class GridCell(Contract):
    row: int = Field(ge=0, le=11)
    column: int = Field(ge=0, le=11)


class GridPathsInput(Contract):
    type: Literal["grid_paths"]
    rows: int = Field(ge=1, le=12)
    columns: int = Field(ge=1, le=12)
    blocked: list[GridCell] = Field(default_factory=list, max_length=144)

    @model_validator(mode="after")
    def valid_cells(self):
        cells = [(c.row, c.column) for c in self.blocked]
        if len(cells) != len(set(cells)) or any(
            row >= self.rows or col >= self.columns for row, col in cells
        ):
            raise ValueError("Blocked cells must be distinct and inside the grid.")
        return self


class CombinationInput(Contract):
    """Positive subset sum: each input position is considered at most once."""

    type: Literal["combination_sum"]
    values: list[Annotated[int, Field(ge=1, le=100)]] = Field(min_length=1, max_length=10)
    target: int = Field(ge=1, le=1000)


class Interval(Contract):
    id: ItemId
    start: Number
    end: Number

    @model_validator(mode="after")
    def valid_interval(self):
        if self.start >= self.end:
            raise ValueError("An interval needs start < end.")
        return self


class IntervalsInput(Contract):
    type: Literal["interval_scan"]
    intervals: list[Interval] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique_intervals(self):
        if len({item.id for item in self.intervals}) != len(self.intervals):
            raise ValueError("Interval ids must be distinct.")
        return self


class BitsInput(Contract):
    type: Literal["bitwise"]
    left: int = Field(ge=0, le=65535)
    right: int = Field(ge=0, le=65535)
    operation: Literal["and", "or", "xor"]
    width: int = Field(ge=1, le=16)

    @model_validator(mode="after")
    def fits_width(self):
        if max(self.left, self.right) >= 2 ** self.width:
            raise ValueError("Values must fit the selected bit width.")
        return self


class Point(Contract):
    id: ItemId
    x: Number
    y: Number


class GeometryInput(Contract):
    """Orientation of three points by the signed cross product."""

    type: Literal["geometry"]
    points: list[Point] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def distinct_points(self):
        if len({p.id for p in self.points}) != 3 or len({(p.x, p.y) for p in self.points}) != 3:
            raise ValueError("Orientation needs three distinct labeled points.")
        return self


AlgorithmInput = Annotated[
    BinarySearchInput | BracketsInput | BfsInput | GridPathsInput | CombinationInput
    | IntervalsInput | BitsInput | GeometryInput,
    Field(discriminator="type"),
]
ALGORITHM_VIEWS = {
    "AlgorithmSequence": {"binary_search", "brackets"},
    "AlgorithmContainer": {"brackets", "bfs", "combination_sum"},
    "AlgorithmGraph": {"bfs"},
    "AlgorithmGrid": {"grid_paths"},
    "AlgorithmRecursion": {"combination_sum"},
    "AlgorithmIntervals": {"interval_scan"},
    "AlgorithmBits": {"bitwise"},
    "AlgorithmGeometry": {"geometry"},
}


class PresentationCapabilities(Contract):
    versions: list[Literal["learning_composition.v2"]] = Field(
        default_factory=list, max_length=1
    )
    actions: list[Literal[
        "learning_practice.v2", "learning_responses.v1", "learning_code_review.v1",
        "learning_code_review.v2",
        "learning_programs.v1", "learning_programs.v2",
        "learning_direct_answers.v1", "learning_hints.v1",
        "learning_demo_events.v1", "learning_example_runs.v1", "learning_example_runs.v2",
        "learning_templates.v1",
    ]] = Field(
        default_factory=list, max_length=9
    )

    @model_validator(mode="after")
    def action_renderer(self):
        if len(set(self.actions)) != len(self.actions):
            raise ValueError("Action capabilities must be distinct.")
        if {"learning_code_review.v1", "learning_code_review.v2"} <= set(self.actions):
            raise ValueError("Declare one submitted-code review capability version.")
        if {"learning_example_runs.v1", "learning_example_runs.v2"} <= set(self.actions):
            raise ValueError("Declare one example run capability version.")
        if self.actions and "learning_composition.v2" not in self.versions:
            raise ValueError("Practice actions require the V2 composition renderer.")
        return self


class LearningCompositionV2(Contract):
    schema_version: Literal["learning_composition.v2"]
    title: Label
    layout: Literal["stack", "split"] = "stack"
    states: dict[Key, CompositionState] = Field(default_factory=dict, max_length=32)
    inputs: dict[Key, AlgorithmInput] = Field(default_factory=dict, max_length=12)
    components: list[CompositionComponent] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def legal_ports(self):
        nodes = {node.id: node for node in self.components}
        if len(nodes) != len(self.components):
            raise ValueError("Component ids must be unique.")
        children = set()
        for node in self.components:
            props = node.props
            allowed_states = COMPONENT_BY_NAME[node.component][3]
            if allowed_states:
                state = self.states.get(props.state)
                if state is None or state.type not in allowed_states:
                    raise ValueError(f"{node.id}: missing or incompatible state port.")
            if node.component == "OrderingAnswer":
                ids = [i.id for i in props.items]
                if sorted(self.states[props.state].value) != sorted(ids):
                    raise ValueError("Ordering state must be a permutation of its item ids.")
            if node.component == "ParameterControl":
                value = self.states[props.state].value
                if not props.minimum <= value <= props.maximum:
                    raise ValueError("Parameter state is outside its range.")
            if node.component == "LineRangeAnswer":
                code = self.states.get(props.code_state)
                if code is None or code.type != "code" or not code.read_only:
                    raise ValueError("Review annotations need a read-only code snapshot.")
            if node.component == "IsolatedPreview":
                for key in (props.html_state, props.css_state):
                    if key and (key not in self.states or self.states[key].type != "code"):
                        raise ValueError("Preview inputs must reference inert code states.")
            if node.component == "AlgorithmPlayer":
                source = self.inputs.get(props.input)
                if not source or source.type != props.algorithm:
                    raise ValueError("Algorithm and input contract must agree.")
                if source.type == "binary_search":
                    target = self.states.get(source.target_state)
                    if target is None or target.type != "number":
                        raise ValueError("Binary-search target needs a number state.")
            if node.component in ALGORITHM_VIEWS:
                player = nodes.get(props.timeline)
                if (
                    not player or player.component != "AlgorithmPlayer"
                    or player.props.algorithm not in ALGORITHM_VIEWS[node.component]
                ):
                    supported = ", ".join(sorted(ALGORITHM_VIEWS[node.component]))
                    raise ValueError(
                        f"{node.id}.timeline must reference an AlgorithmPlayer component id "
                        f"using {supported}, not a playback state key."
                    )
            if node.component in {
                "ArtifactAction", "AnswerFeedback", "ResultFeedback", "ReviewFinding"
            }:
                target = nodes.get(props.for_component)
                if target is None or target.id == node.id:
                    raise ValueError("An event/feedback target must name another component.")
                if node.component == "ArtifactAction":
                    targets = {
                        "submit_answer": {"ChoiceAnswer", "TextAnswer", "OrderingAnswer"},
                        "submit_review": {"LineRangeAnswer"},
                        "check_code": {"CodeEditor", "CodeDiff"},
                        "preview": {"IsolatedPreview"},
                        "cancel": set(COMPONENT_BY_NAME) - {"ActionGroup", "ArtifactAction"},
                    }
                    if target.component not in targets[props.event]:
                        raise ValueError("The requested event is not supported by this port.")
            if node.component == "ActionGroup":
                if len(props.members) != len(set(props.members)):
                    raise ValueError("Action-group members must be distinct.")
                for child in props.members:
                    member = nodes.get(child)
                    if not member or member.component != "ArtifactAction" or child in children:
                        raise ValueError(
                            "An action has exactly one group; nested groups forbidden."
                        )
                    children.add(child)
        return self
