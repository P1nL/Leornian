"""Lossless raw coverage first; a separate summary pass checks cross-batch risks."""

import json

from leornian.agent_runtime.gateway import ModelProtocolError
from leornian.agent_runtime.policies import estimate_tokens
from leornian.modules.assessment.gate_contracts import GateRelations, RelationCheck
from leornian.modules.assessment.relation_parts import RelationParts


class RelationBatches:
    # This is a per-call working set, never a total history, exposure or attempt cap.
    working_tokens = 12000

    @staticmethod
    def context_key(row):
        return (
            "learning_context" if "learning_context" in row["context_data"] else "teaching_context"
        )

    @classmethod
    def batches(cls, row):
        data = row["context_data"]
        if not data.get("batched_review"):
            return []
        key = cls.context_key(row)
        if estimate_tokens(data) < cls.working_tokens and len(row["comparisons"]) <= 20:
            return []
        batches = []
        fixed = {
            k: v
            for k, v in data.items()
            if k not in {key, "training_and_exposure", "actual_exposures"}
        }
        entries = data.get("training_and_exposure", data.get("actual_exposures", []))
        pending_pairs = []
        pending_entries = []
        for pair in row["comparisons"]:
            if pair["right"] == key:
                continue
            selected = [
                entry
                for entry in entries
                if pair["right"] in {entry.get("key"), "seen:" + entry.get("key", "")}
            ]
            trial = {
                "context": {**fixed, "compared_exposure": pending_entries + selected},
                "required_comparisons": pending_pairs + [pair],
            }
            if pending_pairs and (
                estimate_tokens(trial) > cls.working_tokens or len(pending_pairs) >= 12
            ):
                batches.append(
                    {
                        "context": {**fixed, "compared_exposure": pending_entries},
                        "required_comparisons": pending_pairs,
                        "coverage": [p["right"] for p in pending_pairs],
                    }
                )
                pending_pairs, pending_entries = [], []
            pending_pairs.append(pair)
            pending_entries.extend(entry for entry in selected if entry not in pending_entries)
        if pending_pairs:
            batches.append(
                {
                    "context": {**fixed, "compared_exposure": pending_entries},
                    "required_comparisons": pending_pairs,
                    "coverage": [p["right"] for p in pending_pairs],
                }
            )
        raw = json.dumps(data[key], ensure_ascii=False, indent=2)
        # Preserve every character, including code and all actual exposure facts. These
        # are explicitly labelled fragments, never presented as complete standalone facts.
        chars = max(512, cls.working_tokens // 2)
        fragments = [raw[i : i + chars] for i in range(0, len(raw), chars)]
        pairs = [p for p in row["comparisons"] if p["right"] == key]
        for index, fragment in enumerate(fragments):
            batches.append(
                {
                    "context": {
                        **fixed,
                        key: {
                            "serialized_fragment": fragment,
                            "index": index,
                            "total": len(fragments),
                        },
                    },
                    "required_comparisons": pairs,
                    "coverage": [f"{key}:{index}/{len(fragments)}"],
                }
            )
        # Summaries supplement, never replace the preceding raw-fragment comparisons.
        batches.append(
            {"context": fixed, "required_comparisons": pairs, "coverage": ["cross_batch_risk"]}
        )
        return batches

    @classmethod
    def payload(cls, row):
        batches = cls.batches(row)
        if not batches:
            return None
        index = len(row["relation_parts"])
        payload = dict(batches[index])
        if index == len(batches) - 1:
            payload["reviewed_raw_summaries"] = [
                part["report"].get("exposure_summary", "") for part in row["relation_parts"]
            ]
        payload["batch_index"] = index
        payload["batch_total"] = len(batches)
        return payload

    @classmethod
    def consume(cls, connection, row, report, kind, call_id=None):
        batches = cls.batches(row)
        if not batches:
            return report
        index = len(row["relation_parts"])
        payload = batches[index]
        expected = {(p["left"], p["right"]) for p in payload["required_comparisons"]}
        actual = {(p.left, p.right) for p in report.comparisons}
        required = {(p["left"], p["right"]) for p in row["comparisons"]}
        # Additional opinions about another real pair are retained, including negatives.
        # They never replace that pair's remaining raw-fragment or cross-batch coverage.
        if not expected <= actual <= required or not report.exposure_summary:
            raise ModelProtocolError("invalid_relation_batch")
        part = {
            "coverage": payload["coverage"],
            "report": report.model_dump(mode="json"),
            "call_id": str(call_id) if call_id else None,
        }
        RelationParts(connection, kind).append(row, part)
        parts = row["relation_parts"] + [part]
        gate_blocked = kind == "gate" and any(
            check.verdict != "distinct_decision" for check in report.comparisons
        )
        if len(parts) != len(batches) and not gate_blocked:
            return None
        priority = {"distinct_decision": 0, "uncertain": 1, "answer_leakage": 2}
        combined = {}
        for part in parts:
            for check in part["report"]["comparisons"]:
                pair = (check["left"], check["right"])
                previous = combined.get(pair)
                if previous is None or priority[check["verdict"]] > priority[previous["verdict"]]:
                    combined[pair] = check
        if gate_blocked:
            for pair in row["comparisons"]:
                combined.setdefault(
                    (pair["left"], pair["right"]),
                    {
                        **pair,
                        "verdict": "uncertain",
                        "reason": "Not reviewed: an earlier raw batch already blocks this Gate.",
                    },
                )
        return GateRelations(comparisons=[RelationCheck(**p) for p in combined.values()])
