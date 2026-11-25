"""Assemble a checked node reply without giving a handoff repair ownership of its text."""

import json
import re
from copy import deepcopy
from itertools import pairwise

from pydantic import ValidationError

from leornian.modules.tutor.interaction_contracts import LearningReply, PacedLearningReply


class MissingHandoff(ValueError):
    def __init__(self, draft, fields, diagnostics=()):
        super().__init__("Complete the teaching decision fields: " + ", ".join(fields))
        self.draft = draft
        self.fields = fields
        self.diagnostics = list(diagnostics)

    def narrows(self, previous):
        return set(self.fields) != set(previous) and all(
            any(field == old or field.startswith(old + ".") for old in previous)
            for field in self.fields
        )


def pending_handoff(task):
    return next((issue for issue in task.get("issues", ()) if
                 issue.get("code") == "node_handoff_required" and "frozen_reply" in issue), None)


def unique_fields(pairs):
    data = dict(pairs)
    if len(data) != len(pairs):
        raise ValueError("The reply contains duplicate fields.")
    return data


OPERATION_TARGET = "candidate.text.operation:"


def pending_operations(task):
    if task.get("issues"):
        repair = task["issues"][0].get("operation_repair")
        if repair and repair["candidate_call_id"] == str(task.get("candidate_call_id")):
            return repair
    return None


def operation_quotes(candidate, issues):
    if not issues or not all(issue["target_ref"].startswith(OPERATION_TARGET) for issue in issues):
        return []
    try:
        reply = json.loads(candidate)
    except (TypeError, ValueError):
        return []
    if not isinstance(reply, dict) or not isinstance(text := reply.get("text"), str):
        return []
    quotes = {issue["target_ref"][len(OPERATION_TARGET):] for issue in issues}
    if any(not quote.strip() or text.find(quote) < 0 or text.find(quote) != text.rfind(quote)
           for quote in quotes):
        return []
    ordered = sorted(quotes, key=text.index)
    if any(text.index(first) + len(first) > text.index(second)
           for first, second in pairwise(ordered)):
        return []
    return ordered


def revise_operations(candidate, quotes, content):
    replacements = json.loads(content, object_pairs_hook=unique_fields)
    if (not isinstance(replacements, dict) or replacements.keys() != set(quotes)
        or not all(isinstance(value, str) for value in replacements.values())):
        raise ValueError("Return one replacement string per exact operation quote.")
    reply = json.loads(candidate)
    text = original = reply["text"]
    for quote in reversed(quotes):
        start = original.index(quote)
        text = text[:start] + replacements[quote] + text[start + len(quote):]
    return assemble({**reply, "text": text}, paced="pacing" in reply), replacements


def assemble(draft, *, paced, required_handle=None):
    data = deepcopy(draft)
    if required_handle:
        data.setdefault("interaction", {"type": "artifact", "exact_handle": required_handle})
    interaction = data.get("interaction")
    pacing = data.get("pacing")
    if isinstance(interaction, dict):
        kind = interaction.get("type")
        if kind == "artifact":
            interaction.setdefault("intent", "introduce_only")
        step = {"artifact": "wait_for_action", "composer": "wait_for_reply"}.get(kind) if (
            isinstance(kind, str)
        ) else None
        if paced and step and "pacing" not in data:
            pacing = data["pacing"] = {}
        if paced and step and isinstance(pacing, dict):
            pacing.setdefault("next_step", step)
    if paced and isinstance(pacing, dict):
        if pacing.get("next_step") in ("can_continue", "wrap_up"):
            data.setdefault("interaction", {"type": "none"})
        if pacing.get("next_step") == "wrap_up":
            pacing.setdefault("resume_at", "")
    contract = PacedLearningReply if paced else LearningReply
    try:
        validated = contract.model_validate_json(json.dumps(data), strict=True)
        return validated.model_copy(update={"text": data["text"]}).model_dump_json()
    except ValidationError as error:
        diagnostics = []
        for item in error.errors(include_input=False, include_url=False):
            path = item["loc"]
            if (not path or path[0] not in {"interaction", "pacing"}
                or item["type"] == "extra_forbidden"):
                raise
            if len(path) > 1 and path[0] == "interaction" and path[1] in {
                "none", "artifact", "composer",
            }:
                path = ("interaction", *path[2:])
            parent = data
            for name in path[:-1]:
                parent = parent[name]
            parent.pop(path[-1], None)
            diagnostics.append({"type": item["type"], "path": list(path), "message": item["msg"]})
        fields = [".".join(issue["path"]) for issue in diagnostics]
        raise MissingHandoff(data, fields, diagnostics) from error


def merge_handoff(issue, content):
    patch = json.loads(content, object_pairs_hook=unique_fields)
    if not isinstance(patch, dict) or set(patch) != set(issue["missing_fields"]):
        raise ValueError("Return exactly the requested handoff fields, without text.")
    result = deepcopy(issue["frozen_reply"])
    for path, value in patch.items():
        parent = result
        *parents, key = path.split(".")
        for name in parents:
            parent = parent[name]
        if key in parent or path.split(".")[0] not in {"interaction", "pacing"}:
            raise ValueError("A handoff patch cannot replace a supplied field.")
        parent[key] = value
    return result


def node_candidate(task, content):
    paced = bool(task["context_manifest"].get("node_pacing"))
    required_handle = task["context_manifest"].get("required_learning_handle")
    issue = pending_handoff(task)
    if issue:
        return assemble(merge_handoff(issue, content), paced=paced, required_handle=required_handle)
    text = content.strip()
    if not text:
        raise ValueError("The learner-facing explanation is missing.")
    fenced = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", text, re.S | re.I)
    try:
        data = json.loads(fenced[1] if fenced else text, object_pairs_hook=unique_fields)
    except json.JSONDecodeError:
        data = None
    if fenced and isinstance(data, dict) and data.keys() == {"text"}:
        data = None
    if isinstance(data, dict) and data.keys() & {"fragment", "complete"}:
        if not {"fragment", "complete"} <= data.keys():
            raise ValueError("Incomplete fragment envelope.")
        part = data["fragment"]
        if (type(data["complete"]) is not bool or not isinstance(part, dict)
            or set(part) != {"text"} or not isinstance(part["text"], str)
            or not part["text"].strip() or part in task["fragments"]
            or data.keys() - {"fragment", "complete", "pacing", "interaction"}):
            raise ValueError("Invalid teaching fragment.")
        fragments = [*task["fragments"], part]
        if not data["complete"]:
            if "interaction" in data or "pacing" in data:
                raise ValueError("Only the final fragment may choose a handoff.")
            return fragments
        text = "\n\n".join(item["text"] for item in fragments)
        data = {key: value for key, value in data.items() if key in {"pacing", "interaction"}}
        data["text"] = text
    elif task["fragments"]:
        raise ValueError("Finish the remaining text in an explicit final fragment.")
    if isinstance(data, dict) and data.keys() & {"text", "interaction", "pacing"}:
        return assemble(data, paced=paced, required_handle=required_handle)
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\{\s*"(?:text|interaction|pacing|fragment|complete)"\s*:', text):
        try:
            nested, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            if match.start() == 0 or re.search(
                r'"(?:pacing|interaction)"\s*:', text[match.start():],
            ):
                raise ValueError("Malformed reply envelope; return one complete reply.") from None
            continue
        if isinstance(nested, dict) and (
            "text" in nested and nested.keys() & {"interaction", "pacing"}
            or {"fragment", "complete"} <= nested.keys()
        ):
            raise ValueError("Ambiguous reply envelope; revise the content as one complete reply.")
    if paced or required_handle:
        return assemble({"text": content}, paced=paced, required_handle=required_handle)
    return content
