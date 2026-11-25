"""Closed presentation data and ports for the existing learning components."""

from typing import Annotated, Literal, Union

from pydantic import Field, StringConstraints, create_model, model_validator

from leornian.modules.knowledge.contracts import SourceRef
from leornian.modules.learning.contracts import MaterialCitation
from leornian.shared_kernel.contracts import Contract

Key = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,39}$")]
ItemId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")]
Label = Annotated[str, StringConstraints(min_length=1, max_length=120, pattern=r"\S")]
Text = Annotated[str, StringConstraints(min_length=1, max_length=400, pattern=r"\S")]
Code = Annotated[str, StringConstraints(max_length=20000)]
Cell = Annotated[str, StringConstraints(max_length=500)]
Number = Annotated[float, Field(allow_inf_nan=False, ge=-1_000_000, le=1_000_000)]


class CodeState(Contract):
    type: Literal["code"]
    value: Code
    read_only: bool = False


class TextState(Contract):
    type: Literal["text"]
    value: Literal[""] = ""


class ChoiceState(Contract):
    type: Literal["choice"]
    value: list[ItemId] = Field(default_factory=list, max_length=0)


class OrderState(Contract):
    type: Literal["order"]
    value: list[ItemId] = Field(max_length=30)


class AnnotationState(Contract):
    type: Literal["annotations"]
    # Empty at preparation: learner responses never originate in a model proposal.
    value: list[str] = Field(default_factory=list, max_length=0)


class PlaybackState(Contract):
    type: Literal["playback"]
    value: Literal[0] = 0


class NumberState(Contract):
    type: Literal["number"]
    value: Number


class SelectionState(Contract):
    type: Literal["selection"]
    value: ItemId | None = None


class ProjectFile(Contract):
    path: Annotated[str, StringConstraints(
        min_length=1, max_length=160,
        pattern=r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)*\.[A-Za-z0-9_-]+$",
    )]
    content: str = Field(max_length=100000)
    read_only: bool = False


class FilesState(Contract):
    type: Literal["files"]
    files: list[ProjectFile] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def safe_files(self):
        paths = [f.path for f in self.files]
        if len(paths) != len(set(paths)) or any(".." in p.split("/") for p in paths):
            raise ValueError("Files need distinct relative paths without traversal.")
        if sum(len(f.content.encode("utf-8")) for f in self.files) > 100000:
            raise ValueError("Project display content exceeds 100 KB.")
        return self


CompositionState = Annotated[
    CodeState | TextState | ChoiceState | OrderState | AnnotationState | PlaybackState
    | NumberState | SelectionState | FilesState,
    Field(discriminator="type"),
]


class TextProps(Contract):
    title: Label | None = None
    text: Text


class CitationProps(Contract):
    label: Label
    citation: MaterialCitation | SourceRef


class CodeProps(Contract):
    label: Label
    state: Key


class DiffProps(CodeProps):
    before: Code


class TableProps(Contract):
    label: Label
    columns: list[Label] = Field(min_length=1, max_length=12)
    rows: list[list[Cell]] = Field(max_length=100)

    @model_validator(mode="after")
    def rectangular(self):
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Every row must match the declared columns.")
        return self


class NamedValue(Contract):
    name: Label
    value: Cell


class ValuesProps(Contract):
    label: Label
    entries: list[NamedValue] = Field(max_length=30)


class PreviewProps(Contract):
    title: Label
    html_state: Key
    css_state: Key | None = None


class TreeEntry(Contract):
    id: Key
    label: Label
    children: list["TreeEntry"] = Field(default_factory=list, max_length=30)


class TreeProps(Contract):
    label: Label
    nodes: list[TreeEntry] = Field(min_length=1, max_length=30)
    state: Key

    @model_validator(mode="after")
    def bounded_tree(self):
        seen = set()

        def walk(nodes, depth):
            if depth > 8:
                raise ValueError("A tree may have at most eight levels.")
            for node in nodes:
                if node.id in seen or len(seen) >= 200:
                    raise ValueError("Tree ids must be distinct and bounded.")
                seen.add(node.id)
                walk(node.children, depth + 1)

        walk(self.nodes, 1)
        return self


class GraphNode(Contract):
    id: ItemId
    label: Label
    x: Number
    y: Number


class GraphEdge(Contract):
    source: ItemId
    target: ItemId
    label: Label | None = None


class GraphProps(Contract):
    label: Label
    nodes: list[GraphNode] = Field(min_length=1, max_length=30)
    edges: list[GraphEdge] = Field(max_length=80)
    state: Key

    @model_validator(mode="after")
    def endpoints(self):
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)) or any(
            e.source not in ids or e.target not in ids for e in self.edges
        ):
            raise ValueError("Graph endpoints must name distinct declared nodes.")
        return self


class Participant(Contract):
    id: ItemId
    label: Label


class SequenceStep(GraphEdge):
    id: Key
    label: Label


class SequenceProps(Contract):
    label: Label
    participants: list[Participant] = Field(min_length=1, max_length=12)
    steps: list[SequenceStep] = Field(min_length=1, max_length=100)
    state: Key

    @model_validator(mode="after")
    def participants_exist(self):
        ids = [p.id for p in self.participants]
        if (
            len(ids) != len(set(ids))
            or len({s.id for s in self.steps}) != len(self.steps)
            or any(s.source not in ids or s.target not in ids for s in self.steps)
        ):
            raise ValueError("Sequence ids and participant endpoints are invalid.")
        return self


class AlgorithmProps(Contract):
    """Algorithm inputs, never model-generated frames or executable algorithms."""

    label: Label
    algorithm: Literal[
        "binary_search", "brackets", "bfs", "grid_paths",
        "combination_sum", "interval_scan", "bitwise", "geometry",
    ]
    state: Key
    input: Key
    show_code: bool = True
    show_variables: bool = True


class AlgorithmViewProps(Contract):
    label: Label
    timeline: Key


class Option(Contract):
    id: ItemId
    text: Annotated[str, StringConstraints(min_length=1, max_length=500, pattern=r"\S")]


class ChoiceProps(Contract):
    label: Label
    options: list[Option] = Field(min_length=2, max_length=20)
    multiple: bool = False
    state: Key

    @model_validator(mode="after")
    def distinct_options(self):
        if len({o.id for o in self.options}) != len(self.options):
            raise ValueError("Options need distinct ids.")
        return self


class TextAnswerProps(Contract):
    label: Label
    state: Key


class OrderingProps(Contract):
    label: Label
    items: list[Option] = Field(min_length=2, max_length=30)
    state: Key

    @model_validator(mode="after")
    def distinct_options(self):
        if len({o.id for o in self.items}) != len(self.items):
            raise ValueError("Ordering items need distinct ids.")
        return self


class AnnotationProps(Contract):
    label: Label
    code_state: Key
    state: Key


class ParameterProps(Contract):
    label: Label
    state: Key
    minimum: Number
    maximum: Number
    step: Annotated[float, Field(gt=0, le=1000000, allow_inf_nan=False)] = 1

    @model_validator(mode="after")
    def valid_range(self):
        if self.minimum >= self.maximum:
            raise ValueError("Parameter minimum must be below maximum.")
        return self


class StepsProps(Contract):
    label: Label
    items: list[Text] = Field(min_length=1, max_length=100)
    state: Key


class FeedbackProps(Contract):
    label: Label
    for_component: Key


class ActionProps(Contract):
    label: Label
    # An intent request is not a permission. Only host allowed_actions enables it.
    event: Literal["submit_answer", "submit_review", "check_code", "preview", "cancel"]
    for_component: Key
    primary: bool = False


class GroupProps(Contract):
    members: list[Key] = Field(min_length=1, max_length=12)


# Each tuple is name, category, typed props, state kinds, output port names.
# This is the contract directory, not a set of business tools.
COMPONENTS = (
    ("Explanation", "content", TextProps, (), ()),
    ("SourceReference", "content", CitationProps, (), ("open_source",)),
    ("CodeBlock", "code", CodeProps, ("code",), ()),
    ("CodeEditor", "code", CodeProps, ("code", "files"), ("change",)),
    ("CodeDiff", "code", DiffProps, ("code",), ("change",)),
    ("DataTable", "data", TableProps, (), ()),
    ("KeyValueList", "data", ValuesProps, (), ()),
    ("IsolatedPreview", "visual", PreviewProps, (), ("preview",)),
    ("TreeView", "visual", TreeProps, ("selection",), ("select",)),
    ("RelationGraph", "visual", GraphProps, ("selection",), ("select",)),
    ("SequenceDiagram", "visual", SequenceProps, ("playback",), ("step",)),
    ("AlgorithmPlayer", "visual", AlgorithmProps, ("playback",), ("step",)),
    ("AlgorithmSequence", "visual", AlgorithmViewProps, (), ()),
    ("AlgorithmContainer", "visual", AlgorithmViewProps, (), ()),
    ("AlgorithmGraph", "visual", AlgorithmViewProps, (), ()),
    ("AlgorithmGrid", "visual", AlgorithmViewProps, (), ()),
    ("AlgorithmRecursion", "visual", AlgorithmViewProps, (), ()),
    ("AlgorithmIntervals", "visual", AlgorithmViewProps, (), ()),
    ("AlgorithmBits", "visual", AlgorithmViewProps, (), ()),
    ("AlgorithmGeometry", "visual", AlgorithmViewProps, (), ()),
    ("ChoiceAnswer", "answer", ChoiceProps, ("choice",), ("change",)),
    ("TextAnswer", "answer", TextAnswerProps, ("text",), ("change",)),
    ("OrderingAnswer", "answer", OrderingProps, ("order",), ("change",)),
    ("LineRangeAnswer", "answer", AnnotationProps, ("annotations",), ("save", "remove")),
    ("ParameterControl", "answer", ParameterProps, ("number",), ("change",)),
    ("StepPlayer", "process", StepsProps, ("playback",), ("step",)),
    ("AnswerFeedback", "feedback", FeedbackProps, (), ()),
    ("ResultFeedback", "feedback", FeedbackProps, (), ()),
    ("ReviewFinding", "feedback", FeedbackProps, (), ()),
    ("ArtifactAction", "actions", ActionProps, (), ("request",)),
    ("ActionGroup", "actions", GroupProps, (), ()),
)
COMPONENT_BY_NAME = {item[0]: item for item in COMPONENTS}
ComponentName = Literal[tuple(COMPONENT_BY_NAME)]
NODE_MODELS = tuple(
    create_model(
        name + "Component", __base__=Contract,
        id=(Key, ...), component=(Literal[name], ...), props=(props, ...),
    )
    for name, _category, props, _states, _outputs in COMPONENTS
)
# Types are supplied by the trusted directory rather than a static type expression.
CompositionComponent = Annotated[Union[NODE_MODELS], Field(discriminator="component")]  # noqa: UP007


def component_directory(names=None):
    """Generated guide/tool data uses the same models that validate proposals."""
    selected = set(names) if names is not None else set(COMPONENT_BY_NAME)
    if not selected <= COMPONENT_BY_NAME.keys():
        raise ValueError("Unknown learning component.")
    return [
        {
            "component": name, "category": category, "props_schema": props.model_json_schema(),
            "state_kinds": list(states), "outputs": list(outputs),
            "authority": "presentation_only; host owns permission, execution and results",
        }
        for name, category, props, states, outputs in COMPONENTS if name in selected
    ]
