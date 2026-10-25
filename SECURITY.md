# Security policy and responsible use

This repository is **security research code**. It exploits a browser CVE and a
V4L2 physmap bug to gain `uid=0` on a Samsung Tizen 9 TV, then installs a
persistent boot payload. It is not a consumer tool and it is not hardened.

## The root channel is a backdoor by design

- TCP **31337** on the TV is an **unauthenticated** line-protocol root shell.
  The only access control is `share/rootchan.allow` (one peer IP per line); the
  listener binds the TV's LAN address, not `0.0.0.0`.
- Anyone who can reach that port from an allowed address has root on the TV.
  Never expose it to the internet, a guest VLAN, Wi-Fi Direct, or a network you
  do not control.
- Run on hardware you own. Uninstall when you are finished
  (`uninstall.ps1 -TvIp <tv-ip>`), and keep TV auto-update **off** (the payload
  does this at every boot, but an OTA can still replace the app).
- A bad physical write can crash or brick the TV. Keep the stock
  `mcs_orig.dll` / `mcs_ni_orig.dll` backups that `deploy.sh` creates.

## Supported scope

- The test unit described in `README.md` and the constants in
  `payload/Program.cs`. Other models/firmware are **not** supported without the
  porting work in `docs/PORTABILITY.md`.
- Nothing here is a generic jailbreak, a warranty service, or a way to bypass
  content protection. Do not use it to attack devices you do not own.

## Reporting a problem

Use GitHub **Security Advisories** for this repository for anything sensitive
(for example, a way this code could damage a device or expose a user beyond the
documented backdoor). For ordinary documentation or tooling bugs, open an issue.
Please include the payload version/hash, the TV model and firmware, and the
relevant beacon lines — never a full disk image or personal data.

## Legal

Use only on hardware you own and only where local law allows security research.
This project is unofficial and not affiliated with or endorsed by Samsung.
Samsung and Tizen are trademarks of Samsung Electronics. The software is
provided as-is, without warranty; see `LICENSE`.
