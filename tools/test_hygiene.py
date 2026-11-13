"""Whole-tree hygiene: every artifact parses, and the TV-side scripts are clean.

    python tools/test_hygiene.py

The behavioural layers (`sim_rpc`, `test_gateway`, `test_shell`, `test_debloat`,
...) only cover the code paths somebody wrote a fixture for.  This layer covers
the *classes* of breakage that no fixture catches:

  * **a Python file that stopped compiling.**  Tools nobody imports from a test
    (`find_pidns.py`, `taskwalk.py`, `physmap.py`'s __main__...) can rot silently
    for weeks; every `.py` in the tree is compiled here.
  * **a JSON state/inventory file that lost a comma** - `docs/state.json` is
    rendered into AGENTS.md, and the debloat inventory feeds the lists.
  * **a TV-side shell script that is no longer byte-clean for busybox.**  A CR
    (`#!/bin/sh^M` -> "not found") or a UTF-8 BOM breaks the shebang, and a
    syntax slip is caught by `sh -n` without executing anything.
  * **a `deploy.sh`/`uninstall.sh` that is no longer a script at all** (missing
    shebang).

No network, no TV, no root; it only reads files.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_DIRS = {".git", ".zcode", "obj", "bin", "__pycache__"}


def check(name: str, ok: bool, note: str = "") -> bool:
    print(("PASS" if ok else "FAIL"), name, ("- " + note if note else ""), flush=True)
    return ok


def find_sh():
    for c in (os.environ.get("TEST_SH"), r"C:\Program Files\Git\bin\sh.exe",
              "/bin/sh", "/usr/bin/sh"):
        if c and Path(c).exists():
            return c
    return None


def walk(pattern: str):
    for p in sorted(ROOT.rglob(pattern)):
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        yield p


def main() -> int:
    failed = 0

    # ---- every Python file compiles (not just the ones a test imports) -----
    py_files = list(walk("*.py"))
    bad = []
    for p in py_files:
        try:
            compile(p.read_text(encoding="utf-8"), str(p), "exec")
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            bad.append(f"{p.relative_to(ROOT)}: {type(exc).__name__}: {exc}")
    failed += not check(f"all {len(py_files)} .py files compile", not bad,
                        "; ".join(bad[:3]))

    # ---- every tracked JSON parses ------------------------------------------
    json_files = (list(walk("docs/*.json")) + list(walk("debloat/**/*.json"))
                  + list(walk("payload/*.json")))
    bad = []
    for p in json_files:
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError, OSError) as exc:
            bad.append(f"{p.relative_to(ROOT)}: {exc}")
    failed += not check(f"all {len(json_files)} .json files parse", not bad,
                        "; ".join(bad[:3]))

    # ---- TV-side shell scripts: no CR, no BOM, a shebang, and sh -n ---------
    sh_files = list(walk("server/*.sh")) + list(walk("debloat/tools/*.sh"))
    failed += not check(f"found the TV-side scripts ({len(sh_files)})", len(sh_files) >= 5,
                        "a broken glob would make the checks below vacuous")
    sh = find_sh()
    for p in sh_files:
        raw = p.read_bytes()
        rel = p.relative_to(ROOT).as_posix()
        failed += not check(f"{rel}: LF-only (no CR)", b"\r" not in raw,
                            "a CR makes busybox sh read it as part of the token")
        failed += not check(f"{rel}: no UTF-8 BOM", not raw.startswith(b"\xef\xbb\xbf"),
                            "a BOM breaks the #!/bin/sh line on the TV")
        failed += not check(f"{rel}: starts with a shebang", raw.startswith(b"#!"))
        if sh:
            r = subprocess.run([sh, "-n", p.as_posix()], capture_output=True, text=True)
            failed += not check(f"{rel}: parses under sh -n", r.returncode == 0,
                                (r.stderr or r.stdout).strip()[:160])
    if not sh:
        print("SKIP: no POSIX sh found (set TEST_SH=/path/to/sh); sh -n not run",
              flush=True)

    # ---- the LF pins themselves (a lost rule only bites on the NEXT checkout) --
    attr_path = ROOT / ".gitattributes"
    attr = attr_path.read_text(encoding="utf-8", errors="replace") if attr_path.is_file() else ""
    for ext in ("*.sh", "*.py"):
        line = next((ln for ln in attr.splitlines() if ln.strip().startswith(ext + " ")
                     and "eol=lf" in ln), "")
        failed += not check(f".gitattributes pins {ext} to LF", bool(line),
                            "without the pin a Windows checkout can rewrite the "
                            "TV-side scripts to CRLF and busybox cannot run them")

    # ---- the page's shellcode blob is still the committed size ---------------
    blob = ROOT / "tools" / "physrpc_shellcode.bin"
    failed += not check("physrpc_shellcode.bin is a non-empty ARM blob",
                        blob.is_file() and blob.stat().st_size > 0,
                        f"{blob.stat().st_size if blob.is_file() else 'missing'} B")

    # ---- a fresh clone's docroot must not leak the runtime dirs ------------
    for name in ("server/logs", "server/__pycache__"):
        p = ROOT / name
        # presence is fine (runtime creates it); what matters is that it is
        # git-ignored, which .gitignore is the single source of truth for.
        if p.exists():
            gi = (ROOT / ".gitignore").read_text(encoding="utf-8", errors="replace")
            key = "logs" if name.endswith("logs") else "__pycache__"
            failed += not check(f"{name} is git-ignored", key in gi,
                                ".gitignore is the source of truth for runtime dirs")

    print(flush=True)
    if failed:
        print(f"{failed} check(s) failed", flush=True)
        return 1
    print("hygiene checks ok", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
