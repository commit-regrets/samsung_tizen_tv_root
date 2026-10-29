# QNX1D resource math — measured, not estimated (2026-10-27) — measured, not estimated (2026-10-27)

Method: per-process `VmRSS` + `readlink /proc/<pid>/exe` dumped over the root
channel (408 processes at idle), each process attributed to its owning package
via the `/opt/usr/apps/<pkg>/` path, then rolled up with the Vetro roles.
Caveat: sum-of-RSS double-counts shared library pages across processes, so
treat these as **upper bounds**; the honest number comes from an A/B
measurement — the same dump after the disable run, diffed.

Baseline at idle: `MemAvailable 319 MB` of 1,816 MB total (this launcher runs
with a small margin by design).

Idle RSS upper bounds by group:

| Group | Idle RSS | Note |
|---|---|---|
| tracking (batch 1) | **39.3 MB** | `pisa-service` 21.8 MB alone — it *does* run at idle; the earlier busybox-ps grep undercounted (ps shows 228 of 408 processes) |
| optional/voice | **130.8 MB** | biggest single area: `voice-app` 21.1, `aov-dashboard` 19.1, wake-word engines |
| optional/samsung | **94.9 MB** | account/SmartThings/store pieces |
| optional/sharing | **58.6 MB** | AirPlay alone is 39.5 MB |
| optional/ambient | **28.0 MB** | `art-app` 28.0 |
| optional/devices | **15.9 MB** | Bluetooth framework — remote/audio risk |
| unused/hotel (batch 2) | ~0 | nothing runs at idle |
| optional/media (excluded) | 104.8 MB | **not counted**: Netflix (62.9), browser (28.3) stay per owner choice |

Scenarios (upper-bound sum-RSS; expect roughly 40–60% of it as real freed
pages once shared libraries are accounted):

| Scenario | Sum-RSS | Realistic |
|---|---|---|
| Batch 1 only (tracking) | 39 MB | 15–25 MB |
| + voice + ambient + samsung + sharing + unused (media/devices kept) | ~352 MB | ~150–210 MB |
| + devices too | ~368 MB | ~160–220 MB |

Against `MemAvailable 319 MB`, the aggressive-minus-media scenario roughly
doubles the idle headroom. Non-RAM gains: no analytics/ad demand-starts during
viewing, fewer background wakeups and uploads, and (for `app_onboot` members
like `targeted-ad-service`) less boot-time work. The A/B dump after the real
run replaces the 40–60% guess with a measured number.

