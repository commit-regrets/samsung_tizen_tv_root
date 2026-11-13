"""Run every test this repo has, in order, and summarise.

    python tools/test_all.py            # offline tests only
    python tools/test_all.py --tv       # also the live-stub protocol test
    python tools/test_all.py --tv --bad-run   # ... including the stub-killing case

Layers (see docs/TESTING.md):

  1. tools/sim_rpc.py        in-memory physmap RPC: cred layout, scan straddle
  2. tools/test_gateway.py   server.py gateway on scratch ports: RSET, pairing,
                             forwarding, BUSY, /save cap, rendered deploy.sh,
                             HTTP-method gate, TV-only shell slot, beacon-token
                             trim + persistence across a server restart
  2b. tools/test_server_unit.py  the same server in-process: the deny-path class
                             table (suffix/case/logs/__pycache__/traversal),
                             deploy render, token save+reload, best-effort log(),
                             the abandoned-waiter release, the absolute request
                             deadline
  2c. tools/test_wait_rooted.py  the launcher's post-deploy gate: a port probe is
                             not "payload active" (uid 0 required), the old
                             listener going away is reported, and root.ps1 uses it
  3. tools/test_shell.py     deploy.sh/uninstall.sh dry tests under sh with stubbed
                             chsmack/sqlite3/aulctl/curl/ls/mv, including rollback
  4. tools/test_constants.py the same offsets/limits across Program.cs, sim_rpc,
                             kernel_root, physmap, physrpc.S and deploy.sh
  5. build_physrpc.py --check-embedded + embed_physrpc.py --check
                             source == blob == page SHELLCODE
  6. tools/test_logs.py      beacon analyzer (fixtures + the on-TV marker file),
                             the self-diagnosing tool error paths, PowerShell parse
  7. tools/test_listwalk.py  layout-shift-proof list walk (sim) + the DWARF
                             fingerprint gate (needs pyelftools + the sim
                             vmlinux; skips without them)
  8. tools/test_docs.py      living docs vs current mechanisms (banned stale
                             claims, required tokens, artifact-number hygiene)
  4c. tools/test_debloat.py  debloat tooling: apply/restore/mask/unmask under
                             sh with stubs, list-argument contract, list
                             hygiene, merge determinism (details in
                             docs/TESTING.md)
  9. tools/test_stub.py      (--tv) live stub protocol + the new clamps
  10. tools/test_hygiene.py  every .py compiles, every tracked .json parses, and
                             every TV-side .sh is LF/BOM/shebang-clean and
                             parses under `sh -n`
  11. tools/test_tv_health.py  the post-boot health checker's comparisons: a
                             healthy fixture passes, every check has a
                             mutation that fails it, and read()/the registry
                             parser are exercised with injected outputs

Exit code 0 means every layer passed (or was skipped for a documented reason).
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def run(label, argv, *, timeout=300):
    print(f"\n=== {label} ===", flush=True)
    try:
        r = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT after {timeout}s: {' '.join(argv)}")
        return "fail"
    out = (r.stdout or "") + (r.stderr or "")
    print(out.rstrip(), flush=True)
    if r.returncode == 77:
        print(f"--- {label}: SKIP")
        return "skip"
    ok = r.returncode == 0
    print(f"--- {label}: {'ok' if ok else 'FAILED'} (exit {r.returncode})")
    return "ok" if ok else "fail"


def main() -> int:
    py = sys.executable
    results = []

    results.append(("sim_rpc", run("sim_rpc self-test", [py, "tools/sim_rpc.py"])))
    results.append(("gateway", run("gateway integration test", [py, "tools/test_gateway.py"])))
    results.append(("server-unit", run("server request gate + state unit checks",
                                       [py, "tools/test_server_unit.py"])))
    results.append(("wait-rooted", run("launcher post-deploy gate",
                                       [py, "tools/test_wait_rooted.py"])))
    results.append(("shell", run("deploy/uninstall dry tests", [py, "tools/test_shell.py"])))
    results.append(("constants", run("constant cross-check", [py, "tools/test_constants.py"])))
    results.append(("auto-root", run("auto_root fresh-stub retry loop",
                                     [py, "tools/test_auto_root.py"])))
    results.append(("logs-and-errors", run("beacon analyzer + tool error paths + ps1 parse",
                                           [py, "tools/test_logs.py"])))
    results.append(("sanitize", run("public-release sanitizer", [py, "tools/test_sanitize.py"])))
    results.append(("push-guard", run("pre-push push guard", [py, "tools/test_push_guard.py"])))
    results.append(("listwalk-dwarf", run("list-walk port + dwarf fingerprint",
                                          [py, "tools/test_listwalk.py"])))
    results.append(("state-docs", run("AGENTS.md payload row matches artifacts/state",
                                      [py, "tools/update_state.py", "--check"])))
    results.append(("debloat-tooling", run("debloat apply/mask tooling + lists + merge",
                                           [py, "tools/test_debloat.py"])))
    results.append(("tv-health", run("post-boot health checks vs the registry",
                                     [py, "tools/test_tv_health.py"])))
    results.append(("docs-consistency", run("living docs vs current mechanisms",
                                            [py, "tools/test_docs.py"])))
    results.append(("hygiene", run("whole-tree parse/encoding hygiene",
                                   [py, "tools/test_hygiene.py"])))

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
        # The debloat oracle needs the 31337 channel (not the browser stub), and
        # it is opt-in by ADDRESS so that a TV_IP already exported for the stub
        # layer cannot silently turn a stub-only run into 11 live checks (a
        # down channel or a registry mismatch would then fail the whole suite).
        tv_ip = None
        for i, a in enumerate(sys.argv):
            if a == "--tv-ip" and i + 1 < len(sys.argv):
                tv_ip = sys.argv[i + 1]
        if tv_ip:
            results.append(("tv-health-live", run(
                f"debloat health on {tv_ip}",
                [py, "tools/tv_health.py", "--tv", tv_ip])))
        else:
            results.append(("tv-health-live", "skip"))
            print("\n=== live debloat health ==="
                  "\nSKIP: pass --tv-ip <ip> to run the debloat checks")
    else:
        print("\n=== live stub ===\nSKIP: pass --tv to run it against a paired stub")

    print("\n=== summary ===")
    failed = [name for name, status in results if status == "fail"]
    skipped = [name for name, status in results if status == "skip"]
    for name, status in results:
        print(f"  {status.upper():5s} {name}")
    if skipped:
        print(f"\n{len(skipped)} layer(s) SKIPPED (not run - not a pass): "
              f"{', '.join(skipped)}")
    if failed:
        print(f"\n{len(failed)} layer(s) failed: {', '.join(failed)}")
        return 1
    if skipped:
        # A skip is not a pass, and the suite must not read as fully green when
        # it did not run something (2026-11-01 review).  Exit stays 0: the
        # skipped layers are environment-dependent by design.
        print(f"\nall selected tests passed, but {len(skipped)} layer(s) were "
              f"SKIPPED (not run): {', '.join(skipped)}")
        return 0
    print("\nall selected tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
