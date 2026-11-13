"""Embed tools/physrpc_shellcode.bin into server/payloads/browser_payload.js.

The page writes the SHELLCODE array into the staging buffer at L_SHELL (0x600);
BUF_SIZE is 0x4000, so the blob must stay under 0x4000-0x600 = 14848 bytes
(checked here, because a silent overflow there corrupts the staging area, not
the shellcode).

    python tools/build_physrpc.py          # rebuild the blob from physrpc.S
    python tools/embed_physrpc.py          # write it into the page
    python tools/embed_physrpc.py --check  # verify the page matches the blob
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN = HERE / "physrpc_shellcode.bin"
JS = HERE.parent / "server" / "payloads" / "browser_payload.js"
ROW = 12                     # bytes per source line, matching the existing style
L_SHELL = 0x600
BUF_SIZE = 0x4000


def js_array(blob: bytes, eol: bytes) -> bytes:
    rows = []
    for i in range(0, len(blob), ROW):
        chunk = blob[i:i + ROW]
        rows.append(b"  " + b",".join(b"0x%02x" % b for b in chunk) + b",")
    return b"[" + eol + eol.join(rows) + eol + b"]"


def main() -> int:
    if not BIN.is_file():
        print(f"[-] {BIN} missing; run tools/build_physrpc.py first")
        return 1
    blob = BIN.read_bytes()
    headroom = BUF_SIZE - L_SHELL
    if len(blob) > headroom:
        print(f"[-] blob {len(blob)} B does not fit the staging buffer "
              f"({headroom} B available at L_SHELL)")
        return 1

    data = JS.read_bytes()
    m = re.search(rb"const SHELLCODE = \[.*?\r?\n\];", data, re.S)
    if not m:
        print(f"[-] SHELLCODE array not found in {JS}")
        return 1
    old_bytes = len(re.findall(rb"0x[0-9a-f]{2}", m.group(0)))
    eol = b"\r\n" if b"\r\n" in data else b"\n"
    block = b"const SHELLCODE = " + js_array(blob, eol) + b";"

    if "--check" in sys.argv:
        if m.group(0) == block:
            print(f"OK: page SHELLCODE == physrpc_shellcode.bin ({len(blob)} B)")
            return 0
        print(f"DIFF: page has {old_bytes} B, blob has {len(blob)} B")
        return 1

    data = data[:m.start()] + block + data[m.end():]
    JS.write_bytes(data)
    # read it back: the regex must now decode to exactly the blob
    again = re.search(rb"const SHELLCODE = \[.*?\r?\n\];", data, re.S)
    nums = [int(x, 16) for x in re.findall(rb"0x[0-9a-f]{2}", again.group(0))]
    if bytes(nums) != blob:
        print("[-] readback mismatch after embedding")
        return 1
    print(f"embedded {len(blob)} B (was {old_bytes} B) into {JS.name}; "
          f"{headroom - len(blob)} B staging headroom left")
    return 0


if __name__ == "__main__":
    sys.exit(main())
