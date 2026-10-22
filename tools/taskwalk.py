"""Walk init_task.tasks in one direction and report comm tags (diagnostic).

Usage: python taskwalk.py [next|prev] [max_hops]
"""
import sys

import kernel_root as K
import physmap as T

INIT_VIRT = 0xC0957180
INIT_PHYS = 0x20957180
OFF = 0x23C
INFO = 0x400


def main():
    direction = sys.argv[1] if len(sys.argv) > 1 else "next"
    hops = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
    step = 0 if direction == "next" else 4
    rpc = T.RPC(timeout=20)
    try:
        head = INIT_VIRT + OFF
        cur = rpc.read_u32(INIT_PHYS + OFF + step)
        tags = 0
        for i in range(hops):
            if not T._kernel_ptr(cur):
                print(f"[!] bad link {T.hexs(cur)} at hop {i}", flush=True)
                break
            task = (cur - OFF) & 0xFFFFFFFF
            try:
                comm = rpc.read(K.PHYS(task) + INFO, 16).split(b"\0")[0]
            except Exception as exc:
                print(f"[!] comm read failed at hop {i}: {exc}", flush=True)
                break
            if i < 8 or comm.startswith(b"PHYSRP") or comm.startswith(b"PHYRFORK"):
                print(f"  [{i:4d}] {T.hexs(task)} {comm!r}", flush=True)
            if comm.startswith(b"PHYSRP"):
                tags += 1
            if i and i % 500 == 0:
                print(f"  ... hop {i}", flush=True)
            try:
                cur = rpc.read_u32(K.PHYS(cur) + step)
            except Exception as exc:
                print(f"[!] link read failed at hop {i}: {exc}", flush=True)
                break
        print(f"[*] {direction}: {i + 1} hops, {tags} PHYSRP tags", flush=True)
    finally:
        rpc.close()


if __name__ == "__main__":
    main()
