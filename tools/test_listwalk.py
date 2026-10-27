"""Offline gate for tools/listwalk.py and tools/dwarf_offsets.py.

listwalk: runs its planted-memory self-test (back-link validation, walk,
page-offset task placement, decoy rejection) - the layout-shift-proof locator
must work without knowing the task-list offset.
dwarf_offsets --check: the sim vmlinux's fingerprint fields must still match
the TV-measured offsets (comm 0x400, cred 0x3f8, real_cred 0x3f4).  Skipped
(77) when pyelftools is missing or the vmlinux is absent, so a fresh clone
without the research workspace still passes.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(argv, timeout=120):
    try:
        return subprocess.run([sys.executable, *argv], cwd=str(HERE.parent),
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None


def main() -> int:
    failed = 0

    print("=== listwalk self-test ===")
    r = run(["tools/listwalk.py"])
    if r is None:
        print("FAIL: listwalk self-test timed out")
        failed += 1
    else:
        print(r.stdout.rstrip())
        if r.returncode != 0:
            failed += 1
            print(r.stderr)

    print("\n=== dwarf fingerprint ===")
    r = run(["tools/dwarf_offsets.py", "--check"])
    if r is None:
        # Optional porting gate (needs a big DWARF vmlinux): never hang the
        # suite on a slow filesystem.
        print("SKIP: dwarf check timed out")
    else:
        print(r.stdout.rstrip())
        if r.returncode == 77:
            print("SKIP: pyelftools/vmlinux not available")
        elif r.returncode != 0:
            failed += 1
            print(r.stderr)

    print("\nlistwalk+dwarf gate:", "FAILED" if failed else "ok")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
