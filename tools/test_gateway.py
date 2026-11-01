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
    sees the 12-byte hello;
  * an abandoned waiting client releases the client slot (it used to hold it
    for 30 minutes and answer every later tool with BUSY);
  * the v41 beacon-token set: a used token survives later renders, an unused
    one ages out, and the set survives a server restart - without that, a PC
    restart made the deployed payload's beacons unknown and they never reached
    beacons.log (the "AUL never launched the app" misread, 2026-11-01 review).

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
               DSH_LOGS_DIR=scratch_logs,
               # short so the trickle test below costs ~2 s, not 15
               HTTP_REQUEST_TIMEOUT="1")
    log = LOG.open("a", encoding="utf-8")
    srv = subprocess.Popen([sys.executable, "server.py"], cwd=str(SERVER_DIR),
                           env=env, stdout=log, stderr=subprocess.STDOUT)
    log2 = None          # the restarted server's stdout (set in step 11)
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

        # 0b) the server must not serve compiled copies of its own source.  A
        #     .pyc in __pycache__ is the same code; the suffix list lacked it and
        #     the path test only looked at "logs" (2026-10-31 review).
        cache = SERVER_DIR / "__pycache__"
        cache.mkdir(exist_ok=True)
        probe_pyc = cache / "dsh_probe_gateway.pyc"
        probe_pyc.write_bytes(b"compiled-source-fixture")
        try:
            status, _, body = get(http_port, "/__pycache__/dsh_probe_gateway.pyc")
            failed += not check(
                "__pycache__/.pyc is not served (compiled source)",
                b"404" in status and b"compiled-source-fixture" not in body,
                status.decode("latin-1"))
        finally:
            try:
                probe_pyc.unlink()
            except OSError:
                pass
        status, _, body = get(http_port, "/server.py")
        failed += not check("server.py itself is not served",
                            b"404" in status, status.decode("latin-1"))

        # 0c) one whole request must be bounded: a peer that trickles the header
        #     used to hold the single accept thread for as long as the 1 MB cap
        #     allowed (2026-10-31 review).  HTTP_REQUEST_TIMEOUT=1 for this run.
        slow = socket.create_connection(("127.0.0.1", http_port), timeout=5)
        try:
            slow.sendall(b"GET / HTTP/1.1\r\n")
            time.sleep(2.0)              # > the configured 1 s request budget
            slow.sendall(b"Host: x\r\n\r\n")
            slow.settimeout(5)
            try:
                got = slow.recv(4096)
            except socket.timeout:
                got = b"<timeout: the server did not close>"
            except OSError:
                # Windows reports the server's close as an abort, not EOF.
                got = b""
            failed += not check(
                "a trickled request is cut off at the absolute deadline",
                got == b"", f"recv={got[:80]!r}")
        finally:
            slow.close()

        # 0b) v42 policy files: served verbatim from the committed debloat lists
        #     (no generated copy that can go stale, same reasoning as deploy.sh).
        for path, src in (("/debloat-masks.txt", "services-units.txt"),
                          ("/debloat-kill.txt", "services-bind.txt")):
            want = (ROOT / "debloat" / "lists" / src).read_bytes()
            status, _, body = get(http_port, path)
            failed += not check(f"GET {path} serves the committed list",
                                b"200" in status and body == want,
                                f"{status.decode('latin-1')} {len(body)}B vs {len(want)}B")

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

        # 10) a client that vanished while waiting (Ctrl-C'd auto_root) must not
        #     hold the single client slot for 30 minutes: the waiter polls its
        #     socket and releases it.  RSET first drops the paired stub, so the
        #     next client really is a WAITER (no stub = no hello to re-attach to).
        rset = connect(rpc_port)
        clients.append(rset)
        rset.sendall(b"RSET")
        try:
            rset.recv(16)
        except OSError:
            pass
        time.sleep(0.3)
        gone = connect(rpc_port)
        time.sleep(0.3)                  # let it claim the slot
        gone.close()
        time.sleep(1.0)                  # > the 0.5 s waiter poll
        nxt = connect(rpc_port)
        clients.append(nxt)
        nxt.settimeout(1.5)
        try:
            busy = nxt.recv(16)
        except socket.timeout:
            busy = b""
        failed += not check(
            "an abandoned waiting client releases the RPC slot", busy == b"",
            f"got={busy!r} (BUSY = the dead waiter still owns the slot)")

        # 11) beacon tokens: a token that has admitted a beacon must survive
        #     later /deploy.sh renders (two stray GETs used to evict the live
        #     payload's token), an UNUSED render older than the last two must be
        #     evicted, and the whole set must survive a PC-server restart - the
        #     v41 set was in-memory only, so a restart silently locked the
        #     deployed payload out of beacons.log (the "AUL never launched"
        #     misread, 2026-11-01 review).
        def render_token() -> str:
            _, _, b = get(http_port, "/deploy.sh")
            mm = re.search(r"(?m)^TOKEN=([0-9a-f]{8})$", b.decode("latin-1"))
            return mm.group(1) if mm else ""

        def send_beacon(tok: str, pid: str) -> None:
            s = connect(http_port)
            try:
                s.sendall(f"DSHROOT tok={tok} t=5s start uid=5001 pid={pid}\n".encode())
                try:
                    s.recv(8)
                except OSError:
                    pass
            finally:
                s.close()

        def beacon_logged(pid: str) -> bool:
            time.sleep(0.4)
            try:
                txt = (Path(scratch_logs) / "beacons.log").read_text(
                    encoding="utf-8", errors="replace")
            except OSError:
                return False
            return f"pid={pid}" in txt

        t_live = render_token()
        failed += not check("a deploy render yields an 8-hex beacon token",
                            bool(t_live))
        send_beacon(t_live, "701")
        failed += not check("a beacon with the rendered token is accepted and logged",
                            beacon_logged("701"))
        t_stale = render_token()          # pushed out below, never used
        render_token()
        render_token()
        send_beacon(t_live, "702")
        failed += not check("a USED token survives later deploy renders",
                            beacon_logged("702"))
        send_beacon(t_stale, "703")
        failed += not check(
            "an UNUSED token older than the last two renders is refused",
            not beacon_logged("703"))

        # restart the PC server with the same scratch log dir (the TV's
        # rootchan.token still holds t_live - nothing else changes)
        marker = f"[rpc] gateway listening on 127.0.0.1:{rpc_port}"

        def marker_count() -> int:
            try:
                return LOG.read_text(encoding="utf-8",
                                     errors="replace").count(marker)
            except OSError:
                return 0

        # count, do not just grep: the FIRST server already printed this marker,
        # so a plain wait_for_log() would call a failed restart "ok"
        seen_before = marker_count()
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except subprocess.TimeoutExpired:
            srv.kill()
            srv.wait(timeout=5)
        log.close()
        log2 = LOG.open("a", encoding="utf-8")
        srv = subprocess.Popen([sys.executable, "server.py"], cwd=str(SERVER_DIR),
                               env=env, stdout=log2, stderr=subprocess.STDOUT)
        restarted = False
        end = time.time() + 10.0
        while time.time() < end:
            if marker_count() > seen_before:
                restarted = True
                break
            time.sleep(0.1)
        failed += not check("the server restarts on the same ports", restarted)
        if restarted:
            send_beacon(t_live, "704")
            failed += not check(
                "the live beacon token survives a PC-server restart",
                beacon_logged("704"))
            send_beacon(t_stale, "705")
            failed += not check(
                "... and the evicted token is still refused after the restart",
                not beacon_logged("705"))

        # A live TV beacon during the run is legitimate (the TV is on the LAN
        # and the production server is not always idle), so growth is allowed -
        # what must never appear is a line from THIS test: its own rendered
        # tokens, the unknown-token probe, or the pid=701..705 shapes.  Byte-
        # size equality turned a busy TV into a red suite once (2026-11-01).
        appended = ""
        if prod_beacon.exists() and prod_beacon.stat().st_size > prod_before:
            with prod_beacon.open("rb") as fh:
                fh.seek(prod_before)
                appended = fh.read().decode("utf-8", "replace")
        leaked = [t for t in (t_live, t_stale, "deadbeef") if t and t in appended]
        leaked += re.findall(r"pid=(70[1-5])\b", appended)
        failed += not check(
            "gateway test kept the production beacon log clean (no test-shaped lines)",
            not leaked,
            f"grew by {len(appended)} B; leaked test markers: {leaked[:5]}")
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
        if log2 is not None:
            log2.close()
        shutil.rmtree(scratch_logs, ignore_errors=True)

    print(flush=True)
    if failed:
        print(f"{failed} check(s) failed", flush=True)
        return 1
    print("gateway test ok", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
