"""Talk to the root channel on the TV (TCP 31337, line protocol).

Usage: python tools/root_shell.py "<command>" [tv-ip]

The address can also come from TV_IP or ROOT_TV (the name the .ps1 wrappers
use), so `$env:ROOT_TV = "..."; python tools/root_shell.py id` works.
Exit codes: 0 ok, 2 no address, 1 connection/protocol failure.
"""
import os
import socket
import sys

host = (sys.argv[2] if len(sys.argv) > 2
        else os.environ.get("TV_IP") or os.environ.get("ROOT_TV"))
if not host:
    print('usage: root_shell.py "<command>" [tv-ip]   (or set TV_IP / ROOT_TV)',
          file=sys.stderr)
    raise SystemExit(2)
cmd = sys.argv[1] if len(sys.argv) > 1 else "id"

try:
    s = socket.create_connection((host, 31337), timeout=8)
    s.settimeout(20)
except OSError as exc:
    print(f"root_shell: cannot connect to {host}:31337: {exc}", file=sys.stderr)
    raise SystemExit(1)
s.sendall(cmd.encode() + b"\n")
buf = b""
while b"__END__" not in buf:
    try:
        d = s.recv(4096)
    except socket.timeout:
        break
    if not d:
        break
    buf += d
sys.stdout.write(buf.decode("latin-1", "replace"))
s.close()
raise SystemExit(0 if b"__END__" in buf else 1)
