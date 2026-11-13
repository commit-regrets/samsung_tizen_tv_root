#!/usr/bin/env python3
"""Redact device/host identifiers from a copy of this repo, for a public release.

    python tools/sanitize_for_public.py <src_dir> <dst_dir>   # copy + redact
    python tools/sanitize_for_public.py --check [paths...]   # exit 1 if tokens found

Copy mode copies the files git tracks in <src_dir> to <dst_dir> (skipping logs
and build trees besides) and replaces the known private tokens with
placeholders, printing a per-token count so you can see what was actually
touched.  Untracked files are never copied (see _tracked).  Deliberately a
*copy*: the private repo is never modified in place, and binary files
(payload.dll, the shellcode blob) pass through untouched so their md5s stay
valid.

--check mode walks the given paths (default: this repo's tracked tree, including
ignored files like docs/codreview.md - hand-written notes are exactly what leaks)
and exits 1 if any private token is present.  Run it before publishing anything.

Ported from the research tree (recon/sanitize_for_public.py); the token list below
is this repo's seed.  Extend it when a new identifier enters the history - CHANGELOG
entries are the usual place (they record real addresses on purpose).

Review before publishing either way - this tool catches the known tokens only,
not identifiers you may have written in prose it has never seen.
"""
import shutil
import re
import subprocess
import sys
from pathlib import Path

# token -> placeholder.  Order matters (longest / most specific first).
SUBS = [
    # device identity
    ("<DUID>", "<DUID>"),
    ("<MODEL>", "<MODEL>"),
    ("<FIRMWARE_BUILD>", "<FIRMWARE_BUILD>"),
    ("<FIRMWARE>", "<FIRMWARE>"),
    ("<PLATFORM_INTERNAL>", "<PLATFORM_INTERNAL>"),
    # network: exact hosts first, then the remaining subnet prefixes
    ("<TV_IP>", "<TV_IP>"),
    ("<HOST_IP>", "<HOST_IP>"),
    ("<LAN>.", "<LAN>."),
    ("<VPN_GW>", "<VPN_GW>"),
    # trailing dot: "10.0.301" (the pinned SDK in payload/global.json) must not match
    ("<WIFI_SUBNET>.", "<WIFI_SUBNET>."),
    # operator home path (de-anonymization; found live on the public repo in
    # SMARTTHINGS-OFFLINE-2026-10-30.md and v42-design-brief.md, 2026-11-13).
    # The name is computed, never a literal: this file is itself copied and
    # redacted by itself, and an escaped literal would evade its own SUBS pass.
    ("C:\\Users\\" + Path.home().name, "<HOME>"),
]

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules",
             "server/logs", "logs", "payload/obj", "payload/out", "payload/bin",
             ".zcode"}
SKIP_SUFFIX = {".pyc", ".dll", ".exe"}

# Per-deploy 8-hex credentials the known-token list cannot anticipate.  Both
# the v41 beacon token (`tok=` in beacons/docs, `beacon_token` in state.json)
# and the v40 pairing token are generated at deploy time, so a list-only check
# would pass a tree that still carries the live one (found 2026-10-27).  The
# TOKEN_FILE= form is the deploy-transcript prose (`TOKEN_FILE=<BEACON_TOKEN>`) -
# the live v49.2 token shipped on the public repo in exactly that form on
# 2026-11-13 because only the tok=/JSON shapes were covered (P1, security
# audit).  All three are deploy-credential shapes; rotate, don't publish.
TOKEN_RES = (
    re.compile(r"\btok=([0-9a-f]{8})\b"),
    re.compile(r'("beacon_token"\s*:\s*")([0-9a-f]{8})(")'),
    re.compile(r"(?i)\btoken_file=([0-9a-f]{8})\b"),
)
# `tok=deadbeef` is the documented forged-token negative test, not a credential.
TOKEN_ALLOW = {"deadbeef"}

# The token list lives in this file and its fixtures, so --check would always
# flag itself.  Not skipped in copy mode (a public copy has no need for the
# real tokens either - they redact to placeholders like everything else).
SELF_FILES = {"tools/sanitize_for_public.py", "tools/test_sanitize.py"}


def _is_skipped(rel: Path) -> bool:
    parts = rel.parts
    if any(p in SKIP_DIRS for p in parts):
        return True
    joined = "/".join(parts)
    return any(joined == d or joined.startswith(d + "/") for d in SKIP_DIRS)


def _iter_files(base: Path):
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(base)
        if _is_skipped(rel):
            continue
        yield path, rel


def _tracked(src: Path):
    """The paths git tracks in src (posix), or None if src is not a worktree.

    Copy mode publishes TRACKED files only.  The working tree also holds
    gitignored artifacts that were never reviewed for release: build trees,
    runtime logs and the kernel RAM dumps under ghidra/ (~20 MB of live
    kernel memory) - the 2026-11-13 snapshot build copied all of them until
    this filter existed.  Nothing leaves the tree unless git tracks it.
    """
    try:
        out = subprocess.run(["git", "-C", str(src), "ls-files", "-z"],
                             capture_output=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    return {p.decode("utf-8", "surrogateescape") for p in out.split(b"\x00") if p}


def _read(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None  # binary (or unreadable): never rewrite


def _find(text: str):
    """[(token, count)] for one file, known tokens first, then live-shaped ones."""
    counts = {}
    for token, placeholder in SUBS:
        if token == placeholder:
            continue  # a public copy redacted its own SUBS list; placeholders
        n = text.count(token)  # are the expected state there, not a leak
        if n:
            counts[token] = n
    for rx in TOKEN_RES:
        for m in rx.finditer(text):
            value = m.group(2) if m.re is TOKEN_RES[1] else m.group(1)
            if value in TOKEN_ALLOW:
                continue
            if m.re is TOKEN_RES[0]:
                label = f"tok={value}"
            elif m.re is TOKEN_RES[1]:
                label = f'beacon_token:"{value}"'
            else:
                label = f"TOKEN_FILE={value}"
            counts[label] = counts.get(label, 0) + 1
    return list(counts.items())


def do_copy(src: Path, dst: Path) -> int:
    if not src.is_dir():
        print(f"not a directory: {src}")
        return 2
    if dst.exists():
        print(f"refusing to overwrite existing {dst}")
        return 2

    tracked = _tracked(src)
    if tracked is None:
        print("refusing to copy: source is not a git worktree "
              "(copy mode publishes tracked files only - see _tracked)")
        return 2

    counts = {token: 0 for token, _ in SUBS}
    copied = 0
    untracked = 0
    for path, rel in _iter_files(src):
        if rel.as_posix() not in tracked:
            untracked += 1
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        text = _read(path)
        if text is None:
            shutil.copy2(path, target)      # binary: pass through untouched
            copied += 1
            continue
        for token, placeholder in SUBS:
            n = text.count(token)
            if n:
                counts[token] += n
                text = text.replace(token, placeholder)
        # per-deploy credentials: same shape, unknown value
        text, n1 = re.subn(r"\btok=([0-9a-f]{8})\b",
                           lambda m: "tok=deadbeef"
                           if m.group(1) in TOKEN_ALLOW
                           else "tok=<BEACON_TOKEN>", text)
        text, n2 = re.subn(r'("beacon_token"\s*:\s*")([0-9a-f]{8})(")',
                           lambda m: m.group(0) if m.group(2) in TOKEN_ALLOW
                           else m.group(1) + "<BEACON_TOKEN>" + m.group(3), text)
        text, n3 = re.subn(r"(?i)\btoken_file=([0-9a-f]{8})\b",
                           lambda m: m.group(0) if m.group(1) in TOKEN_ALLOW
                           else "TOKEN_FILE=<BEACON_TOKEN>", text)
        if n1 or n2 or n3:
            counts["<BEACON_TOKEN>"] = counts.get("<BEACON_TOKEN>", 0) + n1 + n2 + n3
        target.write_text(text, encoding="utf-8", newline="")
        copied += 1

    print(f"copied {copied} tracked files -> {dst} "
          f"(skipped {untracked} untracked)\n")
    print("redactions:")
    for token, n in counts.items():
        flag = "" if n else "   (not found)"
        print(f"  {token:<40} {n:>4}{flag}")
    return 0


def do_check(paths) -> int:
    bad = 0
    for p in paths:
        base = Path(p).resolve()
        files = _iter_files(base) if base.is_dir() else [(base, Path(base.name))]
        for path, rel in files:
            if rel.as_posix() in SELF_FILES:
                continue
            text = _read(path)
            if text is None:
                continue
            for token, n in _find(text):
                print(f"  {token:<24} x{n:<4} {rel}")
                bad += n
    if bad:
        print(f"\nFAIL: {bad} private token occurrence(s). "
              f"Sanitize the copy before publishing "
              f"(or extend SUBS if this is a new identifier).")
        return 1
    print("OK: no private tokens found")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    here = Path(__file__).resolve().parent
    root = here.parent
    if argv and argv[0] == "--check":
        return do_check(argv[1:] or [root])
    if len(argv) != 2:
        print(__doc__)
        return 2
    return do_copy(Path(argv[0]).resolve(), Path(argv[1]).resolve())


if __name__ == "__main__":
    sys.exit(main())
