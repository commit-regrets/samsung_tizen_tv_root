# DU7170 port notes

Port of the QNX1D root + debloat to a 2024 Samsung DU7170 (Crystal UHD,
Novatek NT72671D SoC, Tizen 9.0, firmware `T-KSU2EDDEUC-0090-REL`).

## Hardware profile

| | |
|---|---|
| Model | UE55DU7170 (2024 Crystal UHD) |
| SoC | Novatek NT72671D |
| Firmware | `T-KSU2EDDEUC-0090-REL-202605141701` |
| Kernel | Linux 5.4.249, ARMv7l **with LPAE** |
| RAM | 1578 MiB (vs. QNX1D's ~4 GiB) |
| Browser | Chromium 120 (same WasmGC build) |
| .NET | 6.0.9 (`/usr/bin/dotnet`) |
| Carrier app | `com.samsung.tv.MultiControl-Service` (same as QNX1D) |
| Physmap node | `/dev/video40` (same; video30/60 available as fallbacks) |

## Kernel constants (measured)

| Constant | QNX1D | DU7170 | Notes |
|---|---|---|---|
| `PHYS_OFF` (VA = PA + off) | `0xA0000000` | `0xBC000000` | different SoC memory layout |
| `init_task` PA | `0x20957180` | `0x0490F2C0` | different build, different link address |
| `O_TASKS` | `0x23C` | `0x23C` | same kernel config |
| `O_PID` | `0x2E8` | `0x2E8` | same |
| `O_TGID` | `0x2EC` | `0x2EC` | same |
| `O_RPARENT` | `0x2F0` | `0x2F0` | same |
| `O_RCRED` | `0x3F4` | `0x3F4` | same |
| `O_CRED` | `0x3F8` | `0x3F8` | same |
| `O_COMM` | `0x400` | `0x400` | same |

The struct offsets are identical (same kernel version and config), but
`PHYS_OFF` and `init_task` are completely different — the Novatek SoC uses a
different physical memory base than the QNX1D's `0x20000000`.

## Gate results

1. **Browser** — Chromium 120 with WasmGC, same build as QNX1D. Pass.
2. **Physmap** — `/dev/video40` accepts arbitrary pfn, same as QNX1D. Pass.
3. **Constants** — measured via RAM dump. All struct offsets match; only
   `PHYS_OFF` and `init_task` differ. Pass.
4. **Carrier** — same `com.samsung.tv.MultiControl-Service` on writable `/opt`,
   same SMACK label, same `.dll` replacement procedure. Pass.

## Differences from QNX1D

- **LPAE present**: DU7170 has `lpae` in CPU features (QNX1D does not).
  No impact on the physmap technique — the V4L2 mmap path still works
  with 32-bit pfn values.
- **Less RAM**: 1.6 GiB vs ~4 GiB. Task/cred objects are in a smaller
  physical range. No search-boundary issues encountered.
- **Remote input device**: `/dev/input/event4` ("Smart Control") vs
  QNX1D's `/dev/input/event6`. The remote daemon config must specify the
  correct event device per model.
- **Root shell prompt**: `du7170#` vs `QNX1D#`. The health check script
  and root shell tool match on the model-specific prompt.
- **3 apps missing**: The QNX1D debloat-apps list has 73 entries; 3 are
  not installed on DU7170 (70 actually present). The payload's
  `ReassertDebloatApps()` handles this gracefully (per-app query loop).

## Payload adaptations

`payload-du7170/Program.cs` is a standalone copy of the QNX1D payload with:

- Updated kernel constants (`PHYS_OFF`, `INIT_TASK`)
- Log file name changed to `.dsh_du7170.log`
- Prompt changed to `du7170#`
- Five enforcement threads: masks, apps, hosts, sethome, cec-standby-ignore
- Deadlock-safe `Run()` helper (reads stdout/stderr on separate threads)

## HDMI-CEC standby ignore

The DU7170 has the same `org.tizen.tv.hdmicec` dbus service. Calling
`IgnoreCECStandby(1)` prevents the TV from switching away from HDMI when
a connected device (e.g. PS5) sends a CEC standby command. This is session-only
(the service resets at boot), so the payload re-applies it each boot.

## Files

| File | Purpose |
|---|---|
| `payload-du7170/Program.cs` | Boot payload source |
| `payload-du7170/BootPayload.csproj` | .NET 6.0 project |
| `server/du7170.dll` | Pre-built payload DLL |
| `tools/root_du7170.py` | Root shell client |
| `tools/tv_health_du7170.py` | 14-check health script |
| `remote/remote-map-du7170.conf` | Remote daemon config (event4, observe mode) |
