from psycopg.types.json import Jsonb


class RelationParts:
    def __init__(self, connection, kind):
        self.connection = connection
        self.table = {"gate": "assessment.concept_gates", "transfer": "assessment.transfer_checks"}[
            kind
        ]

    def append(self, row, payload):
        self.connection.execute(
            f"UPDATE {self.table} SET relation_parts=relation_parts||%s "
            "WHERE id=%s AND jsonb_array_length(relation_parts)=%s",
            (Jsonb([payload]), row["id"], len(row["relation_parts"])),
        )
