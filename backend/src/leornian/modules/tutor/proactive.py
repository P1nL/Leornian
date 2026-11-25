from psycopg.types.json import Jsonb

from leornian.modules.tutor.proactive_contracts import ProactivePreference
from leornian.shared_kernel.errors import BusinessError


class ProactivePreferences:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def view(row):
        return ProactivePreference(**{k: v for k, v in row.items()
                                      if k not in {"actor_id", "session_digest"}})

    def get(self, actor, conversation_id):
        row = self.connection.execute(
            "SELECT * FROM tutor.proactive_preferences WHERE conversation_id=%s AND actor_id=%s",
            (conversation_id, actor.id),
        ).fetchone()
        return self.view(row) if row else None

    def enabled(self, limit=100):
        return self.connection.execute(
            "SELECT * FROM tutor.proactive_preferences WHERE enabled "
            "ORDER BY updated_at,conversation_id LIMIT %s", (limit,),
        ).fetchall()

    def receipt(self, actor, conversation_id, key, data=None):
        row = self.connection.execute(
            "SELECT * FROM tutor.proactive_preference_commands "
            "WHERE actor_id=%s AND command_key=%s", (actor.id, key),
        ).fetchone()
        if row:
            if row["conversation_id"] != conversation_id or (
                data is not None and row["request"] != data.model_dump(mode="json")
            ):
                raise BusinessError("idempotency_conflict", "Proactive preference command changed.")
            return ProactivePreference(**row["result"])
        if data is None:
            raise BusinessError("not_found", "Proactive preference receipt not found.")

    def set(self, actor, conversation_id, digest, key, data):
        receipt = self.receipt(actor, conversation_id, key, data)
        if receipt:
            return receipt
        current = self.get(actor, conversation_id)
        if data.expected_revision != (current.revision if current else 0):
            raise BusinessError("stale_version", "Proactive preference changed.")
        row = self.connection.execute(
            "INSERT INTO tutor.proactive_preferences(conversation_id,actor_id,enabled,"
            "timezone,start_minute,end_minute,session_digest) VALUES(%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(conversation_id) DO UPDATE SET revision="
            "tutor.proactive_preferences.revision+1,enabled=excluded.enabled,timezone=excluded.timezone,"
            "start_minute=excluded.start_minute,end_minute=excluded.end_minute,"
            "session_digest=excluded.session_digest,updated_at=now() RETURNING *",
            (conversation_id, actor.id, data.enabled, data.timezone,
             data.start_minute, data.end_minute, digest),
        ).fetchone()
        result = self.view(row)
        self.connection.execute(
            "INSERT INTO tutor.proactive_preference_commands"
            "(actor_id,command_key,conversation_id,request,result) VALUES(%s,%s,%s,%s,%s)",
            (actor.id, key, conversation_id, Jsonb(data.model_dump(mode="json")),
             Jsonb(result.model_dump(mode="json"))),
        )
        return result
