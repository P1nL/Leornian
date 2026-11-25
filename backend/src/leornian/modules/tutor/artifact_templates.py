from typing import Annotated, Literal

from pydantic import Field

from leornian.modules.execution.contracts import ProjectLanguage
from leornian.modules.tutor.composition_catalog import Code, Key, Label, Text
from leornian.modules.tutor.composition_v2_contracts import LearningCompositionV2
from leornian.shared_kernel.contracts import Contract

SampleInput = Annotated[str, Field(max_length=8192)]
Options = Annotated[list[Text], Field(min_length=2, max_length=20)]


class ExampleWorkspace(Contract):
    editor: Key
    description: Key
    language: ProjectLanguage
    stdin: SampleInput = ""


class CodeWorkspaceTemplate(Contract):
    kind: Literal["code_workspace"]
    filename: Label
    language: ProjectLanguage
    code: Code
    before: Code | None = None
    stdin: SampleInput = Field(
        default="", description="Optional example values to try, one per line.",
    )


class PreviewTemplate(Contract):
    kind: Literal["web_preview"]
    html: Code
    css: Code | None = None


class StepsTemplate(Contract):
    kind: Literal["walkthrough"]
    steps: list[Text] = Field(min_length=1, max_length=100)


class ChoiceTemplate(Contract):
    kind: Literal["choice"]
    options: Options
    multiple: bool = False


class OrderingTemplate(Contract):
    kind: Literal["ordering"]
    items: Options


class ReflectionTemplate(Contract):
    kind: Literal["reflection"]


class AnnotationTemplate(Contract):
    kind: Literal["code_annotation"]
    code: Code


class PrepareLearningTemplate(Contract):
    command_key: str = Field(min_length=8, max_length=128)
    title: Label
    description: Text
    content: Annotated[
        CodeWorkspaceTemplate | PreviewTemplate | StepsTemplate | ChoiceTemplate
        | OrderingTemplate | ReflectionTemplate | AnnotationTemplate,
        Field(discriminator="kind"),
    ]

    def expand(self):
        def node(key, component, **props):
            return {"id": key, "component": component, "props": props}

        content = self.content
        states = {}
        nodes = [node("description", "Explanation", text=self.description)]
        workspace = None
        if isinstance(content, CodeWorkspaceTemplate):
            states["code"] = {"type": "code", "value": content.code}
            nodes.append(node("editor", "CodeEditor" if content.before is None else "CodeDiff",
                              state="code", label=content.filename,
                              **({"before": content.before} if content.before is not None else {})))
            workspace = ExampleWorkspace(editor="editor", description="description",
                                         language=content.language, stdin=content.stdin)
        elif isinstance(content, PreviewTemplate):
            for language, code in (("html", content.html), ("css", content.css)):
                if code is not None:
                    states[language] = {"type": "code", "value": code}
                    nodes.append(node(language, "CodeEditor",
                                      label=language.upper(), state=language))
            nodes.extend([node("preview", "IsolatedPreview", title=self.title, html_state="html",
                               css_state="css" if content.css is not None else None),
                          node("refresh", "ArtifactAction", label="更新预览", event="preview",
                               for_component="preview")])
        elif isinstance(content, StepsTemplate):
            states["step"] = {"type": "playback", "value": 0}
            nodes.append(node("steps", "StepPlayer", label=self.title,
                              state="step", items=content.steps))
        elif isinstance(content, (ChoiceTemplate, OrderingTemplate)):
            choice = isinstance(content, ChoiceTemplate)
            labels = content.options if choice else content.items
            options = [{"id": f"item{index}", "text": text} for index, text in enumerate(labels, 1)]
            states["selection"] = {"type": "choice" if choice else "order",
                                   "value": [] if choice else [option["id"] for option in options]}
            nodes.append(node("activity", "ChoiceAnswer" if choice else "OrderingAnswer",
                              label=self.title, state="selection",
                              **({"options": options, "multiple": content.multiple} if choice
                                 else {"items": options})))
        elif isinstance(content, AnnotationTemplate):
            states["code"] = {"type": "code", "value": content.code, "read_only": True}
            states["notes"] = {"type": "annotations", "value": []}
            nodes.append(node("notes", "LineRangeAnswer", label=self.title,
                              code_state="code", state="notes"))
        else:
            states["notes"] = {"type": "text", "value": ""}
            nodes.append(node("notes", "TextAnswer", label=self.title, state="notes"))
        return LearningCompositionV2.model_validate({
            "schema_version": "learning_composition.v2", "title": self.title,
            "states": states, "components": nodes,
        }), workspace
