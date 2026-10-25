"""Samsung TV remote-control WebSocket probe / app launcher (diagnostic).

    python tools/tv_ws_launch.py --tv <tv-ip>                 # pair only
    python tools/tv_ws_launch.py --tv <tv-ip> --launch --url http://<pc>/index.html
    python tools/tv_ws_launch.py --tv <tv-ip> --launch --app com.samsung.tv.MultiControl-Service

What it does: connects to the TV's local remote-control channel
(`samsung.remote.control`), prints the TV's messages, saves the pairing token,
and with `--launch` asks the TV to open an app via `ed.apps.launch`.

Status on the project's test unit (QE65QNX1DATXXN, Tizen 9): the TV answers
`ms.channel.unauthorized` for both `ws://<tv>:8001/...` and the `wss://<tv>:8002`
variant, with or without the previously saved token, so this cannot currently
start the browser or the payload app there. It is kept because it is the
documented, token-based way in on other Samsung sets, and because a diagnostic
that proves "the TV will not pair" is worth having (it is one of the reasons
the AUL boot hook is the only reliable lane on this unit — see
docs/OPEN-ISSUES.md).

First run on a TV that accepts it: the set shows an "Allow" dialog once; later
runs reuse server/logs/ws_token.txt. Needs `websocket-client`.
"""
import argparse
import base64
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "server" / "logs" / "ws_token.txt"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tv", required=True, help="TV address (e.g. <tv-ip>)")
    ap.add_argument("--name", default="dsh-toolkit", help="name shown in the TV's Allow dialog")
    ap.add_argument("--url", default="http://127.0.0.1/index.html",
                    help="URL for the DEEP_LINK metaTag")
    ap.add_argument("--app", default="org.tizen.browser", help="appId to launch")
    ap.add_argument("--launch", action="store_true", help="send ed.apps.launch after pairing")
    ap.add_argument("--token", default="", help="pairing token (else the saved one)")
    ap.add_argument("--port", type=int, default=8001, choices=(8001, 8002))
    ap.add_argument("--secure", action="store_true", help="use wss:// (port 8002)")
    ap.add_argument("--timeout", type=float, default=45.0,
                    help="seconds to wait for ms.channel.connect")
    args = ap.parse_args()

    try:
        import websocket                      # websocket-client
    except ImportError:
        print("[-] websocket-client is not installed: pip install websocket-client")
        return 2

    token = args.token.strip()
    if not token and TOKEN_FILE.is_file():
        token = TOKEN_FILE.read_text(encoding="ascii", errors="replace").strip()
    name_b64 = base64.b64encode(args.name.encode()).decode()
    scheme = "wss" if args.secure else "ws"
    url = (f"{scheme}://{args.tv}:{args.port}/api/v2/channels/samsung.remote.control"
           f"?name={name_b64}")
    if token:
        url += f"&token={token}"

    print(f"[ws] connecting {url}", flush=True)
    try:
        ws = websocket.create_connection(url, timeout=10, origin="http://localhost",
                                         sslopt={"cert_reqs": 0} if args.secure else None)
    except Exception as exc:
        print(f"[-] cannot connect: {exc}", flush=True)
        return 1
    print("[ws] connected; accept the Allow dialog on the TV if it appears", flush=True)

    connected = False
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        try:
            raw = ws.recv()
        except Exception as exc:
            print(f"[ws] recv: {exc}", flush=True)
            break
        if not raw:
            continue
        print(f"[tv] {raw}", flush=True)
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        event = msg.get("event")
        if event == "ms.channel.connect":
            connected = True
            tok = (msg.get("data") or {}).get("token") or ""
            if tok:
                TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
                TOKEN_FILE.write_text(tok, encoding="ascii")
                print(f"[ws] token saved to {TOKEN_FILE}", flush=True)
            break
        if event in ("ms.channel.unauthorized", "ms.channel.timeOut"):
            print(f"[ws] {event} - the TV refused the connection "
                  f"(no Allow dialog will appear)", flush=True)
            ws.close()
            return 3

    if not connected:
        print("[ws] no ms.channel.connect (pairing refused or timed out)", flush=True)
        ws.close()
        return 1

    if args.launch:
        payload = {
            "method": "ms.channel.emit",
            "params": {
                "event": "ed.apps.launch",
                "to": "host",
                "data": {
                    "appId": args.app,
                    "action_type": "DEEP_LINK",
                    "metaTag": args.url,
                },
            },
        }
        print(f"[ws] launching {args.app} {args.url}", flush=True)
        ws.send(json.dumps(payload))
        time.sleep(2)
        try:
            ws.settimeout(2)
            while True:
                print(f"[tv] {ws.recv()}", flush=True)
        except Exception:
            pass
    ws.close()
    print("[ws] done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
