# minimal remote daemon

A tiny root daemon for the Samsung QNX1D remote. It reads the physical remote
event device and either **logs** keys (`observe`) or **remaps** them
(`filter`), forwarding every unmapped key through `/dev/uinput`.

This is the remote half of the future Home-screen replacement; it does **not**
change `home_appid`, install a UI, or start at boot yet.

The `EVIOCGRAB` + `/dev/uinput` approach follows Vetro's
`SamsungTvRemoteInputAgent` (MIT/public domain) as a design reference; this is
an independent minimal implementation.

## Tested

On 2026-11-05, the QNX1D remote is `/dev/input/event6`
(`Smart Control 2016`). Confirmed codes:

| Button | Code |
|---|---:|
| Home | 63 |
| Back | 1 |
| OK / Enter | 28 |
| Up / Down / Left / Right | 103 / 108 / 105 / 106 |
| Settings **and** color | 140 (`XF86More`) |
| Volume + / − / Mute | 68 / 67 / 66 |
| Channel + / − | 88 / 87 |

Observe mode logged `63`, `28`, `1`; filter mode with only `140` mapped
launched `org.tizen.menu` and forwarded Home/OK/Back normally.

## Build

```sh
dotnet build remote/RemoteDaemon.csproj -c Release -o remote/out
```

Output: `remote/out/RemoteDaemon.dll` + `RemoteDaemon.runtimeconfig.json`.
The TV has `/usr/bin/dotnet` and `/dev/uinput`; no extra runtime is needed.

## Config

Copy [`remote-map.conf.example`](remote-map.conf.example) to
`/opt/usr/data/remote-map.conf`:

```ini
device=/dev/input/event6
mode=observe
# map.140=launch:org.tizen.menu
```

`mode=observe` only logs; keys still work normally.
`mode=filter` grabs the device; only mappings are withheld, everything else is
forwarded through `uinput`.

Only `launch:` actions are implemented; app IDs are limited to
`A-Za-z0-9_.-`.

## Run on the TV

Copy the two build files to `/opt/usr/data/remote/`, then:

```sh
systemd-run --unit=remote-daemon /usr/bin/dotnet \
  /opt/usr/data/remote/RemoteDaemon.dll \
  --config /opt/usr/data/remote-map.conf \
  --log /opt/usr/data/remote-daemon.log
```

Stop with:

```sh
systemctl stop remote-daemon
```

The daemon logs to `/opt/usr/data/remote-daemon.log`.

## Safety

- Start with `observe`. No grab; no way to lose the remote.
- For `filter`, the daemon refuses to start if `/dev/uinput` or `EVIOCGRAB`
  fails; it does not half-apply.
- Unmapped keys are forwarded. Home/Back/volume/channel are intentionally
  unmapped until the CC exists.
- If the daemon dies, the kernel releases the grab and removes the virtual
  device; the stock remote works again.
- Do not map `116` (power) without a deliberate test.
- This does not touch the Home app or the boot payload. Starting it at boot is
  a later step.

## Files

- `RemoteDaemon.csproj` — net6.0 console project.
- `Program.cs` — blocking-read loop, optional grab/uinput forwarding,
  `app_launcher` action.
- `remote-map.conf.example` — safe observe default.

## Not done yet

- Boot persistence (start from the payload after root).
- Dynamic device discovery (currently expects `event6`).
- A UI / `home_appid` change.
- Mapping a key to the CC app (needs the CC app ID).
