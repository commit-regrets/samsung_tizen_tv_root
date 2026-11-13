"""Offline tests for `tools/wait_rooted.py` — no TV, all I/O injected.

Covers the 2026-11-01 failure it exists for: a deploy restart whose channel is
still hunting must NOT be reported as "payload active" (the old `root.ps1` check
was a bare TCP probe, and the dying old app could answer it).
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import wait_rooted as W  # noqa: E402


class FakeClock:
    """A clock whose `sleep` advances it, so the loops are bounded instantly."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class Script:
    """Returns `seq` one value per call; the last value repeats."""

    def __init__(self, seq) -> None:
        self.seq = list(seq)
        self.calls = 0

    def __call__(self, _tv):
        self.calls += 1
        return self.seq[min(self.calls - 1, len(self.seq) - 1)]


def check(name: str, ok: bool, note: str = "") -> bool:
    print(("PASS" if ok else "FAIL"), name, ("- " + note if note else ""), flush=True)
    return ok


def main() -> int:
    failed = 0

    # 1) the documented sequence: the old listener is gone, then a rooted answer
    c = FakeClock()
    ok, reason, dropped = W.wait_rooted(
        "192.0.2.1", probe=Script([False, False, True, True]),
        uid=Script(["0"]), clock=c, sleep=c.sleep)
    failed += not check("a closed port counts as the old listener gone",
                        ok and reason == "rooted" and dropped,
                        f"ok={ok} reason={reason} dropped={dropped}")

    # 2) the old listener never drops (kill failed / stale socket): a rooted
    #    answer still comes through, but the caller must be told
    c = FakeClock()
    ok, _reason, dropped = W.wait_rooted(
        "192.0.2.1", drop_wait=5, timeout=30, probe=Script([True]),
        uid=Script(["0"]), clock=c, sleep=c.sleep)
    failed += not check("a never-dropping listener yields ok but dropped=False",
                        ok and not dropped, f"ok={ok} dropped={dropped}")

    # 3) the 2026-11-01 shape: the port is open but the payload is still
    #    hunting (uid 5001) -> NOT accepted
    c = FakeClock()
    ok, reason, _dropped = W.wait_rooted(
        "192.0.2.1", timeout=10, probe=Script([False, True]),
        uid=Script(["5001"]), clock=c, sleep=c.sleep)
    failed += not check("a hunting payload (uid 5001) is not accepted",
                        not ok and reason == "timeout", f"ok={ok} reason={reason}")

    # 4) an unreadable answer (channel flapping) is retried, not trusted
    c = FakeClock()
    ok, reason, _dropped = W.wait_rooted(
        "192.0.2.1", timeout=30, probe=Script([False, True]),
        uid=Script([None, None, "0"]), clock=c, sleep=c.sleep)
    failed += not check("unreadable answers are retried, then rooted",
                        ok and reason == "rooted", f"ok={ok} reason={reason}")

    # 5) no listener at all: uid is never even asked
    c = FakeClock()
    uid = Script(["0"])
    ok, _reason, _dropped = W.wait_rooted(
        "192.0.2.1", timeout=10, probe=Script([False]), uid=uid,
        clock=c, sleep=c.sleep)
    failed += not check("no listener -> timeout without asking uid",
                        not ok and uid.calls == 0, f"ok={ok} calls={uid.calls}")

    # 6) the reply parser: only a numeric line is a uid
    class P:
        def __init__(self, out: str, rc: int = 0) -> None:
            self.stdout, self.returncode = out, rc

    failed += not check("ask_uid parses the reply",
                        W.ask_uid("x", run=lambda *a, **k: P("0\n__END__\n")) == "0")
    failed += not check("ask_uid keeps a non-root uid",
                        W.ask_uid("x", run=lambda *a, **k: P("5001\n__END__\n")) == "5001")
    failed += not check("ask_uid refuses a failed run",
                        W.ask_uid("x", run=lambda *a, **k: P("", 1)) is None)
    failed += not check("ask_uid refuses a non-numeric reply",
                        W.ask_uid("x", run=lambda *a, **k: P("busy\n")) is None)

    # 6b) the v46 restart-log read-back: deploy.sh's detached subshell writes
    #     RESTART_KILL=/RESTART_START= to $S/restart.log instead of /dev/null;
    #     wait_rooted reports it after a rooted answer, best-effort.
    def cat_run(argv, **_kw):
        class R:
            stdout = "RESTART_KILL=fail\nRESTART_START=fail\n__END__\n"
            returncode = 0
        assert argv[2].startswith("cat "), argv
        return R()

    failed += not check(
        "read_restart_log returns the log body without the __END__ terminator",
        W.read_restart_log("x", run=cat_run)
        == "RESTART_KILL=fail\nRESTART_START=fail",
    )

    def empty_run(argv, **_kw):
        # root_shell.py exits 0 once __END__ arrives; the shell's own error text
        # comes back as the reply body (this is what a pre-v46 deploy produces)
        class R:
            stdout = ("cat: can't open "
                      "'/opt/usr/home/owner/share/restart.log': No such file\n"
                      "__END__\n")
            returncode = 0
        return R()

    failed += not check("read_restart_log stays silent on a failed cat",
                        W.read_restart_log("x", run=empty_run) is None)
    failed += not check("read_restart_log stays silent on a crash",
                        W.read_restart_log(
                            "x", run=lambda *a, **k: (_ for _ in ()).throw(OSError("no"))) is None)

    # 7) the CLI contract: --tv is required (exit 2)
    import contextlib
    import io

    try:
        with contextlib.redirect_stderr(io.StringIO()):   # keep the usage text out
            W.main([])
        bad = False
    except SystemExit as exc:
        bad = exc.code == 2
    failed += not check("CLI without --tv exits 2", bad)

    # 8) the launcher must USE this helper instead of trusting a bare port probe
    ps1 = (ROOT / "root.ps1").read_text(encoding="utf-8", errors="replace")
    failed += not check("root.ps1 waits via tools/wait_rooted.py",
                        "wait_rooted.py" in ps1,
                        "a bare Test-TvPort probe accepted the dying old app's "
                        "listener as 'payload active' (2026-11-01)")
    failed += not check("root.ps1 no longer claims 'payload active' from a port probe",
                        "31337 is back; payload active." not in ps1)

    print(flush=True)
    if failed:
        print(f"{failed} check(s) failed", flush=True)
        return 1
    print("wait_rooted tests ok", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
