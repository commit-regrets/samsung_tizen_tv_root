"""Run a shell command as root inside the TV stub (op 7: fork + /bin/sh -c).

Usage: python physrun.py "<command>" [wait_seconds]
"""
import socket
import struct
import sys
import time

import physmap as T

cmd = sys.argv[1]
wait = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
# The stub's cmdbuf is 512 B and it stores "-c\0" + command there; a longer one
# writes past the buffer into adjacent stub data.
if len(cmd.encode()) > 509:
    raise SystemExit(f"[-] command is {len(cmd.encode())} B; the stub limit is 509 B")

rpc = T.RPC(timeout=20)
buf = b"-c\x00" + cmd.encode()
rpc._cmd(7, 0, 0, len(buf))
rpc.s.sendall(buf)
try:
    pid = struct.unpack("<i", rpc._recv_exact(4))[0]
except Exception as exc:
    print(f"[run] no status: {exc}")
    raise SystemExit(1)
print(f"[run] child pid={pid}")

rpc.s.settimeout(0.5)
data = b""
end = time.time() + wait
while time.time() < end:
    try:
        d = rpc.s.recv(65536)
        if not d:
            break
        data += d
    except socket.timeout:
        continue
sys.stdout.write(data.decode("latin-1", "replace"))
print("\n[run] done,", len(data), "bytes")
rpc.close()
