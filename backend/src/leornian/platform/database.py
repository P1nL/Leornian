from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row


class Database:
    def __init__(self, url: str):
        self.url = url

    @contextmanager
    def transaction(self, *, snapshot: bool = False) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.url, row_factory=dict_row, connect_timeout=5) as connection:
            if snapshot:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            yield connection

    def ready(self) -> bool:
        with self.transaction() as connection:
            return connection.execute(
                "SELECT EXISTS(SELECT 1 FROM platform.schema_migrations "
                "WHERE version = '0009') AS ok"
            ).fetchone()["ok"]
