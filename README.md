# Samsung Tizen 9 TV Root — Research Toolkit

Unofficial security research on a 2024 Samsung Neo QLED running **Tizen 9**.
The exploit chain needs no sdb, no developer mode, no firmware flashing: the TV
is rooted from its own browser, and the root is made persistent through a stock
on-boot service app.

| | |
|---|---|
| Test unit | 2024 Neo QLED, QNX1D series (QTV T09 platform) |
| Firmware | `T-PTMxxxx` (01400) |
| Kernel | Linux 5.4.249, ARM32 (VMSPLIT_3G + HIGHMEM, no LPAE), `PAGE_OFFSET 0xC0000000`, `PHYS_OFFSET 0x20000000` |
| Browser | Chromium 120.0.6099.5 (`SamsungBrowser/7.0`) |
| Root | `uid=0`, `CapEff=0x3fffffffff` |
| Persistent payload | repo **v47** (current md5/size in the `AGENTS.md` state row); `payload_backup.dll` keeps the previous build |
| Root channel | TCP **31337** on the TV, line protocol, replies end with `__END__` |

## Quick start

```powershell
pwsh -File .\root.ps1 -TvIp <tv-ip>        # root the TV
pwsh -File .\uninstall.ps1 -TvIp <tv-ip>   # restore stock
```

`root.ps1` runs on the PC and drives everything: it starts the port-80 server,
roots the browser stub, installs the boot payload, and waits for the root channel
after the reboot. Two steps stay on the TV remote, and it prompts for both:

1. open the printed `http://<pc-ip>/index.html` and wait for `RUNNING`;
2. power-cycle the TV once the deploy is verified.

Then:

```powershell
python tools\root_shell.py "id" <tv-ip>   # talk to the TV's root channel
```

Every option, the exact prompts, expected output, the host-IP caveat and the
manual fallback: [`docs/USAGE.md`](docs/USAGE.md).

## How it works

1. **Browser RCE** — CVE-2024-2887 (WasmGC type confusion) in Chromium 120 gives
   arbitrary read/write and ARM shellcode execution inside the renderer.
2. **Physmap** — the V4L2 codec nodes (`/dev/video40`/`30`/`60`) accept an
   attacker-chosen `vm_pgoff` in `mmap()` and pass it to `remap_pfn_range()`
   unvalidated: arbitrary physical memory read/write from an unprivileged
   process (uid 5001, group `video`). Exclusivity is per instance: the
   payload retries `video40` on `EBUSY` and falls back to `video30`/`video60`
   only on `ENOENT`/`ENODEV` — never cycle nodes on busy.
3. **Root** — find the kernel Image and `init_task` in physical memory, locate our
   own task through a forked child's `real_parent`, and zero the credentials.
4. **Persistence** — replace the IL assembly of a stock `app_onboot` service with
   a .NET payload that repeats the physmap/cred patch at every boot, closes its
   node and serves a root command channel on TCP 31337.

No GPU CVE, no kernel exploit, no signed module. The physmap is the interesting
part; the stage-by-stage writeup with the measured constants is
[`docs/EXPLOIT.md`](docs/EXPLOIT.md).

## Kernel analysis — firmware file first, TV dump when rooted

The kernel you analyse comes from two sources, in order: the **OTA package**
downloadable before rooting (strip the u-boot header off its `uImage`), and
after rooting the **TV itself** — flash partition or live RAM — via
`tools/dump_kernel_chunked.py` and `tools/dump_kernel_ram.py`. Key rule:
trust RAM, not the firmware file, for any offset that goes into shellcode —
the two are usually **different builds** (the TV may run a newer build than
the package you downloaded, and each build links its sections at slightly
different addresses; it is not a runtime relocation). Full procedure,
measured examples and the flash-vs-RAM build differences:
[`docs/KERNEL-DUMPS.md`](docs/KERNEL-DUMPS.md).

## After rooting — debloat

The package-inventory / disable-list work (QNX1D classification, apply and
restore tooling, measured resource budget) lives in this repository under
[`debloat/`](debloat/README.md). It consumes this toolkit's root channel as
its only dependency. The payload re-asserts the durable service masks at every
boot on its own, and `root.ps1` runs a debloat health check (`tools/tv_health.py`)
against `debloat/registry.tsv` after a deploy.

## Documentation

| Document | Contents |
|---|---|
| [`docs/USAGE.md`](docs/USAGE.md) | running it: options, prompts, expected output, uninstall detail, recovery |
| [`docs/EXPLOIT.md`](docs/EXPLOIT.md) | the chain stage by stage, with the firmware-specific constants |
| [`docs/KERNEL-DUMPS.md`](docs/KERNEL-DUMPS.md) | extracting the kernel: OTA file pre-root, flash/RAM dumps post-root, flash-vs-RAM build differences, `__ksymtab` symbol recovery |
| [`docs/ROOT-METHODS.md`](docs/ROOT-METHODS.md) | every root/persistence method evaluated and the one that won |
| [`docs/FAILED.md`](docs/FAILED.md) | what did not work and why — reads like a list of dead ends, saves weeks |
| [`docs/BOOT-REGRESSION-SMACK.md`](docs/BOOT-REGRESSION-SMACK.md) | the subtlest bug in the project: a wrong SMACK label made the app die before `Main` |
| [`docs/PORTABILITY.md`](docs/PORTABILITY.md) | another Tizen 9 TV: the four gates, what to re-measure, a step-by-step port |
| [`docs/SERVER-HOSTING.md`](docs/SERVER-HOSTING.md) | the PC-side server: how it must run, the silent-death trap, firewall, logs |
| [`docs/SCRIPT-REVIEW.md`](docs/SCRIPT-REVIEW.md) | production-readiness audit of the scripts |
| [`docs/TESTING.md`](docs/TESTING.md) | the test layers, offline and on-TV, and what each catches |
| [`docs/LOGGUIDE.md`](docs/LOGGUIDE.md) | every beacon and tool error decoded, with next steps |
| [`docs/REFERENCE-MATERIALS.md`](docs/REFERENCE-MATERIALS.md) | where to download firmware / GPL sources / sim tooling for your own model |
| [`docs/REVIEW-HISTORY.md`](docs/REVIEW-HISTORY.md) | closed review findings and their evidence (archive) |
| [`docs/OPEN-ISSUES.md`](docs/OPEN-ISSUES.md) | current state, pending work, and the closed review/pass history |
| [`AGENTS.md`](AGENTS.md) | hand-off: tools, procedure, verification, traps, recovery |
| [`CHANGELOG.md`](CHANGELOG.md) | dated history of what changed and why |
| [`SECURITY.md`](SECURITY.md) | the unauthenticated 31337 backdoor, scope, reporting, legal |
| [`NOTICE.md`](NOTICE.md) | third-party attribution; which files are not relicensed |
| [`LICENSE`](LICENSE) | MIT for the original work (third-party files excluded) |

## Repository layout

```
root.ps1, uninstall.ps1     PC entry points (PowerShell)
payload/                    boot payload source (.NET 6, Program.cs)
server/                     port-80 server, exploit page, TV-side deploy scripts
tools/                      physmap client, kernel helpers, build scripts
docs/                       the documents above
AGENTS.md                   hand-off notes
LICENSE, NOTICE.md          license + third-party attribution
SECURITY.md                 backdoor/scope/reporting
```

The whole toolkit is committed, so a clone runs without any other working tree.
`server/payload.dll` is included on purpose (byte-identical to the build output)
so the toolkit works without a .NET SDK. Runtime logs and build output are
git-ignored and never served over HTTP.

## Requirements

- The same TV family and firmware generation — see
  [`docs/PORTABILITY.md`](docs/PORTABILITY.md) before trying another model.
- A PC on the same LAN, able to receive TCP/80 from the TV and reach TCP/31337
  on it. Nothing is committed with a real address: the deploy script, the
  exploit page and the payload all learn the PC's address at run time.
- Python 3 on the PC. On Windows the server must run under an interpreter path the
  firewall allows (see [`docs/SERVER-HOSTING.md`](docs/SERVER-HOSTING.md)).
- .NET SDK only if you rebuild the boot payload — `payload/global.json` pins
  10.0.x (`rollForward: latestPatch`); the project targets net6.0, which the
  pinned SDK still builds (an EOL warning is expected).

Reference material (firmware, GPL kernel sources, QEMU tooling) is not
bundled; [docs/REFERENCE-MATERIALS.md](docs/REFERENCE-MATERIALS.md) lists
where to download each piece for your own model.

## Porting to another Tizen 9 TV

The method is portable; this build is not. `payload.dll` hardcodes this kernel's
`PHYS_OFFSET`, `init_task` and four `task_struct` offsets, and the browser chain
is specific to Chromium 120. The short version:

1. **Browser gate** — serve `server/probe.html` (safe; it executes nothing) and
   open it on the TV. You need Chromium ~120 with WasmGC; otherwise this CVE does
   not apply.
2. **Physmap gate** — get code execution as `owner` (browser chain), then prove
   an arbitrary-pfn mmap on one of the TV's `/dev/video*` nodes with
   `tools/physmap.py` / `tools/physrpc.S`. If the offset is validated, stop.
3. **Constants** — measure `PHYS_OFFSET`, the Image base, `init_task`, and the
   `tasks`/`comm`/`cred`/`real_parent` offsets. Edit the constants in
   `payload/Program.cs`; re-check the read-reliability limit below.
4. **Carrier** — find a `dotnet-inhouse`, `app_onboot` app on writable `/opt`
   whose files you can rewrite under its own SMACK label. Set its app id/paths
   in `server/deploy.sh`, `server/uninstall.sh`, and `server/recover.sh`.
5. **Build, deploy, verify** — `dotnet build -c Release -o out`, copy the artifact
   over `server/payload.dll` (the deploy gate is rendered from it, so there is no
   `WANT=` to edit), deploy via `root.ps1`, then cold boot. Attempt 2 is the
   expected floor.

**Read-reliability limits found on the test unit:** the linear map ends at
VA `0xF0400000` (above it is vmalloc/module space — no valid translation),
and a 156 MiB no-map carve-out (VA `0xE0000000`–`0xE9C00000`) returns
device-buffer content, not kernel memory — task/cred objects never live
there. The top 104 MiB below `0xF0400000` does read. Past PA `0x46000000`
the browser stub's video30 wedged during measurement — potentially
system-fatal with hours of delay; never read there except a planned
diagnostic. When porting, test a known low page and a known high page on the
new model before trusting `Kptr`; all successful cred patches here were below
`0xE0000000`, and it affects how you interpret "not found". Full measurement:
[`docs/OPEN-ISSUES.md`](docs/OPEN-ISSUES.md) item 2.

Full gates, measurement recipes, and a file-by-file porting checklist:
[`docs/PORTABILITY.md`](docs/PORTABILITY.md).

## Safety and legal

- Use only on hardware you own. Rooting voids the warranty, and a bad write to the
  wrong physical page can crash or brick the set.
- **The root channel on 31337 is an unauthenticated LAN root shell** (the allowlist
  is the only filter). Never expose it to the internet or a network you do not
  control. See [`SECURITY.md`](SECURITY.md).
- The boot payload opens a V4L2 physmap node (`/dev/video40`) while it roots
  and closes it right after. The node is exclusive per instance, so the payload
  waits (retries) while anything else — e.g. an open exploit page — holds it,
  and only falls back to `video30`/`video60` if the node is gone.
- Keep the stock `mcs_orig.dll` / `mcs_ni_orig.dll` backups and leave TV
  auto-update **off** — an OTA can replace the app and undo persistence.
- No Samsung firmware, proprietary images or dumps are distributed here.
- Provided as-is, without warranty, for security research and interoperability on
  devices you own. Original code is MIT licensed ([`LICENSE`](LICENSE)); the
  third-party browser-chain files are attributed in [`NOTICE.md`](NOTICE.md) and
  are not relicensed by that file.

## Acknowledgements

Standing on public work by:

- **hdbreaker** — the `samsung-smarttv-tizen-9-chromium-120-v8-rce` browser chain
  (CVE-2024-2887 + WasmGC) that gets code execution on Tizen 9.
- **levkropp** — the boot-agent shape (on-boot app + V4L2 physmap).
- **califio / MADBugs** — the `/dev/ntksys` physmap-to-cred technique on older
  Samsung TVs, the direct ancestor of this approach.
- **DemonKingSwarn**, **chris-ritsen**, **invaliddayta** — Tizen root/debloat
  research and tooling.
- **theubusu (unixtract)**, **gtors (vdfs-unpack)** — firmware decryption and
  VDFS4 extraction used during the research.

Samsung and Tizen are trademarks of Samsung Electronics. This project is
unofficial and not affiliated with or endorsed by Samsung.
