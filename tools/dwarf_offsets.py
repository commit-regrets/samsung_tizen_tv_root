#!/usr/bin/env python3
"""Print member offsets for kernel structs from a vmlinux with DWARF.

The running TV kernel ships without symbols, and porting to another model means
the hand-measured offsets (comm +0x400, cred +0x3F8, ...) cannot be reused
blindly.  A DWARF-equipped build of the SAME kernel config answers every offset
at once; the known-measured fields act as the fingerprint: if they match, the
rest of the layout is trustworthy too.

    python tools/dwarf_offsets.py                       # default vmlinux, default structs
    python tools/dwarf_offsets.py -v /path/vmlinux task_struct mm_struct
    python tools/dwarf_offsets.py --check               # fingerprint gate for test_all.py

--check exits 0 only when every fingerprint field (the TV-measured offsets in
FP) is present with the measured value in the given vmlinux - the condition
under which sim-derived offsets may be substituted for measurements on a new
unit.  Requires pyelftools (pip install -r tools/requirements.txt).

Ported from the research tree (recon/dwarf_offsets.py, 2026-10-26); the sim
vmlinux it was written against is research/sim/out/pontusml.vmlinux in the
wider samsungtv workspace.
"""
import argparse
import sys
from pathlib import Path

# The TV-measured fields: a vmlinux may stand in for the TV kernel only while
# every one of these matches (AGENTS.md §2 / docs/PORTABILITY.md).
FP = {
    "task_struct": {"comm": 0x400, "cred": 0x3F8, "real_cred": 0x3F4},
}
DEFAULT = ["task_struct", "task_smack", "smack_known"]
WANT = {
    "task_struct": ["comm", "cred", "real_cred", "real_parent", "parent", "tasks",
                    "security", "pid", "tgid"],
    "task_smack": ["smk_task", "smk_forked"],
    "smack_known": ["list", "smk_known", "smk_secid", "smk_rules"],
}
# Default: the QEMU sim build from the research workspace, when present.
SIM_VMLINUX = (Path.home() / "Documents/projects/samsungtv"
               / "research/sim/out/pontusml.vmlinux")


def die_name(die):
    if "DW_AT_name" not in die.attributes:
        return None
    try:
        return die.attributes["DW_AT_name"].value.decode("latin-1")
    except Exception:
        return None


def struct_offsets(dwarfinfo, wanted):
    """{struct: {member: offset}} for the first DW_TAG_structure_type of each
    wanted name.

    Kernel DWARF declares its structs at the CU top level (verified on the sim
    vmlinux: task_struct in CU 1, task_smack/smack_known in CU 365), so walking
    only direct children is enough - and it turns --check from minutes (every
    DIE of a 123 MB vmlinux) into well under a second.  Stop as soon as every
    wanted struct is found.
    """
    found = {}
    for cu in dwarfinfo.iter_CUs():
        for die in cu.get_top_DIE().iter_children():
            if die.tag != "DW_TAG_structure_type":
                continue
            nm = die_name(die)
            if nm not in wanted or nm in found:
                continue
            members = {}
            try:
                for child in die.iter_children():
                    if child.tag != "DW_TAG_member":
                        continue
                    mn = die_name(child)
                    loc = child.attributes.get("DW_AT_data_member_location")
                    if mn and loc is not None:
                        members[mn] = loc.value
            except Exception:
                pass
            if members:
                found[nm] = members
        if len(found) == len(wanted):
            break
    return found


def report(path, names):
    from elftools.elf.elffile import ELFFile
    with open(path, "rb") as fh:
        elf = ELFFile(fh)
        if not elf.has_dwarf_info():
            print(f"no DWARF in {path}")
            return 1
        found = struct_offsets(elf.get_dwarf_info(), set(names))
    rc = 0
    for nm in names:
        if nm not in found:
            print(f"[!] {nm}: not found")
            rc = 1
            continue
        members = found[nm]
        print(f"=== {nm} ({len(members)} members parsed) ===")
        for k in WANT.get(nm, list(members)):
            if k in members:
                print(f"    {k:14s} +{members[k]:#06x}")
            else:
                print(f"    {k:14s} (absent)")
    return rc


def do_check(path):
    """Fingerprint gate: every TV-measured offset must match the vmlinux."""
    from elftools.elf.elffile import ELFFile
    with open(path, "rb") as fh:
        elf = ELFFile(fh)
        if not elf.has_dwarf_info():
            print(f"check: no DWARF in {path}")
            return 1
        found = struct_offsets(elf.get_dwarf_info(), set(FP))
    ok = True
    for struct, fields in FP.items():
        members = found.get(struct)
        if not members:
            print(f"FAIL {struct}: type not found")
            return 1
        for field, want in fields.items():
            got = members.get(field)
            good = got == want
            ok = ok and good
            print(f"{'PASS' if good else 'FAIL'} {struct}.{field} "
                  f"= {got:#x}" + ("" if good else f" (TV measures {want:#x})"))
    print("fingerprint:", "MATCH - sim-derived offsets are usable for this unit"
          if ok else "MISMATCH - measure this kernel by hand")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-v", "--vmlinux", type=Path, default=None,
                    help="vmlinux with DWARF (default: the research sim build)")
    ap.add_argument("--check", action="store_true",
                    help="validate the TV-measured fingerprint, exit 1 on drift")
    ap.add_argument("structs", nargs="*", default=DEFAULT)
    argv = ap.parse_args()
    path = argv.vmlinux
    if path is None:
        if SIM_VMLINUX.exists():
            path = SIM_VMLINUX
        else:
            print("no --vmlinux given and the sim build is not present at "
                  f"{SIM_VMLINUX}")
            return 2
    if not path.is_file():
        print(f"not a file: {path}")
        return 2
    try:
        import elftools  # noqa: F401
    except ImportError:
        print("pyelftools missing (pip install -r tools/requirements.txt)")
        return 77 if not argv.check else 1
    return do_check(path) if argv.check else report(path, argv.structs or DEFAULT)


if __name__ == "__main__":
    sys.exit(main())
