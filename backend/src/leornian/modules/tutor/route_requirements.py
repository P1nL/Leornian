from typing import Literal
from uuid import UUID

from psycopg.types.json import Jsonb
from pydantic import Field, field_validator

from leornian.shared_kernel.contracts import Contract
from leornian.shared_kernel.errors import BusinessError


class RouteRequirementChange(Contract):
    key: Literal[
        "goal", "prior_knowledge", "availability", "included_scope", "excluded_scope", "preferences"
    ]
    value: str | None = Field(min_length=1, max_length=1200)
    source_turn_id: UUID
    source_quote: str = Field(min_length=1, max_length=4000)

    @field_validator("value", "source_quote")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("A requirement or source quote cannot be blank.")
        return value


class RouteRequirements:
    """Tutor's checked learner facts; route assumptions remain in the plan."""

    def __init__(self, connection):
        self.connection = connection

    def get(self, conversation_id):
        return self.connection.execute(
            "SELECT * FROM tutor.route_requirements WHERE conversation_id=%s",
            (conversation_id,),
        ).fetchone()

    def context(self, conversation_id, turn_id):
        saved = self.get(conversation_id)
        last = saved["last_turn_id"] if saved else None
        # Recover older goal-level discussions once, then carry only unprocessed learner input.
        messages = self.connection.execute(
            "SELECT id AS turn_id,user_text FROM tutor.turns WHERE conversation_id=%s "
            "AND purpose IN ('planning','teaching') AND context_focus->>'kind'='goal' "
            "AND teaching_intent_id IS NULL AND (completed_at IS NOT NULL OR id=%s) "
            "AND (created_at,id)<=(SELECT created_at,id FROM tutor.turns WHERE id=%s) "
            + ("AND (created_at,id)>(SELECT created_at,id FROM tutor.turns WHERE id=%s) "
               if last else "")
            + "ORDER BY created_at,id",
            (conversation_id, turn_id, turn_id, *((last,) if last else ())),
        ).fetchall()
        return {
            "revision": saved["revision"] if saved else 0,
            "learner_stated": saved["learner_stated"] if saved else {},
            "learner_messages": [
                {"turn_id": str(item["turn_id"]), "text": item["user_text"]} for item in messages
            ],
        }

    @staticmethod
    def validate_changes(snapshot, changes):
        if len({item.key for item in changes}) != len(changes):
            raise ValueError("Update each requirement at most once.")
        sources = {
            item["turn_id"]: item["text"]
            for item in (snapshot or {}).get("learner_messages", [])
        }
        for item in changes:
            text = sources.get(str(item.source_turn_id))
            if text is None or item.source_quote not in text:
                raise ValueError("A requirement needs an exact supplied learner quote and turn.")

    def accept(self, conversation_id, turn_id, snapshot, changes):
        self.validate_changes(snapshot, changes)
        saved = self.get(conversation_id)
        revision = saved["revision"] if saved else 0
        if revision != snapshot["revision"]:
            raise BusinessError("stale_version", "Route requirements changed during discussion.")
        facts = dict(saved["learner_stated"]) if saved else {}
        for item in changes:
            if item.value is None:
                facts.pop(item.key, None)
            else:
                facts[item.key] = item.model_dump(mode="json", exclude={"key"})
        result = self.connection.execute(
            "INSERT INTO tutor.route_requirements"
            "(conversation_id,revision,learner_stated,last_turn_id) VALUES(%s,%s,%s,%s) "
            "ON CONFLICT (conversation_id) DO UPDATE SET revision=EXCLUDED.revision,"
            "learner_stated=EXCLUDED.learner_stated,last_turn_id=EXCLUDED.last_turn_id,"
            "updated_at=now() WHERE tutor.route_requirements.revision=%s RETURNING revision",
            (conversation_id, revision + 1, Jsonb(facts), turn_id, revision),
        ).fetchone()
        if not result:
            raise BusinessError("stale_version", "Route requirements changed during discussion.")
