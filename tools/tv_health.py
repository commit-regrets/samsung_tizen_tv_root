"""Post-boot / post-apply health check for the TV, over the 31337 channel.

    python tools/tv_health.py --tv 192.0.2.1 [--json] [--timeout 20]

Read-only. Exit 0 = all checks pass, 1 = at least one FAIL, 2 = usage/connect.

Why this exists: every state claim in the docs was verified by hand - five
separate one-line `root_shell.py` calls whose parsers lived in the operator's
head, and two count drifts still slipped through (the README said 24 units when
the list held 29; a "deferred" list contained two applied ids). This script is
the TV-side oracle for `debloat/registry.tsv`: it asks the TV whether the
registry's claims are true, so "the apply silently did nothing", "a cold boot
re-enabled something" and "the wrong payload is running" are one command.

Checks (each maps to a registry/document claim):
  root        id -u == 0 and CapEff == 0x3fffffffff
  artifact    installed DLL md5 == server/payload.dll
  witness     rootchan.art == that md5 (the v46 start-beacon witness)
  bootrow     the boot_sequence row for the app in .appsvc.db == 1
              (the persistence hook itself)
  applied     every registry `applied` id is app_disable='true'
  off-list    every installed never/deferred/reverted app is 'false'
  count       the disabled set is exactly the registry's `applied` set
  masks       masked-unit count == debloat/lists/services-units.txt
  maskfile    /opt/usr/data/debloat-masks.txt + debloat-kill.txt exist,
              root-owned and not world-writable (the mask step executes
              what it reads - the v42 hardening)
  masked      every listed unit answers `is-enabled` = masked-runtime
              (polls up to 5 s: the boot payload re-asserts them)
  loops       the newest mask beacon says listed-activating=0, loop-check=ok,
              fail=0, missing=0 (a global `activating=1` is normal on an idle
              boot - a transient unit starting - and is shown as context)
  sentinels   canalysis-daemon + pisa-service sentinels present
  smarthome   org.tizen.easysetup-daemon.service is active
  autoupdate  both buxton autoupdate keys read back Int32: 0
              (the OTA-pinned-off claim, queried live - not from a beacon)
  backups     mcs_orig.dll / mcs_ni_orig.dll exist and match their
              deploy-written .md5 records (uninstall's recovery path)
  beacon      the newest launch line carries tok= and art=<repo md5>

The comparison logic (`evaluate`) is pure and unit-tested offline in
`tools/test_tv_health.py`; `read` does the channel calls and is injectable the
same way.
"""
from __future__ import annotations

import argparse
import json
import re
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PAYLOAD = ROOT / "server" / "payload.dll"
REGISTRY = ROOT / "debloat" / "registry.tsv"
UNITS = ROOT / "debloat" / "lists" / "services-units.txt"
BEACON_LOG = ROOT / "server" / "logs" / "beacons.log"

DB = "/opt/dbspace/.pkgmgr_parser.db"
SHARE = "/opt/usr/home/owner/share"
DLL = ("/opt/usr/apps/com.samsung.tv.MultiControl-Service/bin/"
       "MultiControlService.dll")
SENTINELS = "/opt/usr/share/systemd/system"
FULL_CAPS = "0000003fffffffff"

sys.path.insert(0, str(HERE))
import beacons  # noqa: E402


def default_run(cmd: str, tv: str, timeout: float) -> str:
    p = subprocess.run([sys.executable, str(HERE / "root_shell.py"), cmd, tv],
                       capture_output=True, text=True, timeout=timeout,
                       env={**os.environ, "ROOT_SHELL_TIMEOUT": str(int(timeout))})
    if p.returncode != 0:
        raise OSError((p.stderr or "root_shell failed").strip().splitlines()[-1])
    return (p.stdout or "").replace("__END__", "").strip()


def read(tv: str, *, run=None, timeout: float = 20.0, log: Path | None = None) -> dict:
    """Collect the raw TV facts the checks need (one channel command each)."""
    run = run or (lambda cmd: default_run(cmd, tv, timeout))
    r = {}
    ident = run("id -u; grep -E '^CapEff' /proc/self/status")
    for line in ident.splitlines():
        line = line.strip()
        if line.startswith("CapEff:"):
            r["caps"] = line.split(":", 1)[1].strip().lower()
        elif line.isdigit():
            r["uid"] = int(line)
    r["caps"] = r.get("caps", "")
    r["uid"] = r.get("uid")

    md5_out = run(f"md5sum {DLL}").split()
    r["dll_md5"] = md5_out[0] if md5_out else ""

    r["art"] = run(f"cat {SHARE}/rootchan.art")

    rows = {}
    for line in run(f'sqlite3 -readonly -csv {DB} '
                    '"SELECT app_id, app_disable FROM package_app_info;"').splitlines():
        parts = line.strip().split(",")
        if len(parts) >= 2:
            rows[parts[0]] = parts[1] == "true"
    r["rows"] = rows

    r["masks"] = int(run("find /run/systemd/system -maxdepth 1 -type l "
                         "-lname /dev/null | wc -l").strip() or 0)
    r["activating"] = int(run("systemctl list-units --all --no-legend --plain "
                              "| grep -c ' activating '").strip() or 0)
    r["sentinels"] = len([l for l in run(
        f"ls {SENTINELS}/canalysis-daemon {SENTINELS}/pisa-service "
        "2>/dev/null").splitlines() if l.strip()])
    r["easysetup"] = run("systemctl is-active "
                         "org.tizen.easysetup-daemon.service").strip()

    # Persistence + policy facts, batched one `sh -c` per call (the channel is
    # line-based).  bootrow is the persistence hook; the two autoupdate keys
    # are the OTA pin (queried live, not from a beacon).
    persist_out = run(
        'echo BOOT=$(sqlite3 -readonly /opt/dbspace/user/5001/.appsvc.db '
        '".timeout 5000" '
        '"select count(*) from boot_sequence where '
        "appid='com.samsung.tv.MultiControl-Service';\" 2>/dev/null); "
        "echo AUS=$(buxton2ctl get system "
        "db/menu/support/softwareupdate/autoupdate 2>/dev/null); "
        "echo AUU=$(buxton2ctl get user "
        "db/menu/support/softwareupdate/autoupdate 2>/dev/null)")
    mb = re.search(r"BOOT=(\d+)", persist_out)
    r["bootrow"] = int(mb.group(1)) if mb else None
    au = {}
    for key, tag in (("system", "AUS"), ("user", "AUU")):
        m = re.search(tag + r"=.*Int32: (\d+)", persist_out)
        au[key] = m.group(1) if m else None
    r["autoupdate"] = au

    # The mask policy files must stay root-owned and not world-writable (the
    # mask step executes what it reads), and the stock backups must still
    # match the .md5 records deploy.sh wrote next to them (uninstall's path).
    files_out = run(
        "ls -l /opt/usr/data/debloat-masks.txt "
        "/opt/usr/data/debloat-kill.txt 2>/dev/null; "
        "echo IL=$(md5sum /opt/usr/home/owner/share/mcs_orig.dll 2>/dev/null "
        "| cut -d' ' -f1)-$(cat /opt/usr/home/owner/share/mcs_orig.md5 "
        "2>/dev/null); "
        "echo NI=$(md5sum /opt/usr/home/owner/share/mcs_ni_orig.dll 2>/dev/null "
        "| cut -d' ' -f1)-$(cat /opt/usr/home/owner/share/mcs_ni_orig.md5 "
        "2>/dev/null)")
    files: dict = {}
    for line in files_out.splitlines():
        f = line.split()
        if len(f) >= 8 and f[0].startswith("-"):
            files[f[-1].rsplit("/", 1)[-1]] = {
                "owner": f[2],
                "size": int(f[4]) if f[4].isdigit() else 0,
                "world_writable": len(f[0]) > 8 and f[0][8] == "w",
                "group_writable": len(f[0]) > 5 and f[0][5] == "w",
            }
    r["maskfiles"] = files
    bk: dict = {}
    for key, tag in (("il", "IL="), ("ni", "NI=")):
        m = re.search(tag + r"([0-9a-f]*)-([0-9a-f]*)", files_out)
        bk[key] = {"md5": m.group(1), "expected": m.group(2)} if m \
            else {"md5": "", "expected": ""}
    r["backups"] = bk

    # The list is the payload's own copy (what it re-asserts each boot).  One
    # batched `is-enabled` call for all units (29 separate calls cost >20 s on
    # this TV), and poll up to 5 s so a check run right after rooting does not
    # race the payload's background mask step.
    masked_out = run(
        "i=0; while [ $i -lt 5 ]; do "
        "out=$(systemctl is-enabled "
        "$(grep -v '^#' /opt/usr/data/debloat-masks.txt | grep -v '^$' | tr -d '\\015') "
        "2>/dev/null); "
        "n=$(printf '%s\\n' \"$out\" | grep -c .); "
        "bad=$(printf '%s\\n' \"$out\" | grep -v '^masked-runtime$' | grep -c .); "
        "[ \"$bad\" = 0 ] && break; i=$((i+1)); sleep 1; done; "
        "echo \"masked=$n bad=$bad\"")
    mm = re.search(r"masked=(\d+) bad=(\d+)", masked_out)
    r["masked_units"] = int(mm.group(1)) if mm else -1
    r["unmasked"] = int(mm.group(2)) if mm else -1

    launch = None
    log = log or BEACON_LOG
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    if text:
        launch = beacons.newest_start(text)
    r["beacon"] = launch

    # The mask step's own beacon carries the honest loop signal: a global
    # `activating=1` is normal on an idle boot (a transient unit starting),
    # while a LISTED unit activating is the failure.  Wait briefly for the
    # line: the masked-runtime state can exist a moment before the beacon.
    mask_txt = ""
    for _ in range(6):
        if log.exists():
            mask_txt = next((l for l in reversed(
                log.read_text(encoding="utf-8", errors="replace").splitlines())
                if " masks=" in l and "listed-activating=" in l), "")
        if mask_txt:
            break
        time.sleep(1)
    mask: dict = {}
    for key, field in (("masks", "masks"), ("fail", "fail"),
                       ("missing", "missing"), ("activating", "activating"),
                       ("listed-activating", "listed_activating")):
        mm = re.search(key + r"=(\d+)", mask_txt)
        mask[field] = int(mm.group(1)) if mm else None
    ml = re.search(r"loop-check=(\w+)", mask_txt)
    mask["loop_check"] = ml.group(1) if ml else None
    r["mask"] = mask
    return r


def registry(path: Path = REGISTRY) -> dict:
    """{status: {id}} from the decision ledger (7 columns, # comments)."""
    out: dict[str, set] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        f = line.split("\t")
        if len(f) == 7 and f[1] == "app":
            out.setdefault(f[2], set()).add(f[0])
    return out


def evaluate(r: dict, reg: dict, units: int, payload_md5: str) -> list[dict]:
    """The pure comparison: readings + repo facts -> PASS/FAIL records."""
    checks = []

    def ck(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    ck("root", r.get("uid") == 0 and r.get("caps") == FULL_CAPS,
       f"uid={r.get('uid')} caps={r.get('caps') or 'unreadable'}")
    ck("artifact", r.get("dll_md5") == payload_md5,
       f"tv={r.get('dll_md5') or 'unreadable'} repo={payload_md5}")
    ck("witness", r.get("art") == payload_md5,
       f"rootchan.art={r.get('art') or 'absent/mismatch'}")
    ck("bootrow", r.get("bootrow") == 1,
       f"boot_sequence rows={r.get('bootrow')}")

    rows = r.get("rows") or {}
    applied = reg.get("applied", set())
    never = reg.get("never", set()) | reg.get("deferred", set()) | reg.get("reverted", set())
    off_true = applied - {i for i, v in rows.items() if v}
    ck("applied", not off_true,
       f"{len(applied)} expected, {len(off_true)} not true: {sorted(off_true)[:6]}")
    ck("off-list", not (never & {i for i, v in rows.items() if v}),
       f"unexpectedly disabled: {sorted(never & {i for i, v in rows.items() if v})[:6]}")
    disabled_now = {i for i, v in rows.items() if v}
    ck("count", disabled_now == applied,
       f"tv={len(disabled_now)} registry={len(applied)} extra={sorted(disabled_now - applied)[:4]}")

    ck("masks", r.get("masks") == units, f"tv={r.get('masks')} list={units}")
    ck("masked", r.get("masked_units") == units and r.get("unmasked") == 0,
       f"masked-runtime={r.get('masked_units')}/{units} unmasked={r.get('unmasked')}")
    mf = r.get("maskfiles") or {}
    bad_files = [n for n, s in mf.items()
                 if s.get("owner") != "root" or s.get("world_writable")
                 or s.get("group_writable") or not s.get("size")]
    ck("maskfile",
       set(mf) == {"debloat-masks.txt", "debloat-kill.txt"} and not bad_files,
       f"{len(mf)}/2 files" + (f", bad: {sorted(bad_files)}" if bad_files else
                               " root-owned, not world-writable"))
    m = r.get("mask") or {}
    ck("loops", m.get("listed_activating") == 0 and m.get("loop_check") == "ok"
       and m.get("fail") == 0 and m.get("missing") == 0,
       f"listed-activating={m.get('listed_activating')} "
       f"loop-check={m.get('loop_check')} fail={m.get('fail')} "
       f"missing={m.get('missing')} (global activating={r.get('activating')})")
    ck("sentinels", r.get("sentinels") == 2, f"present={r.get('sentinels')}/2")
    ck("smarthome", r.get("easysetup") == "active", f"easysetup={r.get('easysetup') or 'unreadable'}")
    au = r.get("autoupdate") or {}
    ck("autoupdate", au.get("system") == "0" and au.get("user") == "0",
       f"system={au.get('system') or 'unreadable'} "
       f"user={au.get('user') or 'unreadable'}")
    bk = r.get("backups") or {}
    bad_bk = [k for k in ("il", "ni")
              if not (bk.get(k) or {}).get("md5")
              or (bk[k].get("md5") != bk[k].get("expected"))]
    ck("backups", not bad_bk,
       "il=" + ((bk.get("il") or {}).get("md5") or "missing")
       + " ni=" + ((bk.get("ni") or {}).get("md5") or "missing")
       + (f" (mismatch: {sorted(bad_bk)})" if bad_bk else " match .md5 records"))
    launch = r.get("beacon") or {}
    ck("beacon", bool(launch.get("tok")) and launch.get("art") == payload_md5,
       f"tok={'yes' if launch.get('tok') else 'no'} art={launch.get('art') or 'none'}")
    return checks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tv", default=os.environ.get("TV_IP") or os.environ.get("ROOT_TV"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args(argv)
    if not args.tv:
        print("usage: tv_health.py --tv <ip>   (or set TV_IP / ROOT_TV)",
              file=sys.stderr)
        return 2
    if not PAYLOAD.exists():
        print(f"tv_health: missing {PAYLOAD}", file=sys.stderr)
        return 2
    payload_md5 = __import__("hashlib").md5(PAYLOAD.read_bytes()).hexdigest()
    units = len([l for l in UNITS.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")])
    try:
        readings = read(args.tv, timeout=args.timeout)
    except Exception as exc:  # connection / timeout / shell failure
        print(f"tv_health: cannot read the TV: {exc}", file=sys.stderr)
        return 2
    checks = evaluate(readings, registry(), units, payload_md5)
    bad = [c for c in checks if not c["ok"]]
    if args.json:
        print(json.dumps({"checks": checks, "ok": not bad,
                          "failed": [c["name"] for c in bad]}, indent=2))
    else:
        for c in checks:
            print(("PASS " if c["ok"] else "FAIL ") + c["name"]
                  + (f" - {c['detail']}" if c["detail"] else ""))
        print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed"
              + ("" if not bad else f"; failed: {', '.join(c['name'] for c in bad)}"))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
