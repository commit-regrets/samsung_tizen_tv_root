"""In-process checks on `server.py`'s request gate and its mutable state.

    python tools/test_server_unit.py

`tools/test_gateway.py` drives the real server over TCP; this layer imports
`server` directly (nothing binds: the listeners only start under `__main__`), so
the checks are deterministic and cheap.  It exists because the two common bug
classes behind the 2026-10-31/11-01 findings are not observable from the wire:

  * **the request gate must deny a whole CLASS of paths**, not just the one
    filename somebody remembered - every deny suffix/dir is exercised against a
    planted file, in mixed case, plus `..` and an encoded traversal;
  * **state that must survive a restart must be persisted**, not just held in a
    dict - the beacon-token set is saved and re-loaded here (the live proof
    across a real process restart is in `test_gateway.py`);
  * **best-effort I/O must never raise** where it is called from a server
    thread - `log()` against an unwritable path.

Everything is cleaned up; the repo is left untouched.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT / "server"
LOGS = tempfile.mkdtemp(prefix="dsh_srv_unit_")
os.environ["DSH_LOGS_DIR"] = LOGS          # before the import: LOGS is module state
os.environ.setdefault("HTTP_BIND", "127.0.0.1")
sys.path.insert(0, str(SERVER_DIR))
sys.dont_write_bytecode = True             # no __pycache__ side effect in server/

import server  # noqa: E402

failed = 0


def check(name: str, ok: bool, note: str = "") -> bool:
    global failed
    print(("PASS" if ok else "FAIL"), name, ("- " + note if note else ""), flush=True)
    if not ok:
        failed += 1
    return ok


def exchange(req: bytes, timeout: float = 5.0) -> bytes:
    """Run one request through serve_http() on a socketpair; return the reply.

    serve_http() only writes; the accept loop owns the close.  Closing our end
    before reading is what turns "reply then EOF" into a bounded read instead
    of a timeout per request.
    """
    a, b = socket.socketpair()
    try:
        b.settimeout(timeout)
        server.serve_http(a, req)
        a.close()
        out = b""
        while True:
            try:
                chunk = b.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
        return out
    finally:
        a.close()
        b.close()


def status(reply: bytes) -> bytes:
    return reply.split(b"\r\n", 1)[0]


def get(path: str, host: str = "192.0.2.9") -> bytes:
    return exchange(f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
                    f"Connection: close\r\n\r\n".encode())


def main() -> int:
    # ---- the request gate: a class table, not one filename -------------------
    reply = get("/")
    check("GET / serves the page", b"200" in status(reply),
          status(reply).decode("latin-1"))

    # The expected class is HARDCODED, not taken from the module: a loop over
    # `server.DENY_SUFFIX` silently stops testing an entry the moment it is
    # removed - which is exactly the 2026-10-31 `.pyc` bug (a set-driven loop
    # would have "passed" by not testing it).  Coverage is checked separately so
    # adding a suffix does not require editing this list.
    WANT_SUFFIX = [".py", ".pyc", ".pyo", ".pyd", ".log", ".out", ".err",
                   ".db", ".pem", ".key", ".journal"]
    WANT_DIRS = ["__pycache__"]
    missing = sorted(set(WANT_SUFFIX) - set(server.DENY_SUFFIX))
    check("DENY_SUFFIX still covers the private-source/log extension class",
          not missing, f"missing {missing}")
    missing = sorted(set(WANT_DIRS) - set(server.DENY_DIRS))
    check("DENY_DIRS still covers the compiled-copy directory class",
          not missing, f"missing {missing}")

    planted = []
    try:
        for suffix in WANT_SUFFIX:
            if suffix == ".py":
                # server.py itself: the source class, on a real file
                probe = SERVER_DIR / "server.py"
                reply = get("/" + probe.name)
                check("deny suffix .py is refused (server.py itself)",
                      b"404" in status(reply), status(reply).decode("latin-1"))
                continue
            probe = SERVER_DIR / f"dsh_probe{suffix}"
            probe.write_bytes(b"private-fixture")
            planted.append(probe)
            reply = get("/" + probe.name)
            ok = (b"404" in status(reply) and b"private-fixture" not in reply)
            check(f"deny suffix {suffix} is refused", ok,
                  status(reply).decode("latin-1"))
            up = SERVER_DIR / (probe.stem.upper() + suffix.upper())
            up.write_bytes(b"private-fixture")
            planted.append(up)
            reply = get("/" + up.name)
            check(f"deny suffix {suffix} is refused in mixed case",
                  b"404" in status(reply) and b"private-fixture" not in reply,
                  status(reply).decode("latin-1"))

        # the directory classes are denied by PATH, before existence is tested
        for d in WANT_DIRS + ["logs"]:
            path = f"/{d}/probe.bin"
            reply = get(path)
            check(f"denied path {path} is refused", b"404" in status(reply),
                  status(reply).decode("latin-1"))

        # traversal: plain and encoded, plus a sibling of the docroot
        for path in ("/../AGENTS.md", "/..%2FAGENTS.md", "/%2e%2e/AGENTS.md",
                     "/../../README.md"):
            reply = get(path)
            check(f"traversal {path} cannot escape the docroot",
                  b"404" in status(reply) and b"# AGENTS" not in reply,
                  status(reply).decode("latin-1"))

        # a known HTTP method we do not serve is answered as HTTP, never as a
        # raw peer (the shell slot is decided in the accept loop, but 405 here
        # keeps the two lanes from ever overlapping)
        reply = exchange(b"PATCH / HTTP/1.1\r\nHost: t\r\n"
                         b"Content-Length: 0\r\n\r\n")
        check("an unknown method gets 405", b"405" in status(reply),
              status(reply).decode("latin-1"))
    finally:
        for p in planted:
            try:
                p.unlink()
            except OSError:
                pass

    # ---- deploy.sh render: host + artifact hash + token, no markers ---------
    payload = (SERVER_DIR / "payload.dll").read_bytes()
    reply = get("/deploy.sh")
    body = reply.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in reply else b""
    text = body.decode("latin-1")
    # The template's own guard line intentionally keeps the @MARKERS@ (a global
    # replace once rewrote it and made every valid render look unrendered), so
    # the assertions name the assignment lines, not the whole file.
    ok = (b"200" in status(reply)
          and re.search(r"(?m)^H=http://192\.0\.2\.9$", text) is not None
          and re.search(rf"(?m)^WANT={hashlib.md5(payload).hexdigest()}$", text)
          and re.search(rf"(?m)^SIZE_WANT={len(payload)}$", text)
          and re.search(r"(?m)^TOKEN=[0-9a-f]{8}$", text)
          and "*@HOST@*|*@WANT@*|*@BEACON_TOKEN@*)" in text)
    check("deploy.sh is rendered from the served artifact", ok,
          status(reply).decode("latin-1"))
    check("deploy.sh refuses a non-IPv4 Host",
          b"409" in status(get("/deploy.sh", host="localhost")))

    # ---- beacon-token set: trim + persistence (the restart class) -----------
    def rendered_token() -> str:
        t = get("/deploy.sh").split(b"\r\n\r\n", 1)[-1].decode("latin-1")
        for line in t.splitlines():
            if line.startswith("TOKEN="):
                return line.split("=", 1)[1]
        return ""

    check("a render yields an 8-hex beacon token",
          bool(re.fullmatch(r"[0-9a-f]{8}", rendered_token())))
    with server.state_lock:
        server.BEACON_TOKENS.clear()
        server.BEACON_TOKENS_USED.clear()
    t_live = rendered_token()
    with server.state_lock:                    # the payload beacons right away
        server.BEACON_TOKENS_USED.add(t_live)
        server._save_beacon_tokens()
    t_stale = rendered_token()
    t_mid = rendered_token()
    t_last = rendered_token()
    check("a USED token survives later renders (two stray GETs cannot evict it)",
          t_live in server.BEACON_TOKENS)
    check("an UNUSED token older than the last two renders is evicted",
          t_stale not in server.BEACON_TOKENS)
    check("the last two renders stay valid",
          t_mid in server.BEACON_TOKENS and t_last in server.BEACON_TOKENS)

    # simulate the PC-server restart: fresh process = empty dicts + the file
    with server.state_lock:
        server.BEACON_TOKENS.clear()
        server.BEACON_TOKENS_USED.clear()
    server._load_beacon_tokens()
    check("a USED token is reloaded after a restart (beacons.log stays useful)",
          t_live in server.BEACON_TOKENS and t_live in server.BEACON_TOKENS_USED)
    check("an evicted token is not resurrected by the reload",
          t_stale not in server.BEACON_TOKENS)

    # a corrupt or hand-edited file must not take the server down
    Path(server.BEACON_TOKENS_FILE).write_text("{not json", encoding="utf-8")
    try:
        server._load_beacon_tokens()
        ok = True
    except Exception as exc:                    # noqa: BLE001 - the point
        ok = False
        print(f"  reload raised {type(exc).__name__}: {exc}", flush=True)
    check("a corrupt beacon-token file is tolerated", ok)
    Path(server.BEACON_TOKENS_FILE).write_text(json.dumps(
        [{"tok": "not-a-token", "used": True}, {"tok": "0123abcd", "used": False},
         "junk", 7]), encoding="utf-8")
    with server.state_lock:
        server.BEACON_TOKENS.clear()
        server.BEACON_TOKENS_USED.clear()
    server._load_beacon_tokens()
    check("malformed rows are skipped, the valid one is kept",
          server.BEACON_TOKENS == ["0123abcd"] and not server.BEACON_TOKENS_USED,
          str(server.BEACON_TOKENS))

    # ---- best-effort logging ------------------------------------------------
    real_log = server.LOG
    try:
        server.LOG = Path(LOGS) / "no-such-dir" / "shell.log"
        try:
            server.log("must not escape\n")
            ok = True
        except Exception as exc:                # noqa: BLE001 - the point
            ok = False
            print(f"  log raised {type(exc).__name__}: {exc}", flush=True)
        check("log() never raises when the log file is unwritable", ok)
        server.LOG = Path(LOGS) / "shell-probe.log"
        server.log("probe-line\n")
        check("log() writes when it can",
              "probe-line" in Path(server.LOG).read_text(encoding="utf-8"))
    finally:
        server.LOG = real_log

    # ---- a waiting client that vanished frees the slot ----------------------
    a, b = socket.socketpair()
    try:
        check("_client_gone is False for a live peer", server._client_gone(a) is False)
        b.close()
        deadline = time.time() + 2.0
        while time.time() < deadline and not server._client_gone(a):
            time.sleep(0.05)
        check("_client_gone sees a closed peer", server._client_gone(a) is True)
    finally:
        a.close()

    # ---- the whole-request deadline: returned immediately, not per recv ------
    real_timeout = server.HTTP_REQUEST_TIMEOUT
    try:
        server.HTTP_REQUEST_TIMEOUT = 0.25
        a, b = socket.socketpair()
        try:
            t0 = time.time()
            head, body = server._read_full_request(a, b"GET / HTTP/1.1\r\n")
            elapsed = time.time() - t0
        finally:
            a.close()
            b.close()
        check("a partial request is bounded by the absolute deadline",
              elapsed < 1.5 and b"\r\n\r\n" not in head and body == b"",
              f"{elapsed:.2f}s head={head[:40]!r}")
    finally:
        server.HTTP_REQUEST_TIMEOUT = real_timeout

    print(flush=True)
    if failed:
        print(f"{failed} check(s) failed", flush=True)
        return 1
    print("server unit checks ok", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
