"""The Redis password must be required and stored literally in redis.conf."""
import os
import pathlib
import re
import subprocess
import tempfile
import shutil
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEXT = (ROOT / "docker-compose.yml").read_text()
# The redis service block ends at the next blank line followed by a comment/service.
BLOCK = re.search(r"^  redis:\n(.*?)(?=^\s*$)", TEXT, re.S | re.M).group(1)
REDIS_ENV = re.search(r"REDIS_PASSWORD: (.*)", BLOCK).group(1).strip()
_script = re.search(r"- \|\n((?:        .*\n|\s*\n)+)", BLOCK).group(1)
SCRIPT = "\n".join(line[8:] for line in _script.splitlines()).replace("$$", "$")


def parse_redis_quoted(text):
    """Read a double-quoted Redis config argument like Redis does for \\\\ and \\"."""
    assert text[0] == text[-1] == '"'
    out, i, body = [], 0, text[1:-1]
    while i < len(body):
        if body[i] == "\\":
            i += 1
        out.append(body[i])
        i += 1
    return "".join(out)


SH = shutil.which("sh")


class RedisPasswordTest(unittest.TestCase):
    def test_compose_requires_a_nonempty_password(self):
        self.assertRegex(REDIS_ENV, r"^\$\{REDIS_PASSWORD:\?.+\}$")

    def test_password_is_not_in_the_command_line(self):
        self.assertNotIn("command:", BLOCK)
        self.assertNotIn("--requirepass", BLOCK)

    def run_entrypoint(self, password):
        with tempfile.TemporaryDirectory() as tmp:
            conf = pathlib.Path(tmp) / "redis.conf"
            # Run only the part that writes the config: no chown, no exec.
            lines = [
                line for line in SCRIPT.splitlines()
                if not line.startswith(("chown", "exec"))
            ]
            # Send the script on stdin (not via -c) so no platform's argument
            # quoting can alter it, and write to a relative path in a temp cwd.
            script = "\n".join(lines).replace("/tmp/redis.conf", "redis.conf") + "\n"
            result = subprocess.run(
                [SH, "-s"], input=script.encode(), cwd=tmp,
                env={**os.environ, "REDIS_PASSWORD": password},
                capture_output=True,
            )
            result.stderr = result.stderr.decode(errors="replace")
            return result, conf.read_text() if conf.exists() else None

    @unittest.skipUnless(SH, "needs a POSIX shell (runs on the Linux CI runner)")
    def test_empty_password_stops_the_container(self):
        result, conf = self.run_entrypoint("")
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(conf)

    @unittest.skipUnless(SH, "needs a POSIX shell (runs on the Linux CI runner)")
    def test_line_breaks_are_rejected(self):
        for password in ("a\nb", "a\rb", "ab\n"):
            with self.subTest(password=password):
                result, conf = self.run_entrypoint(password)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(conf)

    @unittest.skipUnless(SH, "needs a POSIX shell (runs on the Linux CI runner)")
    def test_quotes_backslashes_and_spaces_are_stored_literally(self):
        for password in ('plain', 'qu"ote', 'back\\slash', '\\x41 \\" sp ace $HOME %s'):
            with self.subTest(password=password):
                result, conf = self.run_entrypoint(password)
                self.assertEqual(result.returncode, 0, result.stderr)
                match = re.fullmatch(r"requirepass (.*)\n", conf)
                self.assertIsNotNone(match)
                self.assertEqual(parse_redis_quoted(match.group(1)), password)


if __name__ == "__main__":
    unittest.main()
