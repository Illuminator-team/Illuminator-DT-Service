"""The VAA generator must cover every critical/high finding and refuse incomplete assessments."""

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import security_report  # noqa: E402


def vuln(vid, sev, pkg, target="OS", cls="os-pkgs"):
    return cls, target, {"VulnerabilityID": vid, "Severity": sev, "PkgName": pkg,
                         "InstalledVersion": "1", "FixedVersion": "2", "Title": vid}


def scan(*vulns):
    results = {}
    for cls, target, v in vulns:
        results.setdefault((cls, target), []).append(v)
    return {
        "ArtifactName": "example@sha256:abc",
        "CreatedAt": "2026-11-11T10:00:00Z",
        "Metadata": {"RepoDigests": ["example@sha256:abc"], "OS": {"Family": "alpine", "Name": "3.22"}},
        "Results": [{"Class": c, "Target": t, "Vulnerabilities": vs} for (c, t), vs in results.items()],
    }


CONTEXT = """
[context]
image = "Example 1.0"
scan = "example.json"
exposure = "internal only"
runtime = "one process"
"""


class SecurityReportTest(unittest.TestCase):
    def run_report(self, scan_data, toml_text, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            (tmp / "scans").mkdir()
            (tmp / "vaa").mkdir()
            (tmp / "scans" / "example.json").write_text(json.dumps(scan_data))
            (tmp / "vaa" / "example.toml").write_text(toml_text)
            out = tmp / "out.md"
            code = security_report.main(["--scans", str(tmp / "scans"), "--vaa", str(tmp / "vaa"), "--out", str(out), *extra])
            return code, out.read_text() if out.exists() else ""

    def test_all_findings_covered_renders_report(self):
        data = scan(vuln("CVE-1", "CRITICAL", "curl"), vuln("CVE-2", "HIGH", "curl"), vuln("CVE-3", "MEDIUM", "zlib"))
        rules = CONTEXT + """
[[rule]]
id = "EX-01"
match = { pkgs = ["curl"] }
verdict = "not_affected"
justification = "vulnerable_code_not_in_execute_path"
rationale = "curl is never executed."
"""
        code, text = self.run_report(data, rules)
        self.assertEqual(code, 0)
        self.assertIn("| Example 1.0 | 1 | 1 | 2 | 0 | 0 | 0 |", text)
        self.assertIn("| CVE-1 | C | curl |", text)
        self.assertIn("Vulnerable code not in execute path", text)
        self.assertIn("| Example 1.0 | 1 | 1 | 1 | 0 | 3 |", text)  # appendix counts all severities

    def test_uncovered_finding_fails(self):
        data = scan(vuln("CVE-1", "HIGH", "curl"), vuln("CVE-2", "HIGH", "openssl"))
        rules = CONTEXT + """
[[rule]]
id = "EX-01"
match = { pkgs = ["curl"] }
verdict = "not_affected"
justification = "component_not_present"
rationale = "x"
"""
        code, _ = self.run_report(data, rules, "--check")
        self.assertEqual(code, 1)

    def test_rule_matching_nothing_fails(self):
        data = scan(vuln("CVE-1", "HIGH", "curl"))
        rules = CONTEXT + """
[[rule]]
id = "EX-01"
match = { pkgs = ["curl"] }
verdict = "not_affected"
justification = "component_not_present"
rationale = "x"

[[rule]]
id = "EX-02"
match = { pkgs = ["gone"] }
verdict = "not_affected"
justification = "component_not_present"
rationale = "x"
"""
        code, _ = self.run_report(data, rules, "--check")
        self.assertEqual(code, 1)

    def test_not_affected_needs_justification_and_affected_needs_action(self):
        data = scan(vuln("CVE-1", "HIGH", "curl"))
        for body in ('verdict = "not_affected"\nrationale = "x"', 'verdict = "mitigated"\nrationale = "x"'):
            with self.subTest(body=body):
                rules = CONTEXT + f'\n[[rule]]\nid = "EX-01"\nmatch = {{ pkgs = ["curl"] }}\n{body}\n'
                code, _ = self.run_report(data, rules, "--check")
                self.assertEqual(code, 2)

    def test_first_matching_rule_wins_and_target_regex(self):
        data = scan(
            vuln("CVE-1", "HIGH", "stdlib", "usr/bin/exporter", "lang-pkgs"),
            vuln("CVE-2", "HIGH", "stdlib", "usr/bin/server", "lang-pkgs"),
        )
        rules = CONTEXT + """
[[rule]]
id = "EX-01"
match = { pkgs = ["stdlib"], target = "exporter$" }
verdict = "not_affected"
justification = "vulnerable_code_not_in_execute_path"
rationale = "exporter is not started"

[[rule]]
id = "EX-02"
match = { pkgs = ["stdlib"] }
verdict = "mitigated"
rationale = "server is internal"
action = "update when the vendor ships a fix"
"""
        code, text = self.run_report(data, rules)
        self.assertEqual(code, 0)
        self.assertIn("| CVE-1 | H | stdlib | 1 | 2 | exporter | EX-01 |", text)
        self.assertIn("| CVE-2 | H | stdlib | 1 | 2 | server | EX-02 |", text)


class RepositoryAssessmentTest(unittest.TestCase):
    def test_committed_assessment_covers_the_newest_scan(self):
        scans = sorted((ROOT / "docs" / "security" / "scans").iterdir())[-1]
        code = security_report.main(["--scans", str(scans), "--vaa", str(ROOT / "docs" / "security" / "vaa"), "--check"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
