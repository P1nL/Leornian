"""Tutor-owned reading reports for checked, submission-pinned reviews."""

from uuid import uuid4

from leornian.modules.tutor.review_contracts import ReviewCompletion, ReviewReportView
from leornian.shared_kernel.errors import BusinessError


class ReviewReports:
    def __init__(self, connection):
        self.connection = connection

    def views(self, artifact, bindings):
        bindings = [
            binding for binding in bindings
            if binding["profile_version"] == "submitted-code-review.v2"
        ]
        if not bindings:
            return []
        completed = {
            row["component_id"]: ReviewCompletion(**row)
            for row in self.connection.execute(
                "SELECT * FROM tutor.review_completions WHERE artifact_id=%s",
                (artifact["id"],),
            ).fetchall()
        }
        return [
            ReviewReportView(
                component_id=binding["component_id"],
                state="completed" if binding["component_id"] in completed else (
                    "cancelled" if artifact["state"] in {"cancelled", "superseded"}
                    else "ready"
                ),
                allowed_actions=["complete_review"] if (
                    artifact["state"] == "ready"
                    and binding["component_id"] not in completed
                ) else [],
                completion=completed.get(binding["component_id"]),
            )
            for binding in bindings
        ]

    def complete(self, artifact, presentation, binding):
        if self.connection.execute(
            "SELECT 1 FROM tutor.review_completions WHERE artifact_id=%s AND component_id=%s",
            (artifact["id"], binding["component_id"]),
        ).fetchone():
            raise BusinessError("precondition_failed", "This review is already recorded.")
        return ReviewCompletion(**self.connection.execute(
            "INSERT INTO tutor.review_completions"
            "(id,artifact_id,component_id,presentation_id,content_identity,"
            "attempt_id,evaluation_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (
                uuid4(), artifact["id"], binding["component_id"], presentation["id"],
                presentation["public_identity"], binding["attempt"]["id"],
                binding["evaluation_id"],
            ),
        ).fetchone())
