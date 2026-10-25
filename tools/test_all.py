"""Run every test this repo has, in order, and summarise.

    python tools/test_all.py            # offline tests only
    python tools/test_all.py --tv       # also the live-stub protocol test
    python tools/test_all.py --tv --bad-run   # ... including the stub-killing case

Layers (see docs/TESTING.md):

  1. tools/sim_rpc.py        in-memory physmap RPC: cred layout, scan straddle
  2. tools/test_gateway.py   server.py gateway on scratch ports: RSET, pairing,
                             forwarding, BUSY, /save cap
  3. tools/test_shell.py     deploy.sh/uninstall.sh dry tests under sh with stubbed
                             chsmack/sqlite3/aulctl/curl/ls/login
  4. build_physrpc.py --check-embedded + embed_physrpc.py --check
                             source == blob == page SHELLCODE
  5. tools/test_stub.py      (--tv) live stub protocol + the new clamps

Exit code 0 means every layer passed (or was skipped for a documented reason).
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def run(label, argv, *, required=True, timeout=300):
    print(f"\n=== {label} ===", flush=True)
    try:
        r = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT after {timeout}s: {' '.join(argv)}")
        return False
    out = (r.stdout or "") + (r.stderr or "")
    print(out.rstrip(), flush=True)
    ok = r.returncode == 0
    print(f"--- {label}: {'ok' if ok else 'FAILED'} (exit {r.returncode})")
    return ok or not required


def main() -> int:
    py = sys.executable
    results = []

    results.append(("sim_rpc", run("sim_rpc self-test", [py, "tools/sim_rpc.py"])))
    results.append(("gateway", run("gateway integration test", [py, "tools/test_gateway.py"])))
    results.append(("shell", run("deploy/uninstall dry tests", [py, "tools/test_shell.py"])))
    results.append(("auto-root", run("auto_root fresh-stub retry loop",
                                     [py, "tools/test_auto_root.py"])))

    # requires keystone+capstone; report the skip instead of failing a fresh clone
    try:
        import keystone  # noqa: F401
        have_keystone = True
    except ImportError:
        have_keystone = False
    if have_keystone:
        results.append(("blob-vs-source", run(
            "physrpc.S vs embedded blob",
            [py, "tools/build_physrpc.py", "--check-embedded"])))
        results.append(("blob-vs-page", run(
            "physrpc_shellcode.bin vs page SHELLCODE",
            [py, "tools/embed_physrpc.py", "--check"])))
    else:
        print("\n=== physrpc checks ===\nSKIP: keystone not installed "
              "(pip install -r tools/requirements.txt)")

    if "--tv" in sys.argv:
        argv = [py, "tools/test_stub.py"]
        if "--bad-run" in sys.argv:
            argv.append("--bad-run")
        results.append(("stub-protocol", run("live stub protocol", argv)))
    else:
        print("\n=== live stub ===\nSKIP: pass --tv to run it against a paired stub")

    print("\n=== summary ===")
    failed = [name for name, ok in results if not ok]
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if failed:
        print(f"\n{len(failed)} layer(s) failed: {', '.join(failed)}")
        return 1
    print("\nall selected tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
