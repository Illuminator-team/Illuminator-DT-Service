"""GeoServer must read the layer tables with a separate read-only role."""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "layer-publisher"))

try:
    from psycopg2 import sql  # noqa: E402

    import reader_role  # noqa: E402
except ImportError:  # psycopg2 comes from layer-publisher/requirements.txt (installed in CI)
    sql = reader_role = None


class FakeCursor:  # noqa: D101
    def __init__(self, existing_roles=(), tables=()):
        self.existing_roles = set(existing_roles)
        self.tables = set(tables)
        self.executed = []
        self._rows = []

    def execute(self, statement, params=None):
        text = statement
        self.executed.append(text)
        if "FROM pg_roles" in text:
            self._rows = [(1,)] if params[0] in self.existing_roles else []
        elif "FROM pg_tables" in text:
            self._rows = [(t,) for t in params[0] if t in self.tables]

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


def render(statement):
    # psycopg2 needs a connection to quote literals; replace them by a marker for the test.
    if isinstance(statement, sql.Composed):
        parts = []
        for part in statement.seq:
            if isinstance(part, sql.Literal):
                parts.append("<literal>")
            elif isinstance(part, sql.Identifier):
                parts.append(".".join('"%s"' % s for s in part.strings))
            elif isinstance(part, sql.SQL):
                parts.append(part.string)
            else:
                parts.append(render(part))
        return "".join(parts)
    return str(statement)


@unittest.skipIf(sql is None, "psycopg2 is not installed")
class ReaderRoleTest(unittest.TestCase):
    def test_role_is_created_read_only(self):
        statements = [render(s) for s in reader_role.role_statements("geoserver_reader", "pw", "rdp_db", exists=False)]
        self.assertTrue(statements[0].startswith('CREATE ROLE "geoserver_reader" WITH LOGIN NOSUPERUSER'))
        for attribute in ("NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE", "NOINHERIT", "NOBYPASSRLS"):
            self.assertIn(attribute, statements[0])
        self.assertIn("PASSWORD <literal>", statements[0])
        self.assertEqual(statements[1], 'GRANT CONNECT ON DATABASE "rdp_db" TO "geoserver_reader"')
        self.assertEqual(statements[2], 'GRANT USAGE ON SCHEMA public TO "geoserver_reader"')

    def test_existing_role_is_reset_not_recreated(self):
        statements = [render(s) for s in reader_role.role_statements("r", "pw", "db", exists=True)]
        self.assertTrue(statements[0].startswith('ALTER ROLE "r" WITH LOGIN NOSUPERUSER'))

    def test_only_select_is_granted_and_only_on_existing_tables(self):
        cursor = FakeCursor(tables={"grid_lines", "pv_capacity"})
        cursor.execute = self._recording(cursor)
        missing = reader_role.grant_reader_select(cursor, "r", ["pv_capacity", "grid_lines", "not_yet"])
        self.assertEqual(missing, ["not_yet"])
        grants = [s for s in self.rendered if s.startswith("GRANT")]
        self.assertEqual(grants, [
            'GRANT SELECT ON TABLE "public"."grid_lines" TO "r"',
            'GRANT SELECT ON TABLE "public"."pv_capacity" TO "r"',
        ])
        self.assertFalse(any(re.search(r"INSERT|UPDATE|DELETE|ALL PRIVILEGES", s) for s in self.rendered))

    def test_empty_credentials_are_refused(self):
        with self.assertRaises(ValueError):
            reader_role.ensure_reader_role(FakeCursor(), "", "pw", "db")
        with self.assertRaises(ValueError):
            reader_role.ensure_reader_role(FakeCursor(), "r", "", "db")

    def _recording(self, cursor):
        self.rendered = []
        original = FakeCursor.execute

        def execute(statement, params=None):
            self.rendered.append(render(statement) if isinstance(statement, sql.Composable) else statement)
            return original(cursor, statement if not isinstance(statement, sql.Composable) else "", params)

        return execute


class PublisherWiringTest(unittest.TestCase):
    def setUp(self):
        self.main = (ROOT / "layer-publisher" / "main.py").read_text()
        self.compose = (ROOT / "docker-compose.yml").read_text()

    def test_datastore_uses_the_reader_credentials(self):
        body = self.main.split("def datastore_xml", 1)[1].split("def ", 1)[0]
        self.assertIn('"user": GEOSERVER_DB_USER', body)
        self.assertIn('"passwd": GEOSERVER_DB_PASSWORD', body)
        self.assertNotIn('DB_CONN["user"]', body)
        self.assertNotIn('DB_CONN["password"]', body)

    def test_reader_must_differ_from_the_publisher_user(self):
        self.assertIn('if GEOSERVER_DB_USER == DB_CONN["user"]', self.main)

    def test_role_and_wfs_are_ensured_before_publishing(self):
        run = self.main.split("def run()", 1)[1]
        order = [run.index(x) for x in ("ensure_geoserver_reader()", "grant_reader_tables()", "ensure_datastore()", "ensure_wfs_read_only()", "publish_pc6()")]
        self.assertEqual(order, sorted(order))
        loop = run.split("while True:", 1)[1]
        self.assertIn("grant_reader_tables()", loop)

    def test_compose_requires_reader_credentials(self):
        self.assertIn("GEOSERVER_DB_USER: ${GEOSERVER_DB_READER_USER:?", self.compose)
        self.assertIn("GEOSERVER_DB_PASSWORD: ${GEOSERVER_DB_READER_PASSWORD:?", self.compose)

    def test_image_ships_the_module(self):
        self.assertIn("reader_role.py", (ROOT / "layer-publisher" / "Dockerfile").read_text())


if __name__ == "__main__":
    unittest.main()
