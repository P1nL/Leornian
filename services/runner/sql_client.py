"""Trusted DB client inside a credential-free, networkless learner sandbox."""

import json
import sqlite3
import sys
from decimal import Decimal

MAX_ROWS = 100
MAX_COLUMNS = 12


def identifier(value, dialect):
    quote = "`" if dialect == "mysql" else '"'
    return quote + value + quote


def sqlite_connection(data):
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("BEGIN")
    for table in data["schema_definition"]["tables"]:
        columns = [
            identifier(c["name"], "sqlite") + " " + {
                "integer": "INTEGER", "text": "TEXT", "real": "REAL", "boolean": "INTEGER",
            }[c["type"]] + (" NOT NULL" if not c["nullable"] or c["primary_key"] else "")
            + (" PRIMARY KEY" if c["primary_key"] else "")
            for c in table["columns"]
        ]
        columns += [
            "FOREIGN KEY(" + identifier(k["column"], "sqlite") + ") REFERENCES "
            + identifier(k["references_table"], "sqlite") + "("
            + identifier(k["references_column"], "sqlite") + ") DEFERRABLE INITIALLY DEFERRED"
            for k in table["foreign_keys"]
        ]
        connection.execute(f'CREATE TABLE "{table["name"]}" (' + ",".join(columns) + ")")
    for table in data["schema_definition"]["tables"]:
        markers = ",".join("?" for _ in table["columns"])
        connection.executemany(
            f'INSERT INTO "{table["name"]}" VALUES ({markers})',
            data["dataset"]["rows"][table["name"]],
        )
    connection.commit()
    connection.enable_load_extension(False)
    connection.execute("PRAGMA query_only=ON")
    denied_functions = {"load_extension", "readfile", "writefile", "edit"}

    def authorize(action, first, second, _database, _trigger):
        if action not in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
                          sqlite3.SQLITE_RECURSIVE}:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and (second or "").lower() in denied_functions:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    connection.set_authorizer(authorize)
    for limit, size in (
        (sqlite3.SQLITE_LIMIT_ATTACHED, 0), (sqlite3.SQLITE_LIMIT_COLUMN, 32),
        (sqlite3.SQLITE_LIMIT_SQL_LENGTH, 12000), (sqlite3.SQLITE_LIMIT_LENGTH, 131072),
        (sqlite3.SQLITE_LIMIT_VDBE_OP, 100000),
    ):
        connection.setlimit(limit, size)
    return connection


def connect(data):
    if data["dialect"] == "sqlite":
        return sqlite_connection(data)
    if data["dialect"] == "postgresql":
        import psycopg

        connection = psycopg.connect(
            host="/socket", dbname="course", user="learner", connect_timeout=3,
            options="-c statement_timeout=5000 -c lock_timeout=1000", autocommit=True,
        )
        connection.execute("BEGIN READ ONLY")
        return connection
    import pymysql

    connection = pymysql.connect(
        unix_socket="/socket/mysql.sock", user="learner", database="course",
        connect_timeout=3, read_timeout=6, write_timeout=3, local_infile=False,
        charset="utf8mb4", autocommit=True,
    )
    with connection.cursor() as cursor:
        cursor.execute("SET SESSION MAX_EXECUTION_TIME=5000")
        cursor.execute("START TRANSACTION READ ONLY")
    return connection


def cell(value):
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("Non-finite SQL cells are not supported.")
        text = format(number, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return "0" if number == 0 else text
    raise ValueError("This SQL result type is outside the table profile.")


def cell_type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, (float, Decimal)):
        return "number"
    return "text"


def main():
    data = json.load(sys.stdin)
    try:
        connection = connect(data)
        expected_version = data.get("runtime_version")
        if data["dialect"] == "sqlite":
            version = sqlite3.sqlite_version
        elif data["dialect"] == "postgresql":
            number = connection.info.server_version
            version = str(number // 10000) + "." + str(number % 10000)
        else:
            version = connection.get_server_info().split("-")[0]
        if expected_version is not None and version != expected_version:
            connection.close()
            raise ValueError("The exact SQL environment version changed.")
    except Exception as error:
        print(type(error).__name__ + ": SQL environment unavailable.", file=sys.stderr)
        return 70
    try:
        cursor = connection.cursor()
        if data["dialect"] == "postgresql":
            cursor.execute(data["query"], prepare=True)
        else:
            cursor.execute(data["query"])
        if not cursor.description or len(cursor.description) > MAX_COLUMNS:
            raise ValueError("A read-only query with at most 12 result columns is required.")
        rows = cursor.fetchmany(MAX_ROWS + 1)
        columns = [column[0] for column in cursor.description]
        if len(rows) > MAX_ROWS:
            raise ValueError("SQL result exceeds the 100-row profile.")
        if data["dialect"] == "mysql" and cursor.nextset():
            raise ValueError("Multiple SQL results are outside the single-query profile.")
        result = {
            "profile": "sql-table.v1",
            "columns": columns,
            "rows": [[cell(value) for value in row] for row in rows],
            "types": [[cell_type(value) for value in row] for row in rows],
        }
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) >= 4095:
            raise ValueError("SQL result exceeds the public output limit.")
        print(encoded)
        return 0
    except Exception as error:
        print(type(error).__name__ + ": " + str(error)[:500], file=sys.stderr)
        return 2
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
