"""Chunked dump of the TV kernel flash partition over the 31337 root channel.

Procedure: find the kernel partition from /sys/block/mmcblk0/mmcblk0p*/uevent
(this unit's expected layout is /dev/mmcblk0p5, A/B-mirrored in p6 — verify
before trusting), then read the PRISTINE FLASH IMAGE — the build as flashed,
not the running RAM copy (use dump_kernel_ram.py for that). The payload caps
a single reply at ~1 MiB, so the 12 MiB window is pulled in 384 KiB raw
chunks, appended locally, then verified against the TV's own md5 read of the
same range — that match is the only acceptance signal a partition dump has.

Usage:
  python tools/dump_kernel_chunked.py <tv-ip> [out-file]
  python tools/dump_kernel_chunked.py -h | --help
  (tv-ip falls back to the TV_IP environment variable; no hardcoded default)
"""
import base64
import hashlib
import os
import socket
import sys

argv = sys.argv[1:]
if "-h" in argv or "--help" in argv:
    print(__doc__)
    sys.exit(0)
bad = [a for a in argv if a.startswith("-")]
if bad:
    sys.exit("unknown option(s): %s\nusage: dump_kernel_chunked.py "
             "<tv-ip> [out-file] (-h for help)" % ", ".join(bad))
HOST = argv[0] if argv else os.environ.get("TV_IP")
if not HOST:
    sys.exit("usage: dump_kernel_chunked.py <tv-ip> [out-file]  "
             "(or set TV_IP; no default host is baked in)")
OUT = argv[1] if len(argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "ghidra",
    "Image_flash_partition.bin")
SKIP_BLOCKS = 2048          # kernel payload starts at partition offset 1 MiB
TOTAL_BLOCKS = 24576        # 12 MiB
CHUNK_BLOCKS = 768          # 384 KiB per round trip
TIMEOUT = float(os.environ.get("ROOT_SHELL_TIMEOUT", "60"))


def run_cmd(cmd):
    s = socket.create_connection((HOST, 31337), timeout=10)
    s.settimeout(TIMEOUT)
    s.sendall((cmd + "\n").encode())
    buf = []
    tail = b""
    try:
        while True:
            line = s.recv(65536)
            if not line:
                break
            buf.append(line)
            tail = (tail + line)[-4096:]   # marker may split across recvs
            if b"__END__" in tail:
                break
    finally:
        s.close()
    return b"".join(buf)


def main():
    total = 0
    md5 = hashlib.md5()
    partial = OUT + ".partial"
    os.makedirs(os.path.dirname(os.path.abspath(partial)), exist_ok=True)
    with open(partial, "wb") as f:
        for i in range(0, TOTAL_BLOCKS, CHUNK_BLOCKS):
            n = min(CHUNK_BLOCKS, TOTAL_BLOCKS - i)
            skip = SKIP_BLOCKS + i
            raw = run_cmd(
                f"dd if=/dev/mmcblk0p5 bs=512 skip={skip} count={n} 2>/dev/null | base64 -w 240"
            )
            b64 = b"".join(
                l for l in raw.split(b"\n")
                if l.strip() and not l.startswith(b"__END__")
            )
            data = base64.b64decode(b64, validate=True)
            if len(data) != n * 512:
                sys.exit(
                    f"chunk at sector {skip}: got {len(data)} bytes, "
                    f"expected {n * 512} - transfer desynced; "
                    f"partial kept at {partial}")
            f.write(data)
            md5.update(data)
            total += len(data)
            print(f"chunk {i // CHUNK_BLOCKS + 1}: +{len(data)} (total {total})",
                  flush=True)

    tv_line = run_cmd(
        f"dd if=/dev/mmcblk0p5 bs=512 skip={SKIP_BLOCKS} count={TOTAL_BLOCKS} "
        f"2>/dev/null | md5sum"
    ).split(b"\n")[0].decode(errors="replace").split()
    tv = tv_line[0] if tv_line else ""
    if len(tv) != 32:
        sys.exit(f"could not parse the TV's md5 (got {tv_line[:3]!r}); "
                 f"partial kept at {partial}")
    mine = md5.hexdigest()
    print(f"tv md5:   {tv}")
    print(f"local md5: {mine}")
    if tv == mine:
        os.replace(partial, OUT)
        print(f"MATCH - {OUT} written", flush=True)
    else:
        print(f"MISMATCH - partial kept at {partial}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
