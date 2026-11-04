"""Dump the running kernel from TV RAM via the physmap RPC (read-only).

Wraps physmap.py dump for the standard kernel-RAM window. The physmap stub
must be alive (browser payload running, gateway on 127.0.0.1:9998) — see
physmap.py verify. Unlike tools/dump_kernel_chunked.py (which reads the flash
partition over the 31337 root channel), this reads physical RAM, so it sees
the kernel as the TV is actually executing it (post-boot patches included).

Usage:
  python tools/dump_kernel_ram.py [out-file]
  python tools/dump_kernel_ram.py -h | --help

No TV IP is needed: the physmap lane pairs through the PC-side gateway
(127.0.0.1:9998, TVPHYS_GATEWAY to override) and the stub must already be
alive — see physmap.py verify.

Default: ghidra/Image_TV_running_full.bin
Window:  phys 0x20008000, length 0xA20000 (entry .. .bss end)
Safety:  reads stay under 0x46000000 — past it the stub wedges (the
         video40/physmap read-band note in AGENTS.md section 2); the tool is
         read-only, TV state untouched.

This tool performs a LIVE dump the moment it runs — there is no dry-run —
so flags are rejected rather than swallowed as filenames (a stray
"--help" once triggered a real dump).
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYS = "0x20008000"
LENGTH = "0xA20000"

args = [a for a in sys.argv[1:]]
if "-h" in args or "--help" in args:
    print(__doc__)
    sys.exit(0)
bad = [a for a in args if a.startswith("-")]
if bad:
    sys.exit("unknown option(s): %s\nusage: dump_kernel_ram.py [out-file] "
             "(-h for help)" % ", ".join(bad))
out = args[0] if args else os.path.join(
    ROOT, "ghidra", "Image_TV_running_full.bin")

sys.exit(subprocess.call([
    sys.executable, os.path.join(ROOT, "tools", "physmap.py"),
    "dump", PHYS, LENGTH, out,
]))
