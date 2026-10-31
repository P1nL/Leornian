from pathlib import Path

import psycopg

from leornian.platform.config import Settings


def migrate(database_url: str, directory: Path | None = None) -> None:
    directory = directory or Path(__file__).parents[3] / "migrations"
    with psycopg.connect(database_url) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(710103001)")
        connection.execute("CREATE SCHEMA IF NOT EXISTS platform")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS platform.schema_migrations "
            "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for source in sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql")):
            version = source.name.split("_", 1)[0]
            if connection.execute(
                "SELECT 1 FROM platform.schema_migrations WHERE version = %s", (version,)
            ).fetchone():
                continue
            connection.execute(source.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO platform.schema_migrations(version) VALUES (%s)", (version,)
            )


def main() -> None:
    migrate(Settings().database_url)
    print("Leornian migrations applied.")


if __name__ == "__main__":
    main()
