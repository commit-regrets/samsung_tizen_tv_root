"""Write a local file onto the TV as root through the stub (op 8, chunked).

Usage: python tools/write_root.py <remote_path> <local_file>
"""
import struct
import sys

import physmap as T

path = sys.argv[1]
src = sys.argv[2]
data = open(src, "rb").read()
pb = path.encode()
CH = 4096
# The stub has pathbuf 256 and databuf 4096 and does not clamp the header, so a
# longer path or chunk overruns the stub's own buffers.
if len(pb) > 255:
    raise SystemExit(f"[-] path is {len(pb)} B; the stub limit is 255 B")
if CH > 4096:
    raise SystemExit("[-] chunk size exceeds the stub's 4096 B buffer")

rpc = T.RPC(timeout=60)
for off in range(0, len(data), CH):
    part = data[off:off + CH]
    flags = 0 if off == 0 else 1
    rpc._cmd(8, flags, len(pb), len(part))
    rpc.s.sendall(pb)
    rpc.s.sendall(part)
    st = struct.unpack("<i", rpc._recv_exact(4))[0]
    print(f"[file] {off}+{len(part)} -> status {st}")
    if st != 0:
        raise SystemExit(1)
print(f"[file] wrote {len(data)} bytes to {path}")
rpc.close()
