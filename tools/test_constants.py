"""Cross-check the measured constants shared by the four implementations.

    python tools/test_constants.py

The exploit is driven by the same numbers in four places that no other test
compares:

  payload/Program.cs   the boot payload (what actually runs on the TV)
  tools/sim_rpc.py     the offline twin used to test logic changes
  tools/kernel_root.py the browser-lane end-game
  tools/physmap.py     the RPC client (init task offset, RAM bounds)
  tools/physrpc.S      the ARM stub (device node, buffer clamps)

A drift here is silent: the simulator goes green while the TV refuses to root,
or the client reads the wrong frame.  This layer greps the sources and fails on
any disagreement.  It caught two real divergences when it was added (v39):
SaneCred's gid bound in the sim, and physmap's missing DATA_SHIFT.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROG = ROOT / "payload" / "Program.cs"
STUB = HERE / "physrpc.S"
SIM = HERE / "sim_rpc.py"
KROOT = HERE / "kernel_root.py"
PHYSMAP = HERE / "physmap.py"
DEPLOY = ROOT / "server" / "deploy.sh"
RECOVER = ROOT / "server" / "recover.sh"

FAILS = 0


def check(name, ok, note=""):
    global FAILS
    print(("PASS" if ok else "FAIL"), name, ("- " + note if note else ""), flush=True)
    if not ok:
        FAILS += 1


def grab(text, pattern, conv=int, default=None):
    m = re.search(pattern, text, re.M)
    return conv(m.group(1), 0) if m else default


def main() -> int:
    prog = PROG.read_text(encoding="utf-8")
    sim = SIM.read_text(encoding="utf-8")
    kroot = KROOT.read_text(encoding="utf-8")
    physmap = PHYSMAP.read_text(encoding="utf-8")
    stub = STUB.read_text(encoding="ascii")
    deploy = DEPLOY.read_text(encoding="utf-8")
    recover = RECOVER.read_text(encoding="utf-8")
    server = (ROOT / "server" / "server.py").read_text(encoding="utf-8")
    run_root = (HERE / "run_root.py").read_text(encoding="utf-8")
    auto_root = (HERE / "auto_root.py").read_text(encoding="utf-8")
    write_root = (HERE / "write_root.py").read_text(encoding="utf-8")

    # --- the payload's own offsets -----------------------------------------
    want = {
        "PHYS_OFF": 0xA0000000, "O_COMM": 0x400, "O_CRED": 0x3F8,
        "O_REAL": 0x3F4, "O_CHILDREN": 0x2F8, "O_SIBLING": 0x300,
        "SlotStride": 0x8000, "SlotCount": 2048,
    }
    for name, val in want.items():
        got = grab(prog, rf"const int {name}\s*=\s*(0x[0-9A-Fa-f]+|\d+)")
        if got is None:
            got = grab(prog, rf"const uint {name}\s*=\s*(0x[0-9A-Fa-f]+|\d+)")
        check(f"Program.cs {name} == {val:#x}", got == val, f"got {got}")

    # --- the simulator mirrors the payload ---------------------------------
    sim_want = {"O_TASKS": 0x23C, "O_REAL_PARENT": 0x2F0, "O_PARENT": 0x2F4,
                "O_REAL_CRED": 0x3F4, "O_CRED": 0x3F8, "O_COMM": 0x400,
                "O_CHILDREN": 0x2F8, "O_SIBLING": 0x300,
                "PHYS_OFF": 0xA0000000}
    for name, val in sim_want.items():
        got = grab(sim, rf"^{name}\s*=\s*(0x[0-9A-Fa-f]+|\d+)")
        check(f"sim_rpc {name} == {val:#x}", got == val, f"got {got}")
    check("sim_rpc sweep band == proven RAM (0x20000000-0x40000000)",
          grab(sim, r"^SWEEP_LO\s*=\s*(0x[0-9A-Fa-f]+)") == 0x20000000
          and grab(sim, r"^SWEEP_HI\s*=\s*(0x[0-9A-Fa-f]+)") == 0x40000000)
    sim_span = grab(sim, r"^PROBE_SPAN_PAGES\s*=\s*(\d+)")
    prog_span = grab(prog, r"const int SpanPages\s*=\s*(\d+)")
    check("sim_rpc probe span mirrors SpanPages",
          sim_span is not None and sim_span == prog_span,
          f"sim={sim_span} payload={prog_span}")
    check("sim_rpc CAP_FULL == payload caps (0x3fffffffff)",
          grab(sim, r"^CAP_FULL\s*=\s*(0x[0-9A-Fa-f]+)") == 0x3FFFFFFFFF)

    # --- limits the tests pin ----------------------------------------------
    check("payload MaxPatched == 8",
          grab(prog, r"const int MaxPatched\s*=\s*(\d+)") == 8)
    check("payload MaxSteps == 256",
          grab(prog, r"const int MaxSteps\s*=\s*(\d+)") == 256)
    check("payload probe budget == 2500 ms",
          grab(prog, r"const int BudgetMs\s*=\s*(\d+)") == 2500)
    check("payload Run timeout == 120 s",
          grab(prog, r"const int RunTimeoutMs\s*=\s*(\d+)") == 120000)
    check("payload fast rounds == {0,0,5000,5000}",
          "new int[] { 0, 0, 5000, 5000 }" in prog)
    check("payload allows four fast attempts",
          "attempt <= 4" in prog)

    # --- kernel_root / physmap offsets -------------------------------------
    check("kernel_root O_COMM/O_CRED/O_REAL match the payload",
          grab(kroot, r"^O_COMM\s*=\s*(0x[0-9A-Fa-f]+)") == 0x400
          and grab(kroot, r"^O_CRED\s*=\s*(0x[0-9A-Fa-f]+)") == 0x3F8
          and grab(kroot, r"^O_REAL\s*=\s*(0x[0-9A-Fa-f]+)") == 0x3F4)
    check("kernel_root DATA_SHIFT matches the payload's measured shift",
          grab(kroot, r"^DATA_SHIFT\s*=\s*(0x[0-9A-Fa-f]+)") == 0x12000)
    check("physmap OFF_INIT_TASK includes DATA_SHIFT (the root2 bug)",
          "0x93D180 + DATA_SHIFT" in physmap)
    check("physmap RAM default bound is the proven band",
          'TVPHYS_HI", hex(0x40000000)' in physmap)
    check("physmap patch_cred keeps the owner-uid gate",
          "if ids[0] != OWNER_UID" in physmap)

    # --- stub vs payload device nodes --------------------------------------
    stub_node = re.search(r'path:\s*\.ascii "([^"]+)"', stub)
    node = stub_node.group(1).replace("\\0", "") if stub_node else "?"
    check("stub opens /dev/video30 (the documented browser node)",
          node == "/dev/video30", node)
    for n in ("/dev/video40", "/dev/video30", "/dev/video60"):
        check(f"payload node list contains {n}", n in prog)
    check("stub NUL-terminates the op7 command buffer", "NUL after the received" in stub)
    check("stub NUL-terminates the op8 path buffer", "NUL-terminate: open() needs" in stub)

    # --- browser page vs the blob ------------------------------------------
    page = (ROOT / "server" / "payloads" / "browser_payload.js").read_text(
        encoding="utf-8", errors="replace")
    blob = (HERE / "physrpc_shellcode.bin").read_bytes()
    path_at = blob.find(b"/dev/video30")
    sa = blob[path_at - 0x10:path_at - 0x08] if path_at > 0x10 else b""
    m = re.search(r"const pat = \[([^\]]+)\]", page)
    js_pat = bytes(int(x, 16) for x in re.findall(r"0x([0-9a-fA-F]{2})", m.group(1))) if m else b""
    check("page callback pattern == blob sockaddr bytes",
          sa and js_pat == sa, f"blob={sa.hex()} js={js_pat.hex()}")
    check("page patches the callback PORT, not just the IP",
          "arr[i + 2] = (port >> 8) & 0xff" in page)
    check("page aborts when served by hostname", "page served as hostname" in page)
    check("page forwards console output to /save", "b.value += s" in page)
    check("page aborts throw (index.html reports THREW)",
          "throw new Error(\"abort: \" + why)" in page)
    probe = (ROOT / "server" / "probe.html").read_text(encoding="utf-8", errors="replace")
    check("probe.html GC module is well-formed (struct{ i32 })",
          "1, 5, 1, 0x5f, 1, 0x7f, 0" in probe)
    check("probe.html no longer probes WebAssembly.gc", 'feature("gc")' not in probe)
    index = (ROOT / "server" / "index.html").read_text(encoding="utf-8", errors="replace")
    check("index.html retries a failed script load", "RETRY " in index and "retry=" in index)

    # --- v39.1 follow-up guards -------------------------------------------
    check("payload retries the same node on EBUSY (advances only when absent)",
          "busy, retrying this node" in prog and "ENOENT" in prog
          and "ENODEV" in prog)
    check("payload node order starts with video40",
          prog.find('"/dev/video40"') < prog.find('"/dev/video30"')
          < prog.find('"/dev/video60"'))
    check("payload node beacon is state-change + 30 s, not per attempt",
          "still errno=" in prog and "lastWaitBeacon" in prog)
    check("physmap separates the ids write from patch_cred",
          "def patch_ids(" in physmap and "if not patch_ids(" in physmap)
    check("kernel_root writes caps only after a 5001 ids write",
          "T.patch_ids" in kroot)
    check("root_via_fork does not EXEC on the already-uid-0 path",
          "not sending EXEC" in kroot)
    check("legacy root() refuses the already-uid-0 path too (no EXEC)",
          kroot.count("not sending EXEC") >= 2)
    check("a created-but-unfound landmark is not re-forked",
          "not forking a second landmark" in kroot)
    check("recover.sh rewrites WANT and SIZE as well as H",
          "WANT=$want" in recover and "SIZE_WANT=$size" in recover)
    check("high-scan skips the child's own cred object",
          "childCredPhys" in prog and "child_cred_phys" in sim)

    # --- v39.2 hardening tokens (review 2026-10-26, third pass) ------------
    check("stub op8 checks write(2) through write_full",
          "write_full:" in stub and "bl      write_full" in stub)
    cmd_cap = grab(stub, r"movw\s+r2, #(\d+)\s+@ cmdbuf")
    path_cap = grab(stub, r"movw\s+r2, #(\d+)\s+@ pathbuf")
    check("stub cmdbuf cap == 511 (508-byte command + NUL)",
          cmd_cap == 511, f"got {cmd_cap}")
    check("stub pathbuf cap == 255", path_cap == 255, f"got {path_cap}")
    check("run_root refuses commands over 508 B", "> 508" in run_root)
    check("auto_root refuses buffers over 511 B", "> 511" in auto_root)
    check("write_root refuses paths over 255 B", "> 255" in write_root)
    check("payload caps the Run() redirect file (ulimit -f)",
          "ulimit -f 2048" in prog)
    check("payload's first still-waiting beacon is at 30 s",
          "long lastWaitBeacon = 0" in prog)
    check("payload names the actual node on a failed reopen",
          'fail reopen " + _node' in prog)
    check("server bounds every post-peek read", "conn.settimeout(2.0)" in server)
    check("server keeps output_dropped on shell connect",
          "output_dropped += len(output)" in server)
    check("server refuses a different peer while a shell is attached",
          "a shell from" in server and "is already" in server)
    check("server accepts RSET split across TCP segments",
          'b"RSET".startswith(head)' in server)
    check("server rotates beacons.log", "beacons.log.1" in server)
    check("server only aims tv_sock at op5/op7", "in (5, 7)" in server)
    check("server renders only the deploy assignment lines",
          'r"(?m)^H=@HOST@$"' in server and 'r"(?m)^WANT=@WANT@$"' in server)
    check("deploy.sh keeps its literal NEED_RENDER guard",
          "*@HOST@*|*@WANT@*)" in deploy)

    # --- deploy is a template (structural fix) -----------------------------
    check("deploy.sh H/WANT/SIZE come from the server",
          "H=@HOST@" in deploy and "WANT=@WANT@" in deploy
          and "SIZE_WANT=@SIZE@" in deploy)
    check("deploy.sh refuses an unrendered template", "NEED_RENDER" in deploy)
    check("deploy.sh has a rollback trap", "trap cleanup 0" in deploy and "ROLLBACK=1" in deploy)

    print()
    if FAILS:
        print(f"{FAILS} constant check(s) failed")
        return 1
    print("constant cross-check ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
