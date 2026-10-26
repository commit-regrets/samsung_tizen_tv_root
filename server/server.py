"""Port-80 server + interactive TV shell + physmap-RPC gateway.

* port 80        : HTTP (serves the exploit page), the reverse-shell callback,
                   and the physmap RPC stub (identified by the "PGDB" hello).
* 127.0.0.1:9999 : local control channel; anything typed here is forwarded to
                   the TV shell, and everything the TV prints comes back + goes to
                   shell.log
* 127.0.0.1:9998 : RPC gateway.  A local client connects here and is bridged
                   byte-for-byte to a TV connection that sent "PGDB".

The TV shell (from the browser exploit) runs as uid=5001(owner) and persists as
long as this server keeps the socket open.
"""
import hashlib
import os
import queue
import re
import socket
import struct
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# All runtime output lives under logs/ so the toolkit directory stays readable:
#   logs/server.out, logs/server.err   launcher redirects (root.ps1)
#   logs/shell.log[.1]                 rolling shell/TV console capture
#   logs/beacons.log                   one timestamped line per DSHROOT beacon
#   logs/tv/                           pages POST /save dumps (pruned)
LOGS = ROOT / "logs"
LOGS_TV = LOGS / "tv"
LOGS.mkdir(exist_ok=True)
LOGS_TV.mkdir(exist_ok=True)
LOG = LOGS / "shell.log"
BEACON_LOG = LOGS / "beacons.log"
TV_KEEP = int(os.environ.get("TV_OUTPUT_KEEP", "100"))
CTRL_PORT = int(os.environ.get("CTRL_PORT", "9999"))
RPC_PORT = int(os.environ.get("RPC_PORT", "9998"))
HTTP_PORT = int(os.environ.get("HTTP_PORT", "80"))
HTTP_BIND = os.environ.get("HTTP_BIND", "0.0.0.0")

TYPES = {".html": "text/html", ".js": "application/javascript",
         ".json": "application/json", ".bin": "application/octet-stream",
         ".sh": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8"}

# Never serve the server's own source or its logs on the LAN.
DENY_SUFFIX = {".py", ".log", ".out", ".err", ".db", ".pem", ".key", ".journal"}
DENY_NAMES = {"shell.log", "server.out", "server.err"}
LOG_MAX = 8 * 1024 * 1024
MAX_BODY = 1024 * 1024       # POST /save: enough for a page dump, not a disk fill
OUTPUT_MAX = 1024 * 1024     # rolling TV output kept for shell clients
BEACON_MAX = 4096            # one DSHROOT line; nothing legitimate is longer
RPC_QUEUE_MAX = 8            # stale page loads must not pile up as open sockets

# Request line: METHOD SP target SP HTTP/x.y.  Anything that matches is HTTP and
# is answered as such; a reverse-shell connection is a raw stream that never
# starts with a request line, so it can no longer capture the shell slot.
REQ_LINE = re.compile(r"^([A-Z]{3,8})[ \t]+(\S+)[ \t]+HTTP/\d(?:\.\d)?$")
HTTP_METHODS = {"GET", "HEAD", "POST", "OPTIONS"}
IPV4 = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")

# Peers that have announced themselves as the TV (PGDB hello or a DSHROOT
# beacon).  The interactive reverse shell is only accepted from these: on a LAN
# port 80 anybody can open a TCP connection, and the old fallback gave the first
# stranger the operator's root-shell slot (found by review, 2026-10-26).
TV_PEERS = set()

state_lock = threading.Lock()
tv_sock = None
output = bytearray()          # everything the TV printed (rolling)
output_dropped = 0            # bytes trimmed off the front of `output`
rpc_queue = queue.Queue()     # TV connections that announced "PGDB"
rpc_lock = threading.Lock()
rpc_tv = None                 # live TV physmap-RPC socket
rpc_client = None             # local client currently attached
rpc_hello = b""               # 12-byte hello captured when the stub connected


def _drop_tv_socket():
    """Close and forget the current TV stub AND any stale local client.

    Caller must hold rpc_lock.  Clearing rpc_client matters as much as the TV
    socket: a killed client leaves its thread holding the slot, and every later
    client then gets "BUSY" - the same class of stall as a wedged stub.
    """
    global rpc_tv, rpc_hello, rpc_client, tv_sock
    conn, rpc_tv, rpc_hello = rpc_tv, None, b""
    if conn is None:
        # Nothing paired, so any rpc_client is a client still *waiting* for a stub.
        # Evicting it here would drop the stub it is about to receive - that race
        # is what killed a freshly-connected page during testing.  Leave it alone.
        print("[rpc] RSET: nothing paired, keeping the waiting client", flush=True)
        return
    client, rpc_client = rpc_client, None
    with state_lock:
        # If this stub had been turned into a shell (op5/op7), the 9999 bridge
        # must not keep a handle on the socket we are about to close.
        if tv_sock is conn:
            tv_sock = None
    try:
        conn.close()
    except OSError:
        pass
    print("[rpc] dropped the current TV stub (RSET)", flush=True)
    if client is not None:
        try:
            client.close()
        except OSError:
            pass
        print("[rpc] dropped the paired client (RSET)", flush=True)


def log(text: str):
    try:
        if LOG.exists() and LOG.stat().st_size > LOG_MAX:
            bak = LOG.with_name("shell.log.1")
            try:
                bak.unlink()
            except FileNotFoundError:
                pass
            LOG.rename(bak)
    except OSError:
        pass
    with LOG.open("a", encoding="utf-8", errors="replace") as fh:
        fh.write(text)


def _prune_tv_outputs():
    """Keep only the newest TV_KEEP /save dumps - the page can POST frequently."""
    if TV_KEEP <= 0:
        return
    try:
        files = sorted(LOGS_TV.glob("tv_output_*.txt"), key=lambda p: p.stat().st_mtime)
        for old in files[:-TV_KEEP]:
            old.unlink()
    except OSError:
        pass


def _append_output(chunk: bytes):
    """Append TV output to the rolling buffer, trimming it to OUTPUT_MAX.

    The trim is tracked in `output_dropped` so shell clients can still compute
    an absolute read position (a bare `output.clear()` used to leave their saved
    offset past the end and silently swallow everything that followed).
    """
    global output_dropped
    with state_lock:
        output.extend(chunk)
        excess = len(output) - OUTPUT_MAX
        if excess > 0:
            del output[:excess]
            output_dropped += excess


def _header(head: bytes, name: str) -> str:
    """Case-insensitive header lookup over the raw request head."""
    want = name.encode().lower() + b":"
    for line in head.split(b"\r\n")[1:]:
        if line.lower().startswith(want):
            return line.split(b":", 1)[1].strip().decode("latin-1")
    return ""


def _is_ipv4(host: str) -> bool:
    if not IPV4.match(host or ""):
        return False
    return all(0 <= int(part) <= 255 for part in host.split("."))


def deploy_script(host_header: str):
    """Render deploy.sh for the address the TV used to fetch it.

    The script ships as a template (`H=@HOST@`, `WANT=@WANT@`, `SIZE_WANT=@SIZE@`)
    and is completed at request time: the payload hash comes from the artifact
    actually served, so a stale copy can no longer gate the wrong build, and
    `H` is exactly the address the TV reached us on.  A non-IPv4 Host is refused
    instead of guessed: the allowlist compares peer IPs, so a hostname would lock
    the channel out (review finding H3, 2026-10-26).
    """
    host = (host_header or "").split(":")[0].strip()
    if not _is_ipv4(host):
        return None
    try:
        data = (ROOT / "payload.dll").read_bytes()
        text = (ROOT / "deploy.sh").read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"[http] deploy template unavailable: {exc}", flush=True)
        return None
    # Anchor on the assignment lines.  A global replace also rewrote the
    # template's own guard (`*@HOST@*|*@WANT@*)`) into `*http://<host>*`, which
    # matches every valid render, so NEED_RENDER fired on a correctly rendered
    # script and the first real deploy could never run (found on hardware,
    # 2026-10-26).
    text = re.sub(r"(?m)^H=@HOST@$", f"H=http://{host}", text, count=1)
    text = re.sub(r"(?m)^WANT=@WANT@$",
                  "WANT=" + hashlib.md5(data).hexdigest(), text, count=1)
    text = re.sub(r"(?m)^SIZE_WANT=@SIZE@$",
                  "SIZE_WANT=" + str(len(data)), text, count=1)
    if re.search(r"(?m)^(H=@HOST@|WANT=@WANT@|SIZE_WANT=@SIZE@)$", text):
        print("[http] deploy template markers not where expected", flush=True)
        return None
    return text.encode()


def _is_textish(chunk: bytes) -> bool:
    """True for shell/console output; False for 4 KB binary physmap pages."""
    if not chunk:
        return False
    sample = chunk[:4096]
    printable = sum(1 for b in sample if 32 <= b < 127 or b in (9, 10, 13))
    return printable * 10 >= len(sample) * 9


def _read_full_request(conn, first):
    """Read headers, then the body per Content-Length (needed for POST /save)."""
    data = first
    while b"\r\n\r\n" not in data:
        try:
            chunk = conn.recv(65536)
        except OSError:
            break
        if not chunk:
            break
        data += chunk
        if len(data) > 1_000_000:
            break
    head, _, body = data.partition(b"\r\n\r\n")
    clen = 0
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            try:
                clen = int(line.split(b":", 1)[1].strip())
            except ValueError:
                clen = 0
    if clen > MAX_BODY:
        # Refuse instead of growing logs/tv/ without bound (or eating the LAN's
        # bandwidth): the header cap alone left the body unlimited.
        raise ValueError(f"body too large ({clen} B > {MAX_BODY} B)")
    while len(body) < clen:
        try:
            chunk = conn.recv(min(65536, clen - len(body)))
        except OSError:
            break
        if not chunk:
            break
        body += chunk
    return head, body


def serve_http(conn, req):
    try:
        try:
            head, body = _read_full_request(conn, req)
        except ValueError as exc:
            conn.sendall(b"HTTP/1.1 413 Payload Too Large\r\n"
                         b"Content-Length: 0\r\nConnection: close\r\n\r\n")
            print(f"[http] rejected: {exc}", flush=True)
            return
        line = head.split(b"\r\n", 1)[0].decode("latin-1")
        parts = line.split()
        method = parts[0] if parts else "GET"
        path = (parts[1] if len(parts) > 1 else "/").split("?")[0]
        if len(parts) > 2 and parts[2].upper().startswith("HTTP/"):
            if method not in HTTP_METHODS:
                # Known HTTP method we do not serve: answer as HTTP.  It must not
                # fall through to the reverse-shell handler.
                conn.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n"
                             b"Allow: GET, HEAD, POST, OPTIONS\r\n"
                             b"Content-Length: 0\r\nConnection: close\r\n\r\n")
                print(f"[http] 405 {method} {path}", flush=True)
                return

        # --- log sink: pages POST their textarea here ---
        if method == "POST" and path == "/save":
            # A cross-origin <form>/fetch can POST here without reading the reply.
            # Browsers attach Origin to those; same-origin page sends its own host.
            origin = _header(head, "origin")
            if origin:
                host = _header(head, "host")
                if origin.rsplit("/", 1)[-1] != host:
                    conn.sendall(b"HTTP/1.1 403 Forbidden\r\n"
                                 b"Content-Length: 0\r\nConnection: close\r\n\r\n")
                    print(f"[save] refused cross-origin {origin!r}", flush=True)
                    return
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            out = LOGS_TV / f"tv_output_{stamp}.txt"
            out.write_bytes(body)
            _prune_tv_outputs()
            hdr = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
            conn.sendall(hdr)
            print(f"[save] {out.name} {len(body)}B", flush=True)
            return

        # --- deploy script: rendered per request, never a stale generated copy ---
        if path in ("/deploy.sh", "/deploy_local.sh"):
            body_out = deploy_script(_header(head, "host"))
            if body_out is None:
                msg = (b"serve this page by IPv4 address (the deploy script needs "
                       b"the PC address the TV used, and the allowlist compares IPs)\n")
                conn.sendall(b"HTTP/1.1 409 Conflict\r\nContent-Type: text/plain\r\n"
                             + f"Content-Length: {len(msg)}\r\n".encode()
                             + b"Connection: close\r\n\r\n" + msg)
                print("[http] deploy.sh refused: Host is not an IPv4 address",
                      flush=True)
                return
            hdr = (f"HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\n"
                   f"Content-Length: {len(body_out)}\r\nCache-Control: no-store\r\n"
                   f"Connection: close\r\n\r\n").encode()
            conn.sendall(hdr + body_out)
            print(f"[http] {path} {len(body_out)}B (rendered for host)", flush=True)
            return

        if path == "/":
            path = "/index.html"
        target = (ROOT / path.lstrip("/")).resolve()
        try:
            rel = target.relative_to(ROOT)    # reject ../ escapes, not a prefix test
        except ValueError:
            conn.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
            return
        if "logs" in rel.parts:               # never serve our own logs
            conn.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
            return
        if target.suffix.lower() in DENY_SUFFIX or target.name in DENY_NAMES:
            conn.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
            return
        if not target.is_file():
            conn.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
            return
        data = target.read_bytes()
        ctype = TYPES.get(target.suffix.lower(), "application/octet-stream")
        hdr = (f"HTTP/1.1 200 OK\r\nContent-Type: {ctype}\r\n"
               f"Content-Length: {len(data)}\r\nCache-Control: no-store\r\n"
               f"Connection: close\r\n\r\n").encode()
        conn.sendall(hdr + data)
        print(f"[http] {path} {len(data)}B", flush=True)
    except Exception as exc:
        print(f"[http] {exc}", flush=True)


def tv_reader(conn):
    global tv_sock
    while True:
        try:
            chunk = conn.recv(65536)
        except OSError:
            break
        if not chunk:
            break
        if len(chunk) <= 512 and _is_textish(chunk):
            _append_output(chunk)
            log(chunk.decode("latin-1", "replace"))
        print(f"[tv] {chunk[:200]!r}", flush=True)
    with state_lock:
        if tv_sock is conn:          # do not drop a newer shell's slot
            tv_sock = None
    print("[tv] shell closed", flush=True)


def handle_shell(conn):
    global tv_sock, output_dropped
    peer = _tcp_peer(conn)
    with state_lock:
        cur = tv_sock
        cur_peer = _tcp_peer(cur) if cur is not None else ""
        if cur is not None and cur_peer not in ("", peer):
            # Two TCP connects used to be enough to take the operator's shell
            # slot: send PGDB (any sender joins TV_PEERS), then open a silent
            # connection.  A different peer can no longer evict an attached
            # shell; the same TV may replace its own (page reload / new op5).
            print(f"[shell] refused {peer}: a shell from {cur_peer} is already "
                  f"attached", flush=True)
            try:
                conn.close()
            except OSError:
                pass
            return
        # Keep the absolute-position invariant _append_output maintains: a bare
        # clear left shell readers with a saved offset past the end and they
        # silently missed output until the buffer caught up.
        output_dropped += len(output)
        output.clear()
        tv_sock = conn
    print("[shell] reverse shell connected", flush=True)
    log(f"\n===== {datetime.now().isoformat(timespec='seconds')} shell open =====\n")
    threading.Thread(target=tv_reader, args=(conn,), daemon=True).start()


def _recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def rpc_tv_reader(conn):
    """Persistent reader for a TV RPC socket, forwards to the current client."""
    global rpc_tv, rpc_client
    while True:
        try:
            chunk = conn.recv(65536)
        except OSError:
            break
        if not chunk:
            break
        with rpc_lock:
            c = rpc_client
        if c is not None:
            try:
                c.sendall(chunk)
            except OSError:
                with rpc_lock:
                    if rpc_client is c:
                        rpc_client = None
        if _is_textish(chunk):
            _append_output(chunk)
            log(chunk.decode("latin-1", "replace"))
    with rpc_lock:
        if rpc_tv is conn:
            rpc_tv = None
    print("[rpc] TV RPC socket closed", flush=True)


def rpc_gateway_client(client):
    """Attach a local client to the live TV RPC stub (re-pairing supported).

    The client slot is CLAIMED under rpc_lock, then the lock is released before
    waiting for a stub.  Holding it across ``rpc_queue.get(1800)`` froze RSET,
    the TV forwarder and every later client for as long as nobody had opened
    the page yet - which is the normal flow (auto_root connects first).
    """
    global rpc_tv, rpc_client, rpc_hello, tv_sock

    with rpc_lock:
        if rpc_client is not None:
            try:
                client.sendall(b"BUSY")
            except OSError:
                pass
            client.close()
            return
        rpc_client = client           # reservation: one client at a time
        conn = rpc_tv
        first = conn is None
        old = None
        if not first:
            # A page reload leaves a newer stub in the queue.  Always prefer it
            # over the current one: an op-7 shell shares the stub socket and can
            # leave the stub deaf, and without this a single wedged stub blocks
            # every later attempt until the server is restarted.
            try:
                fresh = rpc_queue.get_nowait()
            except queue.Empty:
                fresh = None
            if fresh is not None:
                old, conn, rpc_tv, first = rpc_tv, fresh, fresh, True
                print("[rpc] fresh TV stub replaced the wedged one", flush=True)
            else:
                print("[rpc] client re-attached to live TV stub", flush=True)

    if old is not None:
        try:
            old.close()
        except OSError:
            pass

    if first and conn is None:
        print("[rpc] local client connected, waiting for TV", flush=True)
        try:
            conn = rpc_queue.get(timeout=1800)
        except queue.Empty:
            print("[rpc] no TV connection, closing client", flush=True)
            with rpc_lock:
                if rpc_client is client:
                    rpc_client = None
            client.close()
            return
        with rpc_lock:
            rpc_tv = conn
        print("[rpc] paired with TV physmap stub", flush=True)

    if first:
        # The queued stub may be fake, or a page that died between PGDB and its
        # hello.  The accept loop set a 10 s timeout on this socket; honour it
        # here so a stalled peer cannot park this thread with the client slot
        # claimed forever.
        try:
            conn.settimeout(10)
            hello = _recv_exact(conn, 12)
        except OSError:
            hello = None
        if hello is None:
            print("[rpc] TV closed (or stalled) before hello", flush=True)
            with rpc_lock:
                if rpc_tv is conn:
                    rpc_tv = None
                if rpc_client is client:
                    rpc_client = None
            try:
                client.close()
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass
            return
        rpc_hello = hello
        m, pr, op = hello[:4], int.from_bytes(hello[4:8], "little", signed=True), \
            int.from_bytes(hello[8:12], "little", signed=True)
        print(f"[rpc] hello {m!r} prctl_ret={pr} open_ret={op}", flush=True)
        # From here reads are blocking: a stub idles between commands and must
        # not be dropped for being quiet.
        conn.settimeout(None)
        threading.Thread(target=rpc_tv_reader, args=(conn,), daemon=True).start()
    else:
        hello = rpc_hello

    try:
        client.sendall(hello)
        header = b""
        while True:
            data = client.recv(65536)
            if not data:
                break
            if len(header) < 4:
                header += data[:4 - len(header)]
                if len(header) == 4 and struct.unpack("<I", header)[0] in (5, 7):
                    # op5 EXEC / op7 RUN turn the stub into a shell.  Only now
                    # may the 9999 bridge aim at it: during ordinary RPC, stray
                    # keystrokes would be parsed as the next 16-byte header and
                    # desync the in-flight operation.
                    with state_lock:
                        tv_sock = conn
            conn.sendall(data)
    except OSError:
        pass
    with rpc_lock:
        if rpc_client is client:
            rpc_client = None
    print("[rpc] client detached (TV kept open for re-attach)", flush=True)

def control_client(client):
    def to_tv():
        while True:
            try:
                data = client.recv(4096)
            except OSError:
                break
            if not data:
                break
            with state_lock:
                s = tv_sock
            if s:
                try:
                    s.sendall(data)
                except OSError:
                    break

    def from_tv():
        # Track an ABSOLUTE stream position (output_dropped + index): trimming or
        # clearing the rolling buffer must not make a client miss later output.
        with state_lock:
            pos = output_dropped + len(output)
        while True:
            with state_lock:
                start = max(0, pos - output_dropped)
                new = bytes(output[start:])
                pos = output_dropped + len(output)
            if new:
                try:
                    client.sendall(new)
                except OSError:
                    break
            else:
                time.sleep(0.05)

    threading.Thread(target=to_tv, daemon=True).start()
    from_tv()


def safe_accept(srv, label):
    """accept() that survives transient errors instead of ending the thread.

    A bare `srv.accept()` in the main thread is fatal: any OSError there ends
    http_server(), which ends the process with no traceback in our logs (the
    console that would have shown it is not attached when run from Task
    Scheduler).  Retry with a small backoff and log the reason.
    """
    while True:
        try:
            return srv.accept()
        except Exception:
            print(f"[{label}] accept failed, retrying:", flush=True)
            traceback.print_exc()
            time.sleep(0.2)


def control_server():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", CTRL_PORT))
    srv.listen(8)
    print(f"[ctrl] listening on 127.0.0.1:{CTRL_PORT}", flush=True)
    while True:
        c, _ = safe_accept(srv, 'ctrl')
        threading.Thread(target=control_client, args=(c,), daemon=True).start()


def rpc_server():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", RPC_PORT))
    srv.listen(8)
    print(f"[rpc] gateway listening on 127.0.0.1:{RPC_PORT}", flush=True)
    while True:
        c, _ = safe_accept(srv, 'rpc')
        # A client may start with "RSET" to drop a wedged/stale TV pairing.
        # Without this the only cure was restarting the whole server, because a
        # stub that was consumed by op 5/op 7 (or half-dead after a power cycle)
        # stays as rpc_tv and answers every later client with a cached hello.
        # RSET is sent immediately after connect, but TCP may deliver "RSE"
        # first: one peek then sent the client into the 30-minute BUSY wait, in
        # exactly the wedged-stub case RSET exists for (review 2026-10-26).  Peek
        # until four bytes arrive or the prefix stops matching.
        c.settimeout(0.5)
        head = b""
        try:
            deadline = time.time() + 0.5
            while len(head) < 4:
                try:
                    head = c.recv(4, socket.MSG_PEEK)
                except socket.timeout:
                    break
                if not head or not b"RSET".startswith(head):
                    break
                left = deadline - time.time()
                if left <= 0:
                    break
                c.settimeout(left)
        except OSError:
            head = b""
        finally:
            c.settimeout(None)
        if head == b"RSET":
            try:
                c.recv(4)
            except OSError:
                pass
            with rpc_lock:
                dropped = rpc_tv is not None
                _drop_tv_socket()
            try:
                c.sendall(b"OK\n" if dropped else b"IDLE\n")
            except OSError:
                pass
            c.close()
            continue
        threading.Thread(target=rpc_gateway_client, args=(c,), daemon=True).start()


def _tcp_peer(conn):
    if conn is None:
        return ""
    try:
        return conn.getpeername()[0]
    except OSError:
        return ""


BEACON_LOG_MAX = 16 * 1024 * 1024


def _append_beacon_line(text: str):
    """Append one beacon line, rotating the log first (disk-fill guard).

    Any LAN peer can append a 4 KB DSHROOT line per connection, so an
    unrotated beacons.log was both a disk-fill vector and a way to bury (or
    forge) boot verdicts.  Rotation keeps at most ~32 MiB.
    """
    try:
        if BEACON_LOG.exists() and BEACON_LOG.stat().st_size > BEACON_LOG_MAX:
            bak = BEACON_LOG.with_name("beacons.log.1")
            try:
                bak.unlink()
            except FileNotFoundError:
                pass
            BEACON_LOG.rename(bak)
    except OSError:
        pass
    with BEACON_LOG.open("a", encoding="utf-8", errors="replace") as fh:
        fh.write(f"{datetime.now().isoformat(timespec='seconds')} {text}\n")


def _queue_stub(conn):
    """Hand a TV physmap stub to the gateway, dropping the oldest if full.

    Every page load opens a new stub connection; before this cap a reload loop
    (or a few tabs) left an unbounded queue of dead sockets, and the gateway
    could pair with one of them.
    """
    while rpc_queue.qsize() >= RPC_QUEUE_MAX:
        try:
            old = rpc_queue.get_nowait()
        except queue.Empty:
            break
        try:
            old.close()
        except OSError:
            pass
        print("[rpc] dropped the oldest queued stub (queue full)", flush=True)
    rpc_queue.put(conn)


def http_server():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HTTP_BIND, HTTP_PORT))
    srv.listen(32)
    print(f"[http] listening on {HTTP_BIND}:{HTTP_PORT}", flush=True)
    while True:
        conn, addr = safe_accept(srv, 'http')
        try:
            conn.settimeout(1.5)
            try:
                first = conn.recv(64, socket.MSG_PEEK)
            except socket.timeout:
                first = b""
            # Every branch below must be bounded.  Restoring None here (the v39
            # code) let a peer that sent "DSHROOT" or "GET " and then stalled
            # freeze the single accept thread - and with it the page, /deploy.sh,
            # /save, beacons and the shell slot (review P1, 2026-10-26).  2 s is
            # ample on a LAN; serve_http raises it to 10 s for the body.
            conn.settimeout(2.0)
            peer = addr[0] if addr else ""
            if first[:4] == b"PGDB":
                print("[rpc] TV physmap stub connected", flush=True)
                with state_lock:
                    TV_PEERS.add(peer)
                _queue_stub(conn)
                continue
            if first[:7] == b"DSHROOT":
                # app payload beacon: log it, but never let it take the shell slot
                try:
                    data = conn.recv(BEACON_MAX + 1)
                    with state_lock:
                        TV_PEERS.add(peer)
                    if len(data) > BEACON_MAX:
                        print(f"[beacon] oversized line from {peer} "
                              f"({len(data)}B) truncated", flush=True)
                        data = data[:BEACON_MAX]
                    print(f"[beacon] {data[:300]!r}", flush=True)
                    _append_beacon_line(data.decode("latin-1").strip())
                except OSError:
                    pass
                conn.close()
                continue
            token = first.split(b" ", 1)[0]
            looks_http = (b" " in first and token.isalpha()
                          and token.isupper() and 3 <= len(token) <= 8)
            if looks_http:
                req = b""
                try:
                    req = conn.recv(8192)
                except OSError:
                    pass
                conn.settimeout(10)          # never let one HTTP client hang the accept loop
                serve_http(conn, req)
                conn.close()
            else:
                # Raw peer: this is the reverse shell, which only the TV may own.
                # Without this check any LAN host that opens a TCP connection and
                # stays silent took the operator's root-shell slot (review
                # 2026-10-26; proven with a `PATCH /` request before the fix).
                with state_lock:
                    known = peer in TV_PEERS
                if not known:
                    print(f"[shell] refused {peer}: not a TV peer "
                          f"(send PGDB or a DSHROOT beacon first)", flush=True)
                    conn.close()
                else:
                    # The shell is silent by design and long-lived; its reader is
                    # a dedicated thread, so blocking reads there are correct.
                    conn.settimeout(None)
                    handle_shell(conn)   # keep open
        except Exception as exc:
            print(f"[http] {exc}", flush=True)


if __name__ == "__main__":
    print(f"[init] logs -> {LOGS}", flush=True)
    threading.Thread(target=control_server, daemon=True).start()
    threading.Thread(target=rpc_server, daemon=True).start()
    http_server()
