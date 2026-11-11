"""Database role for GeoServer.

GeoServer only reads the published layer tables, so it gets its own login role with
SELECT on exactly those tables. The publisher calls `ensure_reader_role` at start and
`grant_reader_select` after every publication, because a publication can (re)create a
table.
"""

from __future__ import annotations

from typing import Any, Iterable

from psycopg2 import sql

ROLE_ATTRIBUTES = "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"


def role_statements(role: str, password: str, database: str, exists: bool) -> list[sql.Composed]:
    """Create or reset the role. Re-applying the attributes keeps a hand-edited role read-only."""
    verb = "ALTER" if exists else "CREATE"
    return [
        sql.SQL("{} ROLE {} WITH " + ROLE_ATTRIBUTES + " PASSWORD {}").format(
            sql.SQL(verb), sql.Identifier(role), sql.Literal(password)
        ),
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), sql.Identifier(role)),
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)),
    ]


def select_statements(role: str, tables: Iterable[str]) -> list[sql.Composed]:
    return [
        sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(sql.Identifier("public", table), sql.Identifier(role))
        for table in sorted(set(tables))
    ]


def ensure_reader_role(cursor: Any, role: str, password: str, database: str) -> None:
    if not role or not password:
        raise ValueError("the GeoServer reader role and password must be set")
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    exists = cursor.fetchone() is not None
    for statement in role_statements(role, password, database, exists):
        cursor.execute(statement)


def grant_reader_select(cursor: Any, role: str, tables: Iterable[str]) -> list[str]:
    """Grant SELECT on the tables that exist; return the ones that do not exist yet."""
    tables = sorted(set(tables))
    cursor.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename = ANY(%s)",
        (tables,),
    )
    present = {row[0] for row in cursor.fetchall()}
    for statement in select_statements(role, [t for t in tables if t in present]):
        cursor.execute(statement)
    return [t for t in tables if t not in present]
