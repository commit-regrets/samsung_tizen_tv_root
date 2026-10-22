"""Talk to the v5 root channel on the TV (TCP 31337, line protocol).

Usage: python chan.py "<command>" [host]
"""
import os
import socket
import sys

host = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("TV_IP")
if not host:
    print('usage: root_shell.py "<command>" [tv-ip]   (or set TV_IP)', file=sys.stderr)
    raise SystemExit(2)
cmd = sys.argv[1] if len(sys.argv) > 1 else "id"

s = socket.create_connection((host, 31337), timeout=8)
s.settimeout(20)
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
