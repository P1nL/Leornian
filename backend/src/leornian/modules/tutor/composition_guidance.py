"""Opt-in teaching context; not a tool and not injected into existing frozen runs."""

import json
from pathlib import Path

from leornian.modules.tutor.composition_catalog import component_directory
from leornian.modules.tutor.composition_contracts import LearningComposition
from leornian.modules.tutor.composition_v2_contracts import LearningCompositionV2


def composition_guidance(version="learning_composition.v1") -> str:
    """Use only after the host enables composition proposals for a supported client."""
    if version == "learning_composition.v2":
        guide = (
            "# Dynamic learning composition\n\n"
            "The client supports learning_composition.v2. There is no recipe switch or "
            "three-recipe component limit. Choose the task, actual data, compatible state "
            "ports and explicit events from the directory below. Read exact props with "
            "get_learning_component_contracts when needed. The directory is presentation, "
            "not tools or execution permissions.\n\n"
            "## Compose by responsibility\n\n"
            "- Content: keep substantial teaching in the message; Explanation is a short "
            "local observation. SourceReference must use an actually supplied exact citation.\n"
            "- Code: code/file states can be viewed, edited or diffed. A check action requires "
            "an original published owner and a declared action capability; files/SQL are not "
            "implicitly executable. Legacy file displays retain 20,000 characters per file; "
            "larger files require an actual program owner and the program preparation/reader "
            "capability, within 100 KB total. Never add a scorer, runtime, test or "
            "install command. In the current native host, CodeDiff compares fixed before "
            "text with the editable current code using a locally toggled unified inline diff, "
            "not separate left/right panes. Describe that actual control; do not promise a "
            "side-by-side layout that this component does not provide.\n"
            "- Data: tables and key-values display supplied public data, not invented grades.\n"
            "- Visual: link AlgorithmPlayer to a typed input and named compatible timeline "
            "views. An algorithm view's timeline names the AlgorithmPlayer component id, "
            "not its playback state key; only the player's state names that state key. "
            "The client derives frames; never generate a trace as a result. Tree, "
            "relation and sequence views consume their own typed data. IsolatedPreview is "
            "inert HTML/CSS with scripts/network forbidden, not a Runner or assessment. "
            "For each preview with editable HTML/CSS, include an ArtifactAction with "
            "event='preview' and for_component set to that IsolatedPreview id. Editing "
            "does not update its iframe; starting or acknowledging a demo does not refresh "
            "it either. The preview action only refreshes the local sandbox; it NEVER "
            "records a demo event or completion. Label it as an update, not a report. "
            "The learner must separately report the preview and confirm completion. "
            "A different preview's action cannot update this one.\n"
            "- Answer: ChoiceAnswer, TextAnswer, OrderingAnswer and LineRangeAnswer require "
            "exact published response bindings for business submission. Use only candidate "
            "ids actually listed in this Run. Keep option/item identities and read-only review "
            "code unchanged. Short answers are reference-only, review reasons ungraded. "
            "Each bound answer/editor also needs its own visible ArtifactAction targeting that "
            "component: submit_answer for choice/text/order, submit_review for LineRangeAnswer, "
            "check_code for CodeEditor/CodeDiff. Editing, feedback, hints and demo controls do "
            "not submit answers or execute code. ArtifactAction event='cancel' always cancels "
            "the whole artifact, regardless of for_component. Never target a bound practice "
            "with this event or label it as canceling only that practice. The host separately "
            "provides each queued/running practice's exact active-attempt cancellation and "
            "explicit retry controls; do not invent static replacements. "
            "ParameterControl changes a local observation input, never a grade.\n"
            "- Process: a shared timeline or StepPlayer supports local stepping, pause and "
            "replay. Playback completion does not complete a lesson or write progress.\n"
            "- Demo reports: only a separately frozen learning_demo_events.v1 tool can bind "
            "AlgorithmPlayer, StepPlayer, SequenceDiagram or IsolatedPreview event ports. "
            "The server derives the endpoint/preview requirement. The learner explicitly "
            "starts an input-pinned generation, reports the event, and confirms browsing. "
            "Nonce/sequence receipts prevent replay, not dishonest visibility claims. "
            "Reports never certify comprehension or authorize automatic teaching.\n"
            "- Feedback: AnswerFeedback, ResultFeedback and ReviewFinding reference an exact "
            "owner component. Only the host's committed receipts supply results or findings. "
            "When submitted-code review is explicitly supported, its dedicated preparation "
            "tool binds CodeBlock + ReviewFinding to the actual public Attempt, fills the "
            "submitted code, and independently checks teaching comments before delivery. "
            "A learning_code_review.v2 preparation also provides an explicit learner reading "
            "confirmation for that exact review. Only the learner's complete_review command "
            "records it. The original score stays fixed; edits/new execution remain in the "
            "original workspace.\n"
            "- Actions: ArtifactAction requests a closed intent; ActionGroup groups named "
            "actions. No callback, expression, endpoint, permissions or caller test set.\n\n"
            "## Prepare and deliver\n\n"
            "Use only tools frozen for this Run. Local preparation is not business-action "
            "authority. Original single-choice/Python and new response compositions require "
            "their separately declared capability and matching preparation tool. SQL/multifile "
            "sources use learning_programs.v1 and their dedicated list/prepare tools, with "
            "exact published query/files and fixed environment. Mixed owners each retain their "
            "own capability. Actual public sample results never come from model tables. When no "
            "suitable source exists and request_learning_practice_supply is frozen for this "
            "Run, queue the original supply task and finish the turn with interaction none; "
            "do not invent questions or poll while blocking the task. A later learner turn "
            "reads status and lists published candidates before composition. Only select "
            "a returned prepared candidate.id as exact_handle for independent checked delivery. "
            "Preparation is not publication, exposure, scoring or execution. UNKNOWN never "
            "authorizes resend. If an owner/profile is unavailable, state the actual limitation "
            "instead of fabricating a working widget or grade.\n\n"
            "## Authoritative component directory\n\n"
            + "\n".join(
                f"- {item['component']} [{item['category']}]: state ports "
                f"{','.join(item['state_kinds']) or 'none'}; output ports "
                f"{','.join(item['outputs']) or 'none'}."
                for item in component_directory()
            )
        )
        schema = LearningCompositionV2.model_json_schema()
    elif version == "learning_composition.v1":
        guide = Path(__file__).with_name("composition-guide.md").read_text(encoding="utf-8")
        schema = LearningComposition.model_json_schema()
    else:
        raise ValueError("Unsupported composition version.")
    return guide + "\n\n## Authoritative JSON Schema\n\n" + json.dumps(
        schema, ensure_ascii=False
    )

