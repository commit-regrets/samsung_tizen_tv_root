#!/usr/bin/env python3
"""Docs-consistency gate: the docs must not drift behind the code.

Every check below is a past incident.  The sweep that produced this file found
the same stale-claim classes in three-plus files each: node-switching claims
predating the v39.1 EBUSY invariant, "update WANT=" instructions predating the
rendered deploy gate, `0.0.0.0` bind claims predating v16, "SDK 6+" predating
the global.json pin, and hand-copied artifact md5/sizes that go stale on every
rebuild.  Each is now a banned pattern; the current mechanisms are required
patterns.  Runs as a `test_all.py` layer - a doc edit that reintroduces a dead
claim fails the suite, exactly like a constant drift in `test_constants.py`.

Artifact numbers (md5, byte sizes) are single-sourced: they may appear only in
the generated STATE block of `AGENTS.md` (see `tools/update_state.py`), in the
dated-history files (CHANGELOG, archives, review history), and in the
`docs/OPEN-ISSUES.md` current-state header (a deliberate per-session snapshot
that is refreshed by hand at the start of every hardware session).  Living
prose points at the state row instead.

    python tools/test_docs.py            # check; exit 1 on drift
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LIVING = [
    "README.md", "AGENTS.md", "SECURITY.md", "NOTICE.md",
    "docs/USAGE.md", "docs/EXPLOIT.md", "docs/LOGGUIDE.md",
    "docs/ROOT-METHODS.md", "docs/TESTING.md", "docs/PORTABILITY.md",
    "docs/FAILED.md", "docs/SERVER-HOSTING.md", "docs/SCRIPT-REVIEW.md",
    "docs/BOOT-REGRESSION-SMACK.md", "docs/REFERENCE-MATERIALS.md",
    "docs/OPEN-ISSUES.md",
]
# dated history: narrative only, exempt from every check
EXEMPT = {"CHANGELOG.md", "docs/CHANGELOG-ARCHIVE.md", "docs/REVIEW-HISTORY.md"}
# state snapshot refreshed by hand each session: exempt from artifact hygiene only
STATE_SNAPSHOT = {"docs/OPEN-ISSUES.md"}

# (regex over backtick-stripped text, incident) - a reintroduction is a regression.
BANNED = [
    (r"[Uu]pdate ?WANT=",
     "'update WANT=' instruction: the deploy gate is rendered per request (v39)"),
    (r"update the deploy constants",
     "'update the deploy constants': there are no deploy constants any more (v39)"),
    (r"cycles (three nodes|video\d)",
     "node cycling: retry video40 on EBUSY, advance only on ENOENT/ENODEV "
     "(v39.1 invariant, review 2026-10-26)"),
    (r"binds ?0\.0\.0\.0:31337|Binding ?0\.0\.0\.0",
     "0.0.0.0 bind claim: the channel binds one route-derived address (v16)"),
    (r"\.NET SDK 6\+|SDK 6\+ only",
     "'SDK 6+': payload/global.json pins the SDK 10.0.x patch band"),
    (r"ARM32 LPAE",
     "'ARM32 LPAE': the kernel is VMSPLIT_3G + HIGHMEM, CONFIG_ARM_LPAE unset"),
]

# (substring over backtick-stripped text, files that must mention it) - the
# current mechanism must be documented; losing the section trips the gate.
REQUIRED = [
    ("0xF0400000", ["AGENTS.md", "docs/EXPLOIT.md", "docs/FAILED.md"]),
    ("tok=", ["docs/LOGGUIDE.md", "SECURITY.md", "docs/SERVER-HOSTING.md"]),
    ("rootchan.token", ["docs/USAGE.md", "docs/LOGGUIDE.md", "SECURITY.md"]),
    ("POST /pair", ["SECURITY.md", "docs/SERVER-HOSTING.md"]),
    ("ENOENT/ENODEV", ["README.md", "AGENTS.md"]),
    ("EBUSY", ["README.md"]),
    ('errors="replace"', ["docs/OPEN-ISSUES.md"]),
]

# artifact numbers are single-sourced (AGENTS STATE block / state.json / history)
ARTIFACT_PATTERNS = [
    (r"\b[0-9a-f]{32}\b", "full md5"),
    (r"\b[0-9a-f]{8}…", "short md5"),
    (r"\b33,[027]92 B\b|\b7,[67]92?0? B\b|\b7,600 B\b", "artifact byte size"),
]


def plain(text: str) -> str:
    """Backticks are markdown, not content: match with them stripped."""
    return text.replace("`", "")


def state_block(text: str) -> str:
    m = re.search(r"STATE:BEGIN.*?STATE:END", text, re.S)
    return m.group(0) if m else ""


def main() -> int:
    raw = {rel: (ROOT / rel).read_text(encoding="utf-8") for rel in LIVING}
    texts = {rel: plain(t) for rel, t in raw.items()}
    fails = 0

    for rel, text in texts.items():
        for pat, why in BANNED:
            hits = re.findall(pat, text)
            if hits:
                fails += 1
                print(f"FAIL {rel}: banned claim {hits[0]!r} - {why}")

    for needle, files in REQUIRED:
        for rel in files:
            if rel not in texts:
                print(f"FAIL required-list names {rel}, not in LIVING")
                fails += 1
                continue
            if needle not in texts[rel]:
                fails += 1
                print(f"FAIL {rel}: required token {needle!r} missing - the "
                      f"mechanism it documents must stay documented")

    for rel in texts:
        body = plain(raw[rel].replace(state_block(raw[rel]), "STATE"))
        if rel in STATE_SNAPSHOT:
            continue
        for pat, what in ARTIFACT_PATTERNS:
            for hit in sorted(set(re.findall(pat, body))):
                fails += 1
                print(f"FAIL {rel}: hand-copied artifact number {hit!r} ({what}) "
                      f"- point at the AGENTS.md state row instead (single source)")

    if fails:
        print(f"\ndocs-consistency: {fails} drift(s). Fix the docs, or - if a "
              f"check itself is outdated - update tools/test_docs.py with the "
              f"incident in the message.")
        return 1
    print("docs-consistency: ok "
          f"({len(BANNED)} banned, {sum(len(f) for _, f in REQUIRED)} required, "
          f"{len(ARTIFACT_PATTERNS)} artifact-hygiene checks over {len(LIVING)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
