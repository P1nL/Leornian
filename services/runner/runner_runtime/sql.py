"""Isolated SQL datasets, short-lived database servers and checks."""

import json
import os
import secrets
import subprocess
import time
from pathlib import Path

from .sandbox import (
    IMAGE,
    CleanupError,
    _bounded_container,
    _container_options,
    _docker,
    _mount,
    _new_volume,
    _remove_container,
    _remove_volume,
    _stage_volume,
    _unavailable_cases,
)


def _sql_literal(value, dialect):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + value.replace("'", "''") + "'"



def _sql_setup(data, dataset):
    dialect = data["dialect"]
    quote = "`" if dialect == "mysql" else '"'

    def identifier(value):
        return quote + value + quote

    statements = [] if dialect == "sqlite" else [
        "SET standard_conforming_strings=on" if dialect == "postgresql"
        else "SET SESSION sql_mode='NO_BACKSLASH_ESCAPES,STRICT_ALL_TABLES'",
    ]
    for table in data["schema_definition"]["tables"]:
        columns = []
        for column in table["columns"]:
            kind = {
                "integer": "INTEGER", "text": "VARCHAR(500)" if dialect == "mysql" else "TEXT",
                "real": "DOUBLE PRECISION" if dialect == "postgresql" else "DOUBLE",
                "boolean": "BOOLEAN",
            }[column["type"]]
            required = not column["nullable"] or column["primary_key"]
            columns.append(identifier(column["name"]) + " " + kind
                           + (" NOT NULL" if required else "")
                           + (" PRIMARY KEY" if column["primary_key"] else ""))
        if dialect == "sqlite":
            columns += [
                "FOREIGN KEY(" + identifier(key["column"]) + ") REFERENCES "
                + identifier(key["references_table"]) + "("
                + identifier(key["references_column"]) + ")"
                for key in table["foreign_keys"]
            ]
        statements.append("CREATE TABLE " + identifier(table["name"]) + "("
                          + ",".join(columns) + ")")
    # Populate before adding relationships so the schema need not use dependency order.
    for table in data["schema_definition"]["tables"]:
        for row in dataset["rows"][table["name"]]:
            statements.append("INSERT INTO " + identifier(table["name"]) + " VALUES("
                              + ",".join(_sql_literal(v, dialect) for v in row) + ")")
    for table in data["schema_definition"]["tables"]:
        for key in table["foreign_keys"]:
            if dialect == "sqlite":
                continue
            statements.append(
                "ALTER TABLE " + identifier(table["name"]) + " ADD FOREIGN KEY("
                + identifier(key["column"]) + ") REFERENCES " + identifier(key["references_table"])
                + "(" + identifier(key["references_column"]) + ")"
            )
    if dialect == "postgresql":
        statements += [
            "REVOKE ALL ON SCHEMA public FROM PUBLIC",
            "GRANT USAGE ON SCHEMA public TO learner",
            "GRANT SELECT ON ALL TABLES IN SCHEMA public TO learner",
        ]
    return ";\n".join(statements) + ";\n"



def _start_sql_server(
    data, dataset, volume, name, image=None, authorize=None, *, writable=False, password=None,
):
    postgres = data["dialect"] == "postgresql"
    image = image or os.environ.get(
        "LEORNIAN_RUNNER_POSTGRES_IMAGE" if postgres else "LEORNIAN_RUNNER_MYSQL_IMAGE",
        "postgres:15" if postgres else "mysql:8.0",
    )
    script = (
        "initdb -D /tmp/data --auth-local=trust --auth-host=reject --no-locale --encoding=UTF8 "
        ">/tmp/init.log 2>&1; exec postgres -D /tmp/data -c listen_addresses='' "
        "-c unix_socket_directories=/socket -c unix_socket_permissions=0777 "
        "-c shared_buffers=16MB -c max_connections=8 -c max_worker_processes=0 -c jit=off"
        if postgres else
        "mysqld --no-defaults --initialize-insecure --datadir=/tmp/data "
        "--log-error=/tmp/init.log --innodb-buffer-pool-size=16M "
        "--innodb-log-file-size=8M; exec mysqld --no-defaults --datadir=/tmp/data "
        "--skip-networking --socket=/socket/mysql.sock --pid-file=/tmp/mysql.pid "
        "--innodb-buffer-pool-size=16M --innodb-log-file-size=8M "
        "--performance-schema=OFF --mysqlx=0 --local-infile=OFF --secure-file-priv=NULL"
    )
    if writable:
        password = password or secrets.token_hex(24)
        script = (
            script.replace("listen_addresses=''", "listen_addresses='127.0.0.1'")
            if postgres else script.replace("--skip-networking", "--bind-address=127.0.0.1")
        )
    command = _container_options(
        name, user="999:999", memory="256m" if postgres else "512m",
    ) + [
        "-d", "--mount", _mount(volume, "/socket"),
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m,uid=999,gid=999,mode=0700",
        image, "bash", "-ceu", script,
    ]
    _docker(*command[1:])
    deadline = time.monotonic() + 35
    probe = (
        ["pg_isready", "-h", "/socket", "-U", "postgres"] if postgres
        else ["mysqladmin", "--no-defaults", "--socket=/socket/mysql.sock", "-uroot", "ping"]
    )
    next_authorization = 0.0
    while True:
        if authorize and time.monotonic() >= next_authorization:
            if not authorize():
                raise RuntimeError("execution_authorization_changed")
            next_authorization = time.monotonic() + 2
        result = subprocess.run(
            ["docker", "exec", name, *probe], capture_output=True, timeout=4,
        )
        if result.returncode == 0:
            break
        if time.monotonic() >= deadline or _docker(
            "inspect", "--format", "{{.State.Running}}", name
        ) != "true":
            raise RuntimeError("SQL environment did not become ready.")
        time.sleep(.1)
    if postgres:
        _docker(
            "exec", "-i", name, "psql", "-X", "-h", "/socket", "-U", "postgres",
            "-v", "ON_ERROR_STOP=1", "-c", "CREATE ROLE learner LOGIN",
        )
        _docker(
            "exec", "-i", name, "createdb", "-h", "/socket", "-U", "postgres", "course",
        )
        setup_command = ["psql", "-X", "-h", "/socket", "-U", "postgres",
                         "-d", "course", "-v", "ON_ERROR_STOP=1"]
        setup = _sql_setup(data, dataset)
        if writable:
            setup += (
                f"ALTER ROLE learner PASSWORD '{password}';\n"
                "GRANT CREATE ON SCHEMA public TO learner;\n"
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO learner;\n"
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO learner;\n"
            )
            for table in data["schema_definition"]["tables"]:
                setup += f'ALTER TABLE "{table["name"]}" OWNER TO learner;\n'
    else:
        setup_command = [
            "mysql", "--no-defaults", "--socket=/socket/mysql.sock", "-uroot",
            "--binary-mode=1", "--default-character-set=utf8mb4",
        ]
        setup = (
            "CREATE DATABASE course CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin;\nUSE course;\n"
            + _sql_setup(data, dataset)
            + "CREATE USER 'learner'@'localhost' IDENTIFIED BY '"
            + (password if writable else "") + "';\n"
            + ("GRANT ALL PRIVILEGES" if writable else "GRANT SELECT")
            + " ON course.* TO 'learner'@'localhost';\n"
        )
        if writable:
            setup += (
                "ALTER USER 'root'@'localhost' IDENTIFIED BY '"
                + secrets.token_hex(24) + "';\n"
            )
    _docker("exec", "-i", name, *setup_command, input_bytes=setup.encode())
    if writable and postgres:
        # Learner code may use its role, but cannot impersonate the setup superuser.
        _docker(
            "exec", "-i", name, "sh", "-ceu",
            "cat > /tmp/data/pg_hba.conf; pg_ctl -D /tmp/data reload",
            input_bytes=(
                b"local all postgres peer\nlocal course learner trust\nlocal all all reject\n"
                b"host course learner 127.0.0.1/32 scram-sha-256\n"
                b"host all all all reject\n"
            ),
        )



def execute_sql(program, release=None, authorize=None):
    from leornian.modules.execution.contracts import SqlProgram

    data = SqlProgram.model_validate(program).model_dump(mode="json")
    if data.get("environment_release_id") and (
        not release or release["id"] != data["environment_release_id"]
        or release["profile"] != data["profile"]
        or release["dialect"] != data["dialect"]
        or release["runtime_version"] != data["runtime_version"]
    ):
        return _unavailable_cases(len(data["datasets"]), "runner_environment_unavailable")
    client = (Path(__file__).resolve().parents[1] / "sql_client.py").read_text(encoding="utf-8")
    results = []
    for dataset in data["datasets"]:
        if authorize and not authorize():
            results.extend(_unavailable_cases(
                len(data["datasets"]) - len(results), "environment_authorization_changed",
            ))
            break
        volume = "leornian-sql-" + secrets.token_hex(10)
        server = volume + "-server"
        sqlite = data["dialect"] == "sqlite"
        if not sqlite:
            _new_volume(volume)
        try:
            if not sqlite:
                _stage_volume(volume, [], release["image_id"] if release else IMAGE)
                _start_sql_server(
                    data, dataset, volume, server,
                    release["image_ids"]["server"] if release else None,
                    authorize,
                )
            name = volume + "-client"
            command = _container_options(name)
            if not sqlite:
                command += ["--mount", _mount(volume, "/socket", readonly=True)]
            image = release["image_id"] if release else IMAGE if sqlite else os.environ.get(
                "LEORNIAN_RUNNER_SQL_CLIENT_IMAGE", "leornian-sql-client:dev"
            )
            command += ["-i", image, "python", "-I", "-B", "-c", client]
            result = _bounded_container(
                command, json.dumps({
                    "dialect": data["dialect"], "query": data["query"],
                    "runtime_version": data["runtime_version"],
                    "schema_definition": data["schema_definition"], "dataset": dataset,
                }).encode(), name, 7, authorize,
            )
            if result["exit_code"] == 70:
                result["outcome"] = "infrastructure_error"
            results.append(result)
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            if isinstance(error, CleanupError):
                raise
            results.append({
                "exit_code": None, "stdout": "", "stderr": str(error)[:1000],
                "outcome": "infrastructure_error",
            })
        finally:
            if not sqlite:
                _remove_container(server)
                _remove_volume(volume)
    return results



def verify_sql_environment(images, dialect, version, authorize=None):
    result = execute_sql({
        "profile": "sql-query.v1", "dialect": dialect, "runtime_version": version,
        "environment_release_id": "00000000-0000-0000-0000-000000000001",
        "query": "SELECT id FROM records",
        "schema_definition": {"tables": [{
            "name": "records", "columns": [{"name": "id", "type": "integer"}],
        }]},
        "datasets": [{"rows": {"records": [[5]]}}],
    }, {
        "id": "00000000-0000-0000-0000-000000000001",
        "profile": "sql-query.v1", "dialect": dialect, "runtime_version": version,
        "image_id": images["runtime"], "image_ids": images,
    }, authorize)[0]
    if (
        result["outcome"] != "completed" or result["exit_code"] != 0
        or json.loads(result["stdout"])["rows"] != [["5"]]
    ):
        raise RuntimeError("The isolated SQL engine did not pass its actual query smoke check.")

