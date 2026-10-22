# Portability — running this on a different Tizen 9 TV

This toolkit was built against **one** unit: 2024 Neo QLED (QNX1D / QTV T09
platform), firmware `T-PTMDDEUC 01400`, kernel 5.4.249 ARM32 LPAE, Chromium
120.0.6099.5. Everything model-specific below was *measured* on that unit.

Network addresses are *not* in that list: the page rewrites the shellcode callback
from the host that served it, `root.ps1` detects the PC's address, and the payload
reads the beacon target from `share/rootchan.host`. Only the TV's address and the
PC's address matter, and both are supplied at run time.

The **method** is portable. The **constants, paths and carrier app are not.**
This document is the order in which to test a foreign unit, and what to expect to
re-measure.

## The four gates, in dependency order

| # | Gate | If it fails |
|---|---|---|
| 0 | Browser still runs Chromium ~120 with WasmGC | Nothing else matters — no code execution, stop |
| 1 | A V4L2 codec device accepts an arbitrary `vm_pgoff` in `mmap` | No arbitrary physical R/W — the whole approach is dead on that model |
| 2 | Kernel constants (base, `init_task`, struct offsets) can be measured | Work: they are measurable given gate 1 |
| 3 | A stock dotnet-inhouse `app_onboot` app on writable `/opt` exists | Root works per boot only, via the host watchdog (no persistence) |

Gates 0 and 1 are the real risks. Gate 2 is labour. Gate 3 is usually findable.

## Gate 0 — is the browser still vulnerable? (5 minutes, zero risk)

Serve a **probe page**, not the exploit: `server/probe.html` posts the user agent
and WebAssembly/WasmGC support to `server/logs/tv/` without running anything.

```powershell
pwsh -File .\root.ps1 -ServeOnly      # or just run the server directly
```

Open `http://<pc-ip>/probe.html` in the TV browser, then read the newest
`server/logs/tv/tv_output_*.txt`. You want:

* UA containing `Chrome/120.` (CVE-2024-2887 is specific to that WasmGC
  implementation; a store-updated browser is the usual reason this dies)
* `WASM_GC=yes`
* and `TIZEN=` if the page could read it

If the browser is newer, this entire chain does not apply — look at current
Chromium/Tizen CVEs instead, and keep the physmap idea for later (it only needs
*some* code execution, not this particular CVE).

## Gate 1 — does the physmap exist on that model?

Once you have any code execution as the TV's `owner` user:

```sh
id                                  # must include the video group (44 here)
ls -l /dev/video*                   # note every node, not just video40
```

Then the actual test: `mmap()` one of those devices with a `vm_pgoff` pointing at
a physical page you can predict, and read it. On this unit `/dev/video40` maps
whatever pfn you ask for and the kernel image appears at phys `PHYS_OFFSET +
0x8000`. `tools/physmap.py` + `tools/physrpc.S` are the reference implementation;
the only model-specific value is the device path and the group.

If the driver validates the offset (or the node is absent), gate 1 fails. The
documented fallbacks in `docs/ROOT-METHODS.md` (`/dev/tzmem`, GPU CVEs, the
installer write primitive) each failed or were closed on this unit — do not
assume they work elsewhere.

## Gate 2 — re-measure the kernel constants

These are the values that are *specific to the kernel build* and must be redone:

| Constant | This unit | How to re-measure |
|---|---|---|
| `PHYS_OFFSET` | `0x20000000` | ARM32 LPAE: usually `0x20000000` on 5.4 Samsung TV kernels; confirm with the Image signature |
| Kernel Image phys | `0x20008000` | `PHYS_OFFSET + 0x8000`; find by signature scan |
| `init_task` | `0xC0957180` | via `__ksymtab` (kallsyms is absent on retail builds) — see `tools/` |
| `task_struct`: `tasks` / `comm` / `cred` / `real_parent` | `0x23C` / `0x400` / `0x3F8` / `0x2F0` | GPL source + `.config`, or DWARF from a matching build — `tools/dwarf_offsets.py` |
| `cred.security` (SMACK blob) | `+0x64` | verify live by the self-referential `smk_rules` list trick (`docs/FAILED.md`) |

Two rules learned the hard way:

* **Never trust an offset from a different build without validating it in place.**
  Four offsets matching proves the build is the same class; a later member
  (`cred.security`, `task_struct.security`) can still differ by configuration.
* **A `smack_known` (or any kmalloc'd struct) may be in vmalloc space**, where
  `phys = va - 0xA0000000` does not apply. If reads return implausible data,
  check whether the address is above `0xE0000000` before concluding "no match".

## Gate 3 — find a persistence carrier

An eligible carrier is an app that is all of:

1. `dotnet-inhouse` (IL assemblies — native apps need different work),
2. `app_onboot='true'` (starts every boot by itself),
3. on the writable `/opt` partition,
4. with a `bin/` writable once you carry the app's own SMACK label.

Enumerate from a root shell on the TV (this is what `enum_carriers.sh` in the
lab tree does): list `/opt/usr/apps/*`, read each manifest for
`prefer_dotnet_aot` and the launch entry, then check `chsmack`/`ls -lZ` labels.
`com.samsung.tv.MultiControl-Service` happened to satisfy all four here.

The trick that makes the write legal is generic SMACK, not model-specific:

```sh
echo -n "User::Pkg::<appid>" > /proc/self/attr/current   # root + full caps
```

and the app directory is usually `User::Home` **transmute=TRUE**, so files you
create while carrying the app label inherit it (no `chsmack` needed). Verify the
label actually took before writing.

## What transfers unchanged

* The design: browser RCE → physmap → cred patch → on-boot app payload.
* The payload algorithm (`fork` a landmark, follow the child's `real_parent`,
  patch that cred) — only the four offsets change.
* The whole `server/` tree (HTTP + RPC gateway + page harness), the root-channel
  protocol on 31337, `server/deploy.sh`, `server/recover.sh` (app id is a
  variable).
* The traps list in `docs/FAILED.md` — read it before touching a new unit; it is
  the accumulated cost of this one.

## What definitely does not transfer

* The six browser ROP constants (`ANCHOR_OFS`, `GOT_MPROTECT`, `PIVOT_OFS`,
  `ARGS_OFS`, `L_MPLR`/`L_MPPC`, the shellcode's callback address). They are tied
  to a specific `libchrome` build; re-derive them if the browser differs.
* `init_task`, the kernel physical base, and every `task_struct`/`cred` offset.
* The carrier app id, its SMACK label, and whether it has an AOT image.
* `payload.dll` itself is **not** portable across kernels: it hardcodes
  `PHYS_OFFSET`, `init_task`, and the task/cred offsets. Rebuild it
  (`payload/Program.cs`, .NET SDK 6+) with the new values, or make those values
  a first-run discovery step.

## A realistic expectation

Same platform family (2024 QTV T09 sets, same firmware generation): good odds —
the physmap is a driver property of the platform, and the app layout is shared.
Different SoC generation or 2025+ firmware: expect the browser gate to fail
first, and assume the mmap validation may be fixed. Treat any foreign unit as
"test on hardware you can afford to brick", and keep the stock DLL/AOT backups
that `deploy.sh` makes before writing.
