from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from leornian.shared_kernel.contracts import Contract


class NoInteraction(Contract):
    type: Literal["none"] = "none"


class ComposerInteraction(Contract):
    type: Literal["composer"]


class ArtifactInteraction(Contract):
    type: Literal["artifact"]
    exact_handle: UUID
    intent: Literal["introduce_only"]


LearningInteraction = Annotated[
    NoInteraction | ComposerInteraction | ArtifactInteraction, Field(discriminator="type")
]


class LearningReply(Contract):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    interaction: LearningInteraction


NextSpeaker = Literal["can_continue", "wait_for_reply", "wait_for_action", "wrap_up"]


class PracticeChoice(Contract):
    choice: Literal["defer", "request"]
    quote: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class TeachingPacing(Contract):
    next_step: NextSpeaker
    resume_at: Annotated[str, StringConstraints(strip_whitespace=True, max_length=240)]
    check_topic: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ] | None = None
    practice_choice: PracticeChoice | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )


class PacedLearningReply(LearningReply):
    pacing: TeachingPacing

    @model_validator(mode="after")
    def consistent_handoff(self):
        if self.interaction.type == "artifact" and self.pacing.next_step != "wait_for_action":
            raise ValueError("An introduced artifact needs wait_for_action")
        if self.interaction.type == "composer" and self.pacing.next_step != "wait_for_reply":
            raise ValueError("A composer question needs wait_for_reply")
        if self.pacing.check_topic and self.pacing.next_step not in {
            "wait_for_reply", "wait_for_action",
        }:
            raise ValueError("A teaching check must wait for the learner")
        return self
