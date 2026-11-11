#!/usr/bin/env python3
"""Build the Vulnerability Applicability Assessment (VAA) report from Trivy scans.

Inputs
  --scans DIR   Trivy JSON reports (`trivy image -f json`, optionally .json.gz), one per image.
  --vaa DIR     One TOML file per image with the image context and the assessment rules.

Every HIGH and CRITICAL finding of an assessed image must be covered by a rule; the
first matching rule (in file order) decides. `--check` fails on uncovered findings and
on rules that match nothing, so a rescan with new findings cannot silently pass.

Output: one Markdown document (VAA plus the scan summary as an appendix), suitable
for `pandoc` (see scripts/build-security-report.sh).
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import pathlib
import re
import sys
import tomllib

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
ASSESSED = ("CRITICAL", "HIGH")

VERDICTS = {
    "not_affected": "Not affected",
    "mitigated": "Affected, mitigated",
    "affected": "Affected, action needed",
    "under_investigation": "Under investigation",
}
# CISA/CSAF VEX justifications, required for "not_affected".
JUSTIFICATIONS = {
    "component_not_present": "Component not present",
    "vulnerable_code_not_present": "Vulnerable code not present",
    "vulnerable_code_not_in_execute_path": "Vulnerable code not in execute path",
    "vulnerable_code_cannot_be_controlled_by_adversary": "Vulnerable code cannot be controlled by adversary",
    "inline_mitigations_already_exist": "Inline mitigations already exist",
}


class ReportError(Exception):
    pass


def load_findings(path: pathlib.Path) -> dict:
    raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    data = json.loads(raw)
    findings, counts = [], collections.Counter()
    for result in data.get("Results") or []:
        for v in result.get("Vulnerabilities") or []:
            sev = v.get("Severity", "UNKNOWN")
            counts[sev] += 1
            if sev not in ASSESSED:
                continue
            findings.append(
                {
                    "id": v["VulnerabilityID"],
                    "severity": sev,
                    "pkg": v["PkgName"],
                    "installed": v.get("InstalledVersion", ""),
                    "fixed": v.get("FixedVersion", ""),
                    "class": result.get("Class", ""),
                    "target": result.get("Target", ""),
                    "pkgpath": v.get("PkgPath", ""),
                    "title": v.get("Title", ""),
                }
            )
    meta = data.get("Metadata") or {}
    digests = meta.get("RepoDigests") or []
    return {
        "file": path.name,
        "artifact": data.get("ArtifactName", ""),
        "created": data.get("CreatedAt", ""),
        "digest": digests[0] if digests else "",
        "os": " ".join(filter(None, [(meta.get("OS") or {}).get("Family"), (meta.get("OS") or {}).get("Name")])),
        "counts": counts,
        "findings": findings,
    }


def rule_matches(match: dict, f: dict) -> bool:
    if "ids" in match and f["id"] not in match["ids"]:
        return False
    if "pkgs" in match and f["pkg"] not in match["pkgs"]:
        return False
    if "class" in match and f["class"] != match["class"]:
        return False
    if "target" in match and not any(re.search(match["target"], s) for s in (f["target"], f["pkgpath"]) if s):
        return False
    return True


def validate_vaa(name: str, vaa: dict) -> None:
    for key in ("image", "scan", "exposure", "runtime"):
        if key not in vaa.get("context", {}):
            raise ReportError(f"{name}: context.{key} is missing")
    for rule in vaa.get("rule", []):
        rid = rule.get("id", "?")
        for key in ("id", "match", "verdict", "rationale"):
            if key not in rule:
                raise ReportError(f"{name}: rule {rid} has no {key}")
        if not rule["match"]:
            raise ReportError(f"{name}: rule {rid} has an empty match")
        if rule["verdict"] not in VERDICTS:
            raise ReportError(f"{name}: rule {rid} has unknown verdict {rule['verdict']!r}")
        if rule["verdict"] == "not_affected" and rule.get("justification") not in JUSTIFICATIONS:
            raise ReportError(f"{name}: rule {rid} is not_affected without a valid justification")
        if rule["verdict"] in ("affected", "mitigated", "under_investigation") and not rule.get("action"):
            raise ReportError(f"{name}: rule {rid} ({rule['verdict']}) needs an action")


def assess(scans_dir: pathlib.Path, vaa_dir: pathlib.Path) -> tuple[list, list]:
    images, problems = [], []
    for vaa_path in sorted(vaa_dir.glob("*.toml")):
        vaa = tomllib.loads(vaa_path.read_text())
        validate_vaa(vaa_path.name, vaa)
        scan_path = scans_dir / vaa["context"]["scan"]
        if not scan_path.exists():
            raise ReportError(f"{vaa_path.name}: scan {scan_path.name} not found")
        scan = load_findings(scan_path)
        rules = vaa.get("rule", [])
        used = collections.Counter()
        for f in scan["findings"]:
            rule = next((r for r in rules if rule_matches(r["match"], f)), None)
            if rule is None:
                problems.append(f"{vaa_path.stem}: {f['id']} ({f['pkg']} in {f['target']}) is not covered")
            else:
                f["rule"] = rule["id"]
                used[rule["id"]] += 1
        for r in rules:
            if not used[r["id"]]:
                problems.append(f"{vaa_path.stem}: rule {r['id']} matches no finding")
            r["count"] = used[r["id"]]
            r["critical"] = sum(1 for f in scan["findings"] if f.get("rule") == r["id"] and f["severity"] == "CRITICAL")
        images.append({"key": vaa_path.stem, "vaa": vaa, "scan": scan})
    return images, problems


def md_escape(text: str) -> str:
    return prose(text).replace("|", "\\|").replace("\n", " ")


def prose(text: str) -> str:
    """Keep <placeholders> literal (Markdown would read them as HTML tags)."""
    parts = re.split(r"(`[^`]*`)", str(text))
    return "".join(p if p.startswith("`") else p.replace("<", "\\<").replace(">", "\\>") for p in parts)


def brk(text: str, latex: bool) -> str:
    """Allow LaTeX to break long identifiers (package names, digests, paths)."""
    text = md_escape(text).replace("_", "\\_")
    if not latex:
        return text
    text = re.sub(r"([0-9a-f]{16})(?=[0-9a-f])", lambda m: m.group(1) + "\\allowbreak{}", text)
    return re.sub(r"([:./@-]|\\_)", lambda m: m.group(1) + "\\allowbreak{}", text)


SUMMARY_SEP = "|" + "|".join("-" * n for n in (26, 7, 7, 9, 9, 9, 11)) + "|"
FINDINGS_SEP = "|" + "|".join("-" * n for n in (15, 3, 24, 13, 13, 15, 11)) + "|"


def render(images: list, intro: str, latex: bool = False) -> str:
    out = [intro.rstrip(), ""]
    # Summary
    out += ["## Summary", "", "| Image | Critical | High | Not affected | Mitigated | Action needed | Under investigation |", SUMMARY_SEP]
    tot = collections.Counter()
    for im in images:
        c = im["scan"]["counts"]
        by = collections.Counter()
        for f in im["scan"]["findings"]:
            rule = next(r for r in im["vaa"]["rule"] if r["id"] == f["rule"])
            by[rule["verdict"]] += 1
        tot.update(by)
        tot["C"] += c["CRITICAL"]
        tot["H"] += c["HIGH"]
        out.append(f"| {im['vaa']['context']['image']} | {c['CRITICAL']} | {c['HIGH']} | {by['not_affected']} | {by['mitigated']} | {by['affected']} | {by['under_investigation']} |")
    out.append(f"| **Total** | **{tot['C']}** | **{tot['H']}** | **{tot['not_affected']}** | **{tot['mitigated']}** | **{tot['affected']}** | **{tot['under_investigation']}** |")
    out.append("")
    # Per image
    for im in images:
        ctx, scan = im["vaa"]["context"], im["scan"]
        out += [f"## {ctx['image']}", ""]
        out += [f"- **Digest:** {brk(scan['digest'] or scan['artifact'], latex)}", f"- **OS:** {scan['os'] or 'n/a'}", f"- **Scanned:** {scan['created'][:19]}"]
        out += [f"- **Exposure:** {prose(ctx['exposure'].strip())}", f"- **Runtime:** {prose(ctx['runtime'].strip())}"]
        if ctx.get("notes"):
            out.append(f"- **Notes:** {prose(ctx['notes'].strip())}")
        out.append("")
        if not scan["findings"]:
            out += ["No critical or high findings.", ""]
            continue
        out += ["### Assessment", ""]
        for r in im["vaa"]["rule"]:
            verdict = VERDICTS[r["verdict"]]
            if r["verdict"] == "not_affected":
                verdict += f" ({JUSTIFICATIONS[r['justification']]})"
            out += [f"#### {r['id']}: {r.get('title', '')}".rstrip(": "), ""]
            out += [f"- **Findings:** {r['count']} ({r['critical']} critical)", f"- **Verdict:** {verdict}"]
            out += [f"- **Rationale:** {prose(r['rationale'].strip())}"]
            for ev in r.get("evidence", []):
                out.append(f"    - Evidence: {prose(ev.strip())}")
            if r.get("action"):
                out.append(f"- **Action:** {prose(r['action'].strip())}")
            out.append("")
        out += ["### Findings", "", "| ID | Sev. | Package | Installed | Fixed in | Location | Rule |", FINDINGS_SEP]
        for f in sorted(scan["findings"], key=lambda x: (x["severity"] != "CRITICAL", x["rule"], x["pkg"], x["id"])):
            if f["class"] == "os-pkgs":
                loc = "OS package"
            else:  # file name only; the full path is in the scan and the rule rationale
                loc = (f["pkgpath"] or f["target"]).rstrip("/").rsplit("/", 1)[-1] or f["target"]
            out.append(f"| {brk(f['id'], latex)} | {f['severity'][0]} | {brk(f['pkg'], latex)} | {brk(f['installed'], latex)} | {brk(f['fixed'], latex)} | {brk(loc, latex)} | {f['rule']} |")
        out.append("")
    # Appendix: scan summary all severities
    out += ["## Appendix: Trivy scan summary", "", "| Image | Critical | High | Medium | Low | Total |", "|---|---|---|---|---|---|"]
    for im in images:
        c = im["scan"]["counts"]
        out.append(f"| {im['vaa']['context']['image']} | {c['CRITICAL']} | {c['HIGH']} | {c['MEDIUM']} | {c['LOW']} | {sum(c.values())} |")
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scans", type=pathlib.Path, required=True)
    ap.add_argument("--vaa", type=pathlib.Path, required=True)
    ap.add_argument("--intro", type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--check", action="store_true", help="only validate coverage")
    ap.add_argument("--latex", action="store_true", help="add line-break hints for the PDF (pandoc/LaTeX)")
    args = ap.parse_args(argv)
    try:
        images, problems = assess(args.scans, args.vaa)
    except ReportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for p in problems:
        print(f"error: {p}", file=sys.stderr)
    if problems:
        return 1
    if args.check:
        n = sum(len(im["scan"]["findings"]) for im in images)
        print(f"ok: {n} critical/high findings in {len(images)} images, all assessed")
        return 0
    intro = args.intro.read_text() if args.intro else "# Vulnerability Applicability Assessment\n"
    text = render(images, intro, latex=args.latex)
    if args.out:
        args.out.write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
