"""Offline test for the pre-push push guard (tools/hooks/pre-push).

Covers:
  * the guard refuses a push to the public remote (github-work / repo name
    in the URL) - the 2026-11-13 incident class;
  * the guard allows other remotes through (exit 0);
  * the installed .git/hooks/pre-push is byte-identical to the checked-in
    tools/hooks/pre-push (the drift the hook's own header warns about);
  * the hook is LF-only (busybox-style sh on the TV aside, Windows CRLF in a
    sh hook breaks it).

Runs the hook directly with sh - no actual push happens.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK = HERE / "hooks" / "pre-push"

REFUSE_URLS = [
    "git@github-work:commit-regrets/samsung_tizen_tv_root.git",
    "https://github.com/commit-regrets/samsung_tizen_tv_root.git",
]
ALLOW_URLS = [
    "git@example.com:someone/other-repo.git",
]


def find_sh():
    for cand in (Path("C:/Program Files/Git/bin/sh.exe"),
                 Path("C:/Program Files (x86)/Git/bin/sh.exe"),
                 Path(__import__("os").environ.get("LOCALAPPDATA", ""))
                 / "Programs/Git/bin/sh.exe"):
        if cand.is_file():
            return str(cand)
    return "sh"


def run_hook(sh, url):
    return subprocess.run([sh, str(HOOK), "origin", url],
                          input=b"", capture_output=True, text=True)


def main() -> int:
    ok = True

    def check(name, cond, note=""):
        nonlocal ok
        print(("PASS" if cond else "FAIL"), name, ("- " + note if note else ""))
        ok = ok and cond

    sh = find_sh()
    try:
        subprocess.run([sh, "-c", "exit 0"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        print("SKIP: no working sh (install Git Bash)")
        return 77

    for url in REFUSE_URLS:
        r = run_hook(sh, url)
        check(f"refuses {url.split(':')[0]}", r.returncode == 1,
              r.stderr.strip().splitlines()[0] if r.stderr else "")

    for url in ALLOW_URLS:
        r = run_hook(sh, url)
        check(f"allows {url.split(':')[0]}", r.returncode == 0)

    installed = HERE.parent / ".git" / "hooks" / "pre-push"
    if installed.is_file():
        check("installed hook matches tracked copy",
              installed.read_bytes() == HOOK.read_bytes())
        # Windows has no exec bit; what matters for a POSIX clone is git's
        # index mode, and for this tree that the hook actually runs (proven
        # above by executing it).
        git_mode = subprocess.run(
            ["git", "ls-files", "-s", str(HOOK.relative_to(HERE.parent))],
            capture_output=True, text=True).stdout.split()
        check("tracked hook recorded executable (100755)",
              git_mode[:1] == ["100755"], " ".join(git_mode[:1]))
        check("hook is LF-only", b"\r" not in HOOK.read_bytes())
    else:
        check("hook installed in .git/hooks", False,
              "run: cp tools/hooks/pre-push .git/hooks/pre-push")

    print("\npush-guard selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
