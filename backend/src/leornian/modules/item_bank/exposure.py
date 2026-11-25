from psycopg.types.json import Jsonb


class Exposures:
    """Append-only delivered question/feedback facts, not model guesses about exposure."""

    def __init__(self, connection):
        self.connection = connection

    def revision(self, actor, *, lock=False):
        row = self.connection.execute(
            "SELECT revision FROM item_bank.exposure_heads WHERE actor_id=%s"
            + (" FOR SHARE" if lock else ""),
            (actor.id,),
        ).fetchone()
        return row["revision"] if row else 0

    def record(self, actor, pack_id, question, feedback=None, *, receipt_ref=None):
        self.connection.execute(
            "INSERT INTO item_bank.exposure_heads(actor_id) VALUES(%s) ON CONFLICT DO NOTHING",
            (actor.id,),
        )
        self.connection.execute(
            "SELECT revision FROM item_bank.exposure_heads WHERE actor_id=%s FOR UPDATE",
            (actor.id,),
        )
        public = question.public() if hasattr(question, "public") else question
        data = {"question": public.model_dump(mode="json")}
        kind = "feedback" if feedback is not None else "question"
        if feedback is not None:
            data["feedback"] = (
                {
                    "selected_key": feedback.selected_key,
                    "correct": feedback.correct,
                    "explanation": feedback.explanation,
                }
                if hasattr(feedback, "selected_key")
                else feedback.model_dump(mode="json")
            )
        inserted = self.connection.execute(
            "INSERT INTO item_bank.exposure_facts"
            "(actor_id,pack_id,slot,kind,public_content,receipt_key) VALUES(%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT DO NOTHING RETURNING slot",
            (actor.id, pack_id, public.slot, kind, Jsonb(data), str(receipt_ref or "")),
        ).fetchone()
        if inserted:
            self.connection.execute(
                "UPDATE item_bank.exposure_heads SET revision=revision+1 WHERE actor_id=%s",
                (actor.id,),
            )
        self.connection.execute(
            "INSERT INTO item_bank.exposures(pack_id,slot) VALUES(%s,%s) ON CONFLICT DO NOTHING",
            (pack_id, public.slot),
        )

    def snapshot(self, actor):
        revision = self.revision(actor, lock=True)
        rows = self.connection.execute(
            "SELECT DISTINCT ON (pack_id,slot) pack_id,slot,public_content,'' AS receipt_key "
            "FROM item_bank.exposure_facts WHERE actor_id=%s AND receipt_key='' "
            "ORDER BY pack_id,slot,(kind='feedback') DESC",
            (actor.id,),
        ).fetchall()
        rows += self.connection.execute(
            "SELECT pack_id,slot,public_content,receipt_key FROM item_bank.exposure_facts "
            "WHERE actor_id=%s AND receipt_key<>'' ORDER BY exposed_at,pack_id,slot,receipt_key",
            (actor.id,),
        ).fetchall()
        return revision, [
            {
                "key": str(row["pack_id"]) + ":" + row["slot"]
                + (":" + row["receipt_key"] if row["receipt_key"] else ""),
                **row["public_content"],
            }
            for row in rows
        ]
