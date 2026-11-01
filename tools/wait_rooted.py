"""Wait for a DEPLOYED payload to answer 31337 as uid 0.

    python tools/wait_rooted.py --tv 192.0.2.1 [--timeout 180] [--drop-wait 30]

Why this exists: `deploy.sh` kills the running app with a *detached* kill, so the
OLD app's listener can answer a bare port probe for a moment - and the NEW payload
can then spend minutes in the attempt-1 stale window.  "Port open" is therefore
not "payload active" (2026-11-01: `root.ps1 -Force` printed "payload active"
while the payload was still hunting).  This helper only succeeds when the channel
actually answers `id -u` with 0, after the old listener has been seen to go.

Exit codes: 0 = rooted, 3 = rooted but the port never dropped (the previous DLL
may still be running - check the artifact md5), 1 = timeout, 2 = usage.
"""
from __future__ import annotations

import argparse
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = 31337
_UID_LINE = re.compile(r"(?m)^\s*(\d+)\s*$")


def port_open(tv: str, port: int = PORT, timeout: float = 1.5) -> bool:
    """True when something accepts a TCP connection on the TV's channel port."""
    try:
        s = socket.create_connection((tv, port), timeout=timeout)
    except OSError:
        return False
    try:
        s.close()
    except OSError:
        pass
    return True


def ask_uid(tv: str, *, run=subprocess.run, timeout: float = 20.0) -> str | None:
    """Send `id -u` over the channel; return the number, or None on any failure.

    `run` is injectable so the parser is testable without a TV.
    """
    try:
        p = run([sys.executable, str(HERE / "root_shell.py"), "id -u", tv],
                capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if getattr(p, "returncode", 1) != 0:
        return None
    m = _UID_LINE.search(p.stdout or "")
    return m.group(1) if m else None


# v46: deploy.sh's detached restart subshell writes RESTART_KILL=/RESTART_START=
# to /opt/usr/home/owner/share/restart.log instead of /dev/null.  Reading it
# back after a rooted answer surfaces a failed kill/start that used to vanish.
RESTART_LOG = "/opt/usr/home/owner/share/restart.log"


def read_restart_log(tv: str, *, run=subprocess.run, timeout: float = 20.0) -> str | None:
    """Fetch the deploy restart log over the channel; None on any failure.

    Best-effort by design: the file does not exist on pre-v46 deploys, on
    RESTART=skip deploys, and on stock installs, and a failed read must never
    turn a rooted answer into a failure.  root_shell.py exits 0 whenever the
    channel answered (even for a failed cat), so a missing file surfaces as the
    shell's error TEXT inside a successful reply - recognize it instead of
    printing it as if it were the log.
    """
    try:
        p = run([sys.executable, str(HERE / "root_shell.py"), f"cat {RESTART_LOG}", tv],
                capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if getattr(p, "returncode", 1) != 0:
        return None
    out = (p.stdout or "").strip()
    # root_shell.py prints the raw channel reply, terminated by __END__
    out = out.split("__END__", 1)[0].strip()
    if not out or "can't open" in out:
        return None
    return out


def wait_rooted(tv: str, *, timeout: float = 180.0, drop_wait: float = 30.0,
                probe=None, uid=None, clock=time.monotonic, sleep=time.sleep,
                log=None):
    """Return (ok, reason, dropped).

    Phase 1 waits (bounded by `drop_wait`) for the OLD listener to disappear -
    a port that is already closed counts.  Phase 2 (`timeout`) needs a listener
    that answers `id -u` = 0.  All I/O and the clock are injectable so this is
    testable offline.
    """
    probe = probe or port_open
    uid = uid or ask_uid
    log = log or (lambda _msg: None)

    dropped = not probe(tv)
    drop_deadline = clock() + drop_wait
    while not dropped and clock() < drop_deadline:
        sleep(0.5)
        dropped = not probe(tv)
    if not dropped:
        log("the old listener never dropped; still waiting for a rooted answer")

    deadline = clock() + timeout
    opened = False
    last_note = clock()
    while clock() < deadline:
        if probe(tv):
            if not opened:
                opened = True
                log("31337 is open; waiting for `id -u` = 0")
            if uid(tv) == "0":
                return True, "rooted", dropped
        if clock() - last_note >= 15.0:
            last_note = clock()
            log(f"still not rooted ({int(timeout - (deadline - clock()))}s)")
        sleep(2.0)
    return False, "timeout", dropped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tv", required=True, help="TV IPv4 address")
    ap.add_argument("--timeout", type=float, default=180.0,
                    help="seconds to wait for a rooted answer (default 180)")
    ap.add_argument("--drop-wait", type=float, default=30.0,
                    help="seconds to wait for the old listener to go (default 30)")
    ap.add_argument("--port", type=int, default=PORT, help="root channel port")
    args = ap.parse_args(argv)

    started = time.monotonic()
    ok, reason, dropped = wait_rooted(
        args.tv, timeout=args.timeout, drop_wait=args.drop_wait,
        probe=lambda tv: port_open(tv, args.port),
        log=lambda m: print(f"[wait] {m}", flush=True))
    waited = time.monotonic() - started
    if ok:
        print(f"[wait] rooted after {waited:.0f}s"
              + ("" if dropped else " (the old listener never dropped)"),
              flush=True)
        restart = read_restart_log(args.tv)
        if restart:
            print("[wait] deploy restart log:", flush=True)
            for ln in restart.splitlines():
                print(f"[wait]   {ln}", flush=True)
        return 0 if dropped else 3
    print(f"[wait] no rooted answer after {waited:.0f}s", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
