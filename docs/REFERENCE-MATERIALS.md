# Reference materials — get them yourself

This repository deliberately ships **no Samsung firmware, no kernel images and
no vendor sources**. Everything the research and porting work needs is freely
available from the sources below; download the matching files for **your own
model** and you can reproduce every analysis step in this toolkit
(`docs/PORTABILITY.md` says what to re-measure per model).

## Samsung firmware (the TV's own update image)

- **Where:** samsung.com → Support → your exact model → Manuals & Downloads →
  Firmware. Samsung distributes these packages freely to owners (the update is
  the same file the TV's USB-update flow installs). Third-party mirrors of the
  same official servers exist (e.g. SamFw / FUS-based downloaders), but the
  manufacturer page is the canonical source.
- **What you get:** a `.zip` per region/model containing the kernel image
  (`uImage`), rootfs images and updater metadata. Extract with any unzip tool;
  the images inside are standard formats (CRAMFS/SQUASHFS/ext2 variants).
- **What it is used for here:** measuring the running kernel image (the
  `ee4400eb…` signature, `init_task`, build strings), extracting `.config`
  facts (VMSPLIT_3G, HIGHMEM, SMACK, no LPAE/KASLR), and diffing a candidate
  firmware before touching a TV.

## GPL kernel source

- **Where:** Samsung publishes GPL sources for their TVs on
  [opensource.samsung.com](https://opensource.samsung.com). The exact release
  name to search for is shown on the TV itself: **Settings → Support → Open
  Source License** lists it. Vanilla 5.4 is at
  [kernel.org](https://cdn.kernel.org/pub/linux/kernel/v5.x/).
- **What it is used for here:** the DWARF/struct story. `tools/dwarf_offsets.py`
  reads a DWARF-equipped vmlinux; the fingerprint gate (`--check`) tells you
  whether a build you made matches the hand-measured offsets (comm `+0x400`,
  cred `+0x3F8`, real_cred `+0x3F4`, tasks `+0x23C` …) — if it matches, every
  other offset from the same build is trustworthy for your unit.
- **How to get a DWARF vmlinux:** build the vanilla kernel for your
  architecture (`CONFIG_DEBUG_INFO=y`) with the config facts extracted from
  the firmware; you do not need Samsung's exact tree for struct layout — the
  fingerprint gate is what makes a near-miss build usable or not.

## QEMU rehearsal (no TV needed)

- **Where:** QEMU itself from your distro (`qemu-system-arm`); a Debian
  container with `gcc-arm-linux-gnueabi` plus a `vexpress` defconfig is enough
  to boot a 5.4 kernel you built above.
- **What it is used for here:** rehearsing payload changes offline
  (`high_memory`/`max_low_pfn` reads, task-list walks) before spending a TV
  boot. `tools/listwalk.py` runs against any RPC-shaped memory source, the QEMU
  guest included, and its planted-memory self-test needs nothing at all
  (`python tools/listwalk.py`).

## PC-side tool dependencies

All pip/apt-installable; nothing vendor-specific:

| Tool | Get it from | Used by |
|---|---|---|
| Python 3.10+ | python.org (or distro) | everything |
| keystone-engine, capstone | `pip install -r tools/requirements.txt` | `build_physrpc.py` (stub rebuild) |
| pyelftools | same requirements file | `dwarf_offsets.py` |
| .NET SDK 6+ (10.x pinned via `payload/global.json`) | dotnet.microsoft.com | rebuilding the boot payload |
| Wireshark/tshark (optional) | wireshark.org | network forensics on the LAN |

## Browser-chain upstream

The V8/WasmGC exploit chain is third-party; see `NOTICE.md` for the upstream
public project it derives from (CVE-2024-2887, Chromium 120 era). That upstream
repository is the place to read about the browser-side primitive; this toolkit's
contribution is everything after the renderer read/write.

## Legal note

Firmware and GPL sources are copyrighted by their owners; download them for
hardware you own and follow the licenses (GPL sources carry their own terms).
This toolkit's `LICENSE` covers original work only.
