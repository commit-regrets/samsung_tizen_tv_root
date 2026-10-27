"""Integration test for server/server.py's RPC gateway - no TV required.

    python tools/test_gateway.py

It starts the real server on scratch ports (HTTP/RPC/CTRL overridable via env),
then proves the behaviours the gateway promises:

  * a client that is still waiting for a stub does NOT hold the gateway lock:
    `RSET` answers promptly (this is the bug where rpc_queue.get(1800) ran
    inside rpc_lock and every later client hung behind it);
  * RSET with nothing paired answers IDLE and keeps the waiting client alive,
    so the stub that arrives next still finds its client;
  * a fake "PGDB" stub is paired to the waiting client, the 12-byte hello is
    forwarded verbatim, and bytes flow both ways;
  * a second client is told BUSY while the first is attached;
  * POST /save refuses a body above the cap with 413 (and writes nothing);
  * the v40 pairing token: POST /pair records it, a stub presenting a
    different word is refused, a matching one pairs and the client still
    sees the 12-byte hello.

The test only needs Python and a free loopback port.  It writes its server log
to server/logs/gateway-test.log (git-ignored through server/logs/).
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
SERVER_DIR = ROOT / "server"
LOG = SERVER_DIR / "logs" / "gateway-test.log"
HELLO = b"PGDB" + struct.pack("<ii", 0, 3)
# v40 stub wire: "PGDB" + pairing token (the server consumes these 8 bytes and
# token-checks them), then the 8 hello status bytes the gateway forwards to the
# client as a 12-byte hello.  STUB_GREET is what a fake stub puts on the wire.
STUB_TOK = b"\x7f\x1c\x3a\x99"
STUB_GREET = b"PGDB" + STUB_TOK + HELLO[4:]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def connect(port: int, timeout: float = 5.0) -> socket.socket:
    return socket.create_connection(("127.0.0.1", port), timeout=timeout)


def wait_for_log(marker: str, timeout: float = 10.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if marker in LOG.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            pass
        time.sleep(0.05)
    return False


def recv_exact(s: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise EOFError(f"closed after {len(buf)}/{n} bytes")
        buf += chunk
    return buf


def check(name: str, ok: bool, note: str = "") -> bool:
    print(("PASS" if ok else "FAIL"), name, ("- " + note if note else ""), flush=True)
    return ok


def http_exchange(port: int, raw: bytes, timeout: float = 5.0):
    """Send one raw request, read until close, return (status_line, headers, body)."""
    s = connect(port, timeout=timeout)
    try:
        s.sendall(raw)
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    finally:
        s.close()
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    return (lines[0] if lines else b""), head, body


def announce(port: int, hexstr: str) -> bool:
    """POST /pair like the page does; returns True on a 200."""
    status, _, _ = http_exchange(
        port, (f"POST /pair HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
               f"Content-Length: {len(hexstr)}\r\nConnection: close\r\n\r\n"
               + hexstr).encode())
    return b"200" in status


def get(port: int, path: str, host: str | None = None):
    host = host or f"127.0.0.1:{port}"
    return http_exchange(port, (f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
                                f"Connection: close\r\n\r\n").encode())


def main() -> int:
    http_port, rpc_port, ctrl_port = free_port(), free_port(), free_port()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("", encoding="utf-8")
    # Keep this test's fake beacons out of server/logs/beacons.log (the file the
    # operator reads): the server honours DSH_LOGS_DIR.
    scratch_logs = tempfile.mkdtemp(prefix="dsh_gw_logs_")
    prod_beacon = SERVER_DIR / "logs" / "beacons.log"
    prod_before = prod_beacon.stat().st_size if prod_beacon.exists() else 0
    env = dict(os.environ, HTTP_PORT=str(http_port), RPC_PORT=str(rpc_port),
               CTRL_PORT=str(ctrl_port), HTTP_BIND="127.0.0.1",
               DSH_LOGS_DIR=scratch_logs)
    log = LOG.open("a", encoding="utf-8")
    srv = subprocess.Popen([sys.executable, "server.py"], cwd=str(SERVER_DIR),
                           env=env, stdout=log, stderr=subprocess.STDOUT)
    failed = 0
    clients: list[socket.socket] = []
    try:
        if not wait_for_log(f"[rpc] gateway listening on 127.0.0.1:{rpc_port}"):
            print("[-] server did not start; see", LOG, flush=True)
            return 1

        # 0) deploy.sh is a TEMPLATE rendered per request from the payload that is
        #    actually served: no generated copy, no placeholder host (structural
        #    fix for the stale deploy_local.sh class).
        payload = (SERVER_DIR / "payload.dll").read_bytes()
        md5 = hashlib.md5(payload).hexdigest()
        status, _, body = get(http_port, "/deploy.sh")
        text = body.decode("latin-1")
        failed += not check(
            "GET /deploy.sh is rendered",
            b"200" in status and f"H=http://127.0.0.1" in text
            and f"WANT={md5}" in text and f"SIZE_WANT={len(payload)}" in text
            and "H=@HOST@" not in text and "WANT=@WANT@" not in text,
            status.decode("latin-1"))
        # The template's own guard must survive rendering: a global replace
        # rewrote it to *http://<host>*, which matched every valid render and
        # made the first hardware deploy refuse with NEED_RENDER (2026-10-26).
        failed += not check(
            "rendered deploy keeps its guard literal",
            "*@HOST@*|*@WANT@*|*@BEACON_TOKEN@*)" in text,
            "the renderer rewrote the guard pattern")
        hline = next((ln for ln in text.splitlines() if ln.startswith("H=")), "")
        failed += not check("rendered H cannot trip its own guard",
                            "@HOST@" not in hline and "@WANT@" not in hline)
        status, _, body = get(http_port, "/deploy.sh", host=f"localhost:{http_port}")
        failed += not check("deploy.sh refuses a non-IPv4 Host",
                            b"409" in status and b"@HOST@" not in body,
                            status.decode("latin-1"))

        # 1) any HTTP method must be answered as HTTP, never as the TV shell.
        status, _, _ = http_exchange(
            http_port, b"PATCH / HTTP/1.1\r\nHost: t\r\nContent-Length: 0\r\n\r\n")
        failed += not check("unknown HTTP method gets 405", b"405" in status,
                            status.decode("latin-1"))
        time.sleep(0.3)
        failed += not check("405 did not capture the shell slot",
                            not wait_for_log("reverse shell connected", timeout=0.2))

        # 2) a silent peer that has never announced itself as the TV is refused.
        t0 = time.time()
        stranger = connect(http_port)
        clients.append(stranger)
        try:
            closed = stranger.recv(1) == b""
        except OSError:
            closed = True
        failed += not check("silent non-TV peer refused", closed,
                            f"closed={closed} in {time.time() - t0:.1f}s")
        failed += not check("shell refusal logged",
                            wait_for_log("[shell] refused", timeout=3.0))

        # 2b) a stalled beacon sender must not hold the accept loop: the peeked
        # bytes make recv return at once, and the connection is closed after the
        # line.  The next request must not wait on it.
        stalled = connect(http_port)
        clients.append(stalled)
        stalled.sendall(b"DSHROOT t=1s start uid=5001")
        t0 = time.time()
        status, _, _ = get(http_port, "/index.html")
        failed += not check(
            "stalled beacon sender does not block the next request",
            b"200" in status and time.time() - t0 < 3.0,
            f"{time.time() - t0:.1f}s {status.decode('latin-1')}",
        )

        # 3) a client that arrives before the page does waits for a stub ...
        waiting = connect(rpc_port)
        clients.append(waiting)
        if not wait_for_log("[rpc] local client connected, waiting for TV"):
            print("[-] gateway never accepted the waiting client", flush=True)
            return 1
        time.sleep(0.2)

        # 2) ... and RSET must still answer promptly while it waits.
        t0 = time.time()
        reset = connect(rpc_port)
        clients.append(reset)
        reset.sendall(b"RSET")
        reply = reset.recv(16).decode("latin-1").strip()
        elapsed = time.time() - t0
        failed += not check(
            "RSET while a client waits",
            reply in ("OK", "IDLE") and elapsed < 1.0,
            f"reply={reply!r} in {elapsed * 1000:.0f} ms",
        )
        failed += not check("RSET keeps the waiting client", reply == "IDLE",
                            "nothing was paired yet")

        # 2c) RSET split across two TCP segments ("RSE" then "T") is still
        # recognised; one peek used to send it into the 30-minute BUSY wait.
        t0 = time.time()
        split = connect(rpc_port)
        clients.append(split)
        split.sendall(b"RSE")
        time.sleep(0.05)
        split.sendall(b"T")
        reply = split.recv(16).decode("latin-1").strip()
        failed += not check(
            "RSET split across segments",
            reply in ("OK", "IDLE") and time.time() - t0 < 2.0,
            f"reply={reply!r} in {time.time() - t0:.2f}s",
        )

        # 2e) v40 pairing token: the page announces a token (POST /pair) and the
        #     stub must present the same word as the 4 bytes after "PGDB".
        failed += not check("POST /pair announces a token",
                            announce(http_port, "aa55aa55"))
        wrong = connect(http_port)
        clients.append(wrong)
        wrong.sendall(b"PGDB" + b"\x11\x22\x33\x44" + HELLO[4:])
        t0 = time.time()
        try:
            closed = wrong.recv(1) == b""
        except OSError:
            closed = True
        failed += not check("stub with the wrong token is refused", closed,
                            f"closed={closed} in {time.time() - t0:.1f}s")
        failed += not check("token mismatch logged",
                            wait_for_log("stub token mismatch", timeout=3.0))

        # 3) the next stub pairs with that waiting client, hello intact.
        failed += not check("announce the matching token", announce(http_port, "7f1c3a99"))
        stub = connect(http_port)
        clients.append(stub)
        stub.sendall(STUB_GREET)
        got = recv_exact(waiting, len(HELLO))
        failed += not check("hello forwarded to the waiting client", got == HELLO,
                            got.hex())

        # 4) forwarding works in both directions.
        req = struct.pack("<IIII", 0, 0x20008000, 0, 8)
        waiting.sendall(req)
        failed += not check("client -> stub bytes", recv_exact(stub, len(req)) == req)
        stub.sendall(b"\x00\x00\x00\x00" + b"ABCDEFGH")
        failed += not check("stub -> client bytes",
                            recv_exact(waiting, 12) == b"\x00\x00\x00\x00ABCDEFGH")

        # 5) one client at a time: the second is told BUSY, not made to hang.
        t0 = time.time()
        second = connect(rpc_port)
        clients.append(second)
        busy = second.recv(16)
        failed += not check("second client gets BUSY", busy == b"BUSY",
                            f"{busy!r} in {time.time() - t0:.2f}s")

        # 6) POST /save body cap (M2): oversized body -> 413, no file written.
        tv_dir = SERVER_DIR / "logs" / "tv"
        before = len(list(tv_dir.glob("tv_output_*.txt"))) if tv_dir.is_dir() else 0
        post = connect(http_port)
        clients.append(post)
        body_len = 2 * 1024 * 1024
        post.sendall(b"POST /save HTTP/1.1\r\nHost: t\r\n"
                     b"Content-Length: " + str(body_len).encode() + b"\r\n\r\n")
        status = post.recv(64).split(b"\r\n", 1)[0]
        time.sleep(0.3)
        after = len(list(tv_dir.glob("tv_output_*.txt"))) if tv_dir.is_dir() else 0
        failed += not check("oversized POST /save rejected",
                            b"413" in status and after == before,
                            f"{status.decode('latin-1')} (files {before}->{after})")

        # 7) a peer that HAS announced itself (PGDB above came from 127.0.0.1) may
        #    still open the silent reverse shell: the TV-only gate must not lock
        #    the legitimate lane out.
        shell = connect(http_port)
        clients.append(shell)
        failed += not check("known TV peer may hold the shell slot",
                            wait_for_log("[shell] reverse shell connected", timeout=4.0))

        # 8) a DIFFERENT peer cannot evict the attached shell (two-connect attack:
        #    send PGDB/DSHROOT to join TV_PEERS, then open a silent connection).
        #    Uses the 127.0.0.2 loopback alias as a distinct source address.
        try:
            alias = socket.socket()
            alias.bind(("127.0.0.2", 0))
            alias.settimeout(3)
            alias.connect(("127.0.0.1", http_port))
            alias.sendall(b"DSHROOT t=1s start uid=5001\n")
            alias.close()
            intruder = socket.socket()
            intruder.bind(("127.0.0.2", 0))
            intruder.settimeout(3)
            intruder.connect(("127.0.0.1", http_port))
            clients.append(intruder)
            failed += not check(
                "a different peer cannot evict the attached shell",
                wait_for_log("[shell] refused 127.0.0.2", timeout=4.0))
        except OSError as exc:
            print(f"SKIP: loopback alias 127.0.0.2 unavailable ({exc})", flush=True)

        # 9) v41 beacon token: deploy.sh renders TOKEN=, the payload sends it as
        #    `tok=` in every beacon, and only a matching beacon joins TV_PEERS.
        #    A token-less beacon is still logged (the deploy window must not
        #    blind the boot diagnostics) but never admitted; a wrong token is
        #    refused outright.  Uses 127.0.0.3/4 loopback aliases.
        try:
            status, _, body = get(http_port, "/deploy.sh")
            m = re.search(r"(?m)^TOKEN=([0-9a-f]{8})$", body.decode("latin-1"))
            failed += not check("deploy.sh renders a beacon token", m is not None)
            btok = m.group(1) if m else "00000000"
            alias3 = socket.socket()
            alias3.bind(("127.0.0.3", 0))
            alias3.settimeout(3)
            alias3.connect(("127.0.0.1", http_port))
            alias3.sendall(b"DSHROOT tok=deadbeef t=5s start uid=5001 pid=999\n")
            alias3.close()
            failed += not check("wrong beacon token refused",
                                wait_for_log("unknown beacon token deadbeef",
                                             timeout=4.0))
            silent3 = socket.socket()
            silent3.bind(("127.0.0.3", 0))
            silent3.settimeout(3)
            silent3.connect(("127.0.0.1", http_port))
            clients.append(silent3)
            failed += not check(
                "a wrong-token beacon does not join TV_PEERS",
                wait_for_log("[shell] refused 127.0.0.3: not a TV peer",
                             timeout=4.0))
            alias4 = socket.socket()
            alias4.bind(("127.0.0.4", 0))
            alias4.settimeout(3)
            alias4.connect(("127.0.0.1", http_port))
            alias4.sendall(f"DSHROOT tok={btok} t=5s start uid=5001 pid=998\n".encode())
            alias4.close()
            silent4 = socket.socket()
            silent4.bind(("127.0.0.4", 0))
            silent4.settimeout(3)
            silent4.connect(("127.0.0.1", http_port))
            clients.append(silent4)
            failed += not check(
                "a valid beacon token admits the peer to the shell-slot gate",
                wait_for_log("[shell] refused 127.0.0.4: a shell from",
                             timeout=4.0))
            blines = Path(scratch_logs) / "beacons.log"
            got = blines.read_text(encoding="utf-8", errors="replace") if blines.exists() else ""
            failed += not check("valid beacon logged with its token verbatim",
                                f"tok={btok}" in got and "pid=998" in got)
        except OSError as exc:
            print(f"SKIP: loopback aliases 127.0.0.3/4 unavailable ({exc})",
                  flush=True)

        after = prod_beacon.stat().st_size if prod_beacon.exists() else 0
        failed += not check("gateway test kept the production beacon log clean",
                            after == prod_before, f"{prod_before} -> {after} bytes")
    finally:
        for c in clients:
            try:
                c.close()
            except OSError:
                pass
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except subprocess.TimeoutExpired:
            srv.kill()
        log.close()
        shutil.rmtree(scratch_logs, ignore_errors=True)

    print(flush=True)
    if failed:
        print(f"{failed} check(s) failed", flush=True)
        return 1
    print("gateway test ok", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
