"""In-memory physmap RPC — offline stand-in for a live TV stub.

The QEMU kernel in the research tree (`samsungtv/research/sim`) builds, but it
never prints a console, so it cannot drive these tools. This file is the PC-side
replacement: a dict-backed `read` / `write32` / `readmany` that duck-types
`physmap.RPC`, planted with the cred layout measured on the TV and confirmed
against that kernel's DWARF.

    python tools/sim_rpc.py           # self-test, no TV, no server
    from sim_rpc import MemRPC, plant_cred

Offsets below are the ones the payload and `kernel_root.py` already use.
`cred.uid` is +4; `cap_inheritable` is +0x28. `patch_full` must verify uid
at +4, not inheritable.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kernel_root as K  # noqa: E402
import physmap as T  # noqa: E402

PAGE = 0x1000
OWNER_UID = 5001
OWNER_GID = 100
OWNER_IDS = (OWNER_UID, OWNER_GID) * 4
OWNER_PAT = struct.pack("<8I", *OWNER_IDS)
CAP_FULL = 0x3FFFFFFFFF

# task_struct / cred — TV-measured, DWARF-matched on the pontusml sim kernel
O_TASKS = 0x23C
O_REAL_PARENT = 0x2F0
O_REAL_CRED = 0x3F4
O_CRED = 0x3F8
O_COMM = 0x400
O_USAGE = 0x00
O_UID = 0x04
O_CAP_INHERITABLE = 0x28
O_CAP_PERMITTED = 0x30
O_CAP_EFFECTIVE = 0x38


class MemRPC:
    """Sparse physical memory. Same method names as `physmap.RPC`."""

    def __init__(self):
        self.pages: dict[int, bytearray] = {}

    def _page(self, phys: int) -> bytearray:
        base = phys & ~0xFFF
        buf = self.pages.get(base)
        if buf is None:
            buf = bytearray(PAGE)
            self.pages[base] = buf
        return buf

    def read(self, phys: int, n: int) -> bytes:
        out = bytearray()
        while n > 0:
            buf = self._page(phys)
            off = phys & 0xFFF
            chunk = min(n, PAGE - off)
            out.extend(buf[off : off + chunk])
            phys += chunk
            n -= chunk
        return bytes(out)

    def read_u32(self, phys: int) -> int:
        return struct.unpack_from("<I", self.read(phys, 4))[0]

    def write32(self, phys: int, val: int) -> int:
        buf = self._page(phys)
        off = phys & 0xFFF
        if off + 4 > PAGE:
            return -1
        struct.pack_into("<I", buf, off, val & 0xFFFFFFFF)
        return 0

    def write(self, phys: int, data: bytes) -> None:
        for i, b in enumerate(data):
            buf = self._page(phys + i)
            buf[(phys + i) & 0xFFF] = b

    def readmany(self, first_page: int, count: int):
        page = first_page
        for _ in range(count):
            yield page, bytes(self._page(page))
            page += PAGE


def plant_cred(rpc: MemRPC, phys: int, *, uid: int = OWNER_UID, gid: int = OWNER_GID,
               usage: int = 4, inheritable: int = 0, permitted: int = 0,
               effective: int = 0) -> int:
    """Write a `struct cred` at `phys`. Returns `phys`."""
    rpc.write32(phys + O_USAGE, usage)
    ids = (uid, gid) * 4
    rpc.write(phys + O_UID, struct.pack("<8I", *ids))
    rpc.write(phys + O_CAP_INHERITABLE, inheritable.to_bytes(8, "little"))
    rpc.write(phys + O_CAP_PERMITTED, permitted.to_bytes(8, "little"))
    rpc.write(phys + O_CAP_EFFECTIVE, effective.to_bytes(8, "little"))
    return phys


def find_owner_pat(pages: list[bytes], overlap: int = 0) -> list[int]:
    """Page-local `bytes.find(OWNER_PAT)`, optionally with an overlap window.

    `overlap=0` is what `scan_cred.py` / `tv_rootwatch.py` do today.
    `overlap=31` catches a 32-byte pattern that straddles two pages.
    """
    hits = []
    if overlap:
        blob = b"".join(pages)
        off = 0
        while True:
            i = blob.find(OWNER_PAT, off)
            if i < 0:
                break
            hits.append(i)
            off = i + 1
        return hits
    base = 0
    for data in pages:
        off = 0
        while True:
            i = data.find(OWNER_PAT, off)
            if i < 0:
                break
            hits.append(base + i)
            off = i + 1
        base += len(data)
    return hits


def _check(name: str, ok: bool, note: str) -> bool:
    print(("PASS" if ok else "FAIL"), name, "-", note, flush=True)
    return ok


def selftest() -> int:
    failed = 0

    failed += not _check(
        "layout constants",
        (K.O_COMM, K.O_CRED, K.O_REAL, K.O_CAP_PERMITTED, K.O_CAP_EFFECTIVE)
        == (O_COMM, O_CRED, O_REAL_CRED, O_CAP_PERMITTED, O_CAP_EFFECTIVE),
        "kernel_root.py matches the DWARF/TV cred and task offsets",
    )

    rpc = MemRPC()
    cred = plant_cred(rpc, 0x20100000, usage=4)
    virt = cred + 0xA0000000
    failed += not _check(
        "_sane_cred owner",
        K._sane_cred(rpc, virt),
        f"usage=4 uid={OWNER_UID} at cred {T.hexs(cred)}",
    )
    plant_cred(rpc, 0x20101000, usage=0x20000)
    failed += not _check(
        "_sane_cred rejects huge usage",
        not K._sane_cred(rpc, 0x20101000 + 0xA0000000),
        "usage=0x20000 is not a real cred",
    )

    plant_cred(rpc, cred, usage=4, inheritable=0x11223344)
    ok_ids = T.patch_cred(rpc, cred)
    back = struct.unpack("<8I", rpc.read(cred + O_UID, 32))
    failed += not _check(
        "patch_cred zeros ids",
        ok_ids and all(v == 0 for v in back),
        f"ids after patch = {back}",
    )

    # Non-zero inheritable used to make patch_full return False (it read +0x28 as uid).
    plant_cred(rpc, cred, usage=4, inheritable=0x11223344)
    reported = K.patch_full(rpc, cred)
    real_uid = rpc.read_u32(cred + O_UID)
    perm = int.from_bytes(rpc.read(cred + O_CAP_PERMITTED, 8), "little")
    failed += not _check(
        "patch_full uid readback",
        reported and real_uid == 0 and perm == CAP_FULL,
        f"uid at +{O_UID}={real_uid} inheritable left at +{O_CAP_INHERITABLE}; returned {reported}",
    )

    p1 = b"\x00" * (PAGE - 16) + OWNER_PAT[:16]
    p2 = OWNER_PAT[16:] + b"\x00" * (PAGE - 16)
    failed += not _check(
        "owner-pat page straddle",
        find_owner_pat([p1, p2], overlap=0) == []
        and find_owner_pat([p1, p2], overlap=31) != [],
        "32-byte pattern split 16/16 is invisible per page, visible with overlap=31",
    )

    # The REAL scanner used by scan_cred.py / tv_rootwatch.py must find a cred
    # whose ids straddle the page boundary (M5).  Plant one 16 bytes before it.
    rpc2 = MemRPC()
    base = 0x20200000
    straddle = base + PAGE - 20            # ids at straddle+4 = base+PAGE-16
    plant_cred(rpc2, straddle, usage=4)
    found = list(K.iter_owner_creds(rpc2, base, base + 2 * PAGE))
    failed += not _check(
        "iter_owner_creds page straddle",
        straddle in found,
        f"cred at {T.hexs(straddle)}; found {[T.hexs(f) for f in found]}",
    )
    per_page = [bytes(rpc2.read(base + i * PAGE, PAGE)) for i in range(2)]
    failed += not _check(
        "old page-local scan misses it",
        find_owner_pat(per_page, overlap=0) == [],
        "this is the M5 bug the carry window fixes",
    )

    ordinary = [base + PAGE + 0x80, base + 2 * PAGE + 0x100, base + 3 * PAGE + 0x40]
    for addr in ordinary:
        plant_cred(rpc2, addr, usage=2)
    found = set(K.iter_owner_creds(rpc2, base, base + 4 * PAGE))
    failed += not _check(
        "iter_owner_creds ordinary hits",
        all(a in found for a in ordinary),
        f"planted {[T.hexs(a) for a in ordinary]}, found {len(found)}",
    )

    print(flush=True)
    if failed:
        print(f"{failed} check(s) failed", flush=True)
        return 1
    print("sim_rpc self-test ok", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(selftest())
