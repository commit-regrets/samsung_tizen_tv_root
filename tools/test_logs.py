"""Offline tests for the agent-facing logging layer.

    python tools/test_logs.py          # no TV, no server

Covers:

  1. tools/beacons.py   fixture beacon logs -> boot grouping, verdicts,
                        signature findings, hints, --json shape
  2. root_shell.py      the new self-diagnosing connection errors (offline:
                        refused on loopback, usage exit 2)
  3. run_root.py        the 508 B command refusal (no stub needed)
  4. PowerShell         root.ps1 / uninstall.ps1 parse cleanly (skipped when
                        pwsh/powershell is absent) - guards the ICMP-trap
                        TCP-probe edits from 2026-10-26

Exit code 0 = all present layers passed.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import beacons  # noqa: E402

FAILS = 0


def check(name, ok, note=""):
    global FAILS
    print(("PASS" if ok else "FAIL"), name, "-", note, flush=True)
    if not ok:
        FAILS += 1


# Fixture lines. Addresses are TEST-NET placeholders (repo rule: no private
# LAN IPs in committed examples). Shapes follow the real beacons.log:
# "<iso> DSHROOT t=<n>s <payload line>".
T = "2026-01-01T%02d:%02d:%02d"


def line(h, m, s, t, rest):
    return f"{T % (h, m, s)} DSHROOT t={t}s {rest}"


HEALTHY = [
    line(10, 0, 0, 22, "start uid=5001 pid=100"),
    line(10, 0, 0, 22, "attempt=1 (fast mode)"),
    line(10, 0, 1, 25, "child=cc335640 self=00000000 pu=unread"),
    # v38 probe answer on the fast-exit path (verdict=elsewhere, found 5001)
    line(10, 0, 2, 26, "high-scan C=cc335640 P=e2df7300 pp=42df7000 cp=- "
                       "pc=0 hits=1 at=26f00300 cred=cfa03300 cuid=5001 "
                       "cov=25f00000-27f00000 ms=900 verdict=elsewhere"),
    line(10, 0, 3, 27, "high-alloc parent=e2df7300 cred=b09aa3b5 real=00000000 "
                       "junk=0 fast-exit"),
    line(10, 0, 4, 28, "start uid=5001 pid=101"),
    line(10, 0, 4, 28, "attempt=2 (fast mode)"),
    line(10, 0, 5, 30, "child=c597f300 self=00000000 pu=5001"),
    line(10, 0, 5, 30, "direct-parent+2f0=ca2be1c0 cred=df30cf00"),
    line(10, 0, 5, 30, "direct-patch uid=0"),
    line(10, 0, 6, 31, "SUCCESS-R00T DSHROOT uid=0 pid=101 self=00000000 "
                       "kernel=20008000 init_task=c0957180"),
    line(10, 0, 7, 32, "autoupdate [system] db/menu/support/softwareupdate/"
                       "autoupdate = Int32: 0"),
    line(10, 0, 8, 33, "device closed"),
    line(10, 0, 9, 34, "ROOTCHAN 31337 uid=0 bind=192.0.2.10"),
]

SICK = [
    line(11, 0, 0, 10, "start uid=5001 pid=200"),
    line(11, 0, 0, 10, "attempt=1 (fast mode)"),
    line(11, 0, 1, 12, "physmap window off: slot restore failed at a8280000"),
    line(11, 0, 2, 115, "fail open video40 after 120s=-1"),
    line(11, 0, 3, 116, "chan bind 192.0.2.10 failed (Network unreachable), "
                        "using any"),
    line(11, 0, 4, 117, "exception IOException: mmap failed page=20008000"),
]


def write_log(lines):
    f = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False)
    f.write("\n".join(lines) + "\n")
    f.close()
    return Path(f.name)


def test_beacons():
    # healthy boot: uptime resets split boots, verdict ROOTED, lottery note,
    # high-scan decoded, autoupdate info
    p = write_log(HEALTHY)
    boots = beacons.group_boots(list(beacons.parse_lines(p.read_text())))
    check("healthy: one boot from one uptime run", len(boots) == 1)
    r = beacons.analyse_boot(boots[0], 0)
    check("healthy: verdict ROOTED", r["rooted"] and "ROOTED" in r["verdict"],
          r["verdict"])
    check("healthy: two AUL launches", r["runs"] == 2, f"runs={r['runs']}")
    check("healthy: attempt 2 rooted",
          any(a["attempt"] == 2 and a["result"] == "rooted"
              for a in r["attempts"]))
    check("healthy: lottery note present",
          any("lottery" in n for n in r["notes"]))
    codes = {f["code"] for f in r["findings"]}
    check("healthy: HIGH-ALLOC + HIGH-SCAN + UPDATE-OFF seen",
          {"HIGH-ALLOC", "HIGH-SCAN", "UPDATE-OFF"} <= codes, str(codes))
    hs = next(f for f in r["findings"] if f["code"] == "HIGH-SCAN")
    check("healthy: HIGH-SCAN hint names the elsewhere meaning",
          "elsewhere" in hs["hint"])

    # sick boot: device held, window off, bind fallback, crash -> error hint
    p2 = write_log(SICK)
    boots2 = beacons.group_boots(list(beacons.parse_lines(p2.read_text())))
    r2 = beacons.analyse_boot(boots2[0], 0)
    check("sick: not rooted", not r2["rooted"])
    codes2 = {f["code"] for f in r2["findings"]}
    check("sick: VID40-HELD + WIN-OFF + BIND-FALLBACK + CRASH seen",
          {"VID40-HELD", "WIN-OFF", "BIND-FALLBACK", "CRASH"} <= codes2,
          str(codes2))
    check("sick: error hint surfaced in notes",
          any("next step" in n for n in r2["notes"]), str(r2["notes"]))

    # boot splitting: uptime reset starts a new boot
    both = write_log(HEALTHY + SICK)  # SICK has t=10 < 34 -> new boot
    boots3 = beacons.group_boots(list(beacons.parse_lines(both.read_text())))
    check("two boots split on uptime reset", len(boots3) == 2,
          f"boots={len(boots3)}")

    # the on-TV marker file is `t=<n>s <line>` with no timestamp and no DSHROOT
    # prefix; beacons.py --file reported "no DSHROOT lines" for it before v39.
    marker = write_log([
        "t=22s start uid=5001 pid=100",
        "t=30s SUCCESS-R00T DSHROOT uid=0 pid=100 self=00000000",
        "t=34s ROOTCHAN 31337 uid=0 bind=192.0.2.10",
    ])
    boots4 = beacons.group_boots(list(beacons.parse_lines(marker.read_text())))
    ok = len(boots4) == 1 and beacons.analyse_boot(boots4[0], 0)["rooted"]
    check("marker file (no DSHROOT prefix) parses", ok, f"boots={len(boots4)}")
    out = subprocess.run([sys.executable, str(HERE / "beacons.py"),
                          "--file", str(marker)],
                         capture_output=True, text=True)
    check("marker file: CLI exit 0 + ROOTED", out.returncode == 0
          and "ROOTED" in out.stdout, out.stderr.strip()[-80:])
    marker.unlink()

    # v39 payload lines: per-node open fallback and the cred-miss verdict
    v39 = write_log([
        line(12, 0, 0, 12, "start uid=5001 pid=300"),
        line(12, 0, 0, 12, "open /dev/video40 failed errno=16, trying /dev/video30"),
        line(12, 0, 1, 13, "device /dev/video30 fd=67"),
        line(12, 0, 2, 20, "high-scan C=cc335640 P=21000000 pp=21000000 cp=- "
                          "pc=0 hits=0 at=- cred=- cuid=unread cov=21000000-21100000 "
                          "ms=2500 verdict=cred-miss"),
    ])
    boots5 = beacons.group_boots(list(beacons.parse_lines(v39.read_text())))
    r5 = beacons.analyse_boot(boots5[0], 0)
    codes5 = {f["code"] for f in r5["findings"]}
    check("v39: OPEN-NODE + HIGH-SCAN seen", {"OPEN-NODE", "HIGH-SCAN"} <= codes5,
          str(codes5))
    hs5 = next(f for f in r5["findings"] if f["code"] == "HIGH-SCAN")
    check("v39: cred-miss named in the hint", "cred-miss" in hs5["hint"])
    v39.unlink()

    # --json runs end to end and parses
    out = subprocess.run([sys.executable, str(HERE / "beacons.py"),
                          "--file", str(p), "--json"],
                         capture_output=True, text=True)
    ok = out.returncode == 0
    data = json.loads(out.stdout) if ok else {}
    check("json: parses and carries the boot", ok and data["boots"][0]["rooted"])

    # missing log -> exit 2 with the pysrv hint
    out = subprocess.run([sys.executable, str(HERE / "beacons.py"),
                          "--file", str(p.parent / "nope.log")],
                         capture_output=True, text=True)
    check("missing log: exit 2 + pysrv hint",
          out.returncode == 2 and "pysrv" in out.stderr)

    p.unlink()
    p2.unlink()
    both.unlink()


def test_root_shell_messages():
    py = sys.executable
    rs = str(HERE / "root_shell.py")
    env = dict(os.environ)
    env.pop("TV_IP", None)
    env.pop("ROOT_TV", None)
    # no address -> usage, exit 2
    out = subprocess.run([py, rs, "id"], capture_output=True, text=True, env=env)
    check("root_shell: no address exit 2", out.returncode == 2)
    # loopback refused -> exit 1, message names refusal + beacons hint
    out = subprocess.run([py, rs, "id", "127.0.0.1"],
                         capture_output=True, text=True, timeout=30, env=env)
    check("root_shell: refused -> exit 1 + hints",
          out.returncode == 1 and "refused" in out.stderr
          and "beacons" in out.stderr, out.stderr.splitlines()[0][:70])
    # timeout/unreachable path (RFC 5737 TEST-NET-2 black hole) -> checklist
    out = subprocess.run([py, rs, "id", "198.51.100.1"],
                         capture_output=True, text=True, timeout=60, env=env)
    check("root_shell: timeout -> exit 1 + checklist",
          out.returncode == 1 and "nobody answered" in out.stderr
          and "ping" in out.stderr, out.stderr.splitlines()[0][:70])


def test_run_root_refusal():
    py = sys.executable
    big = "x" * 600
    out = subprocess.run([py, str(HERE / "run_root.py"), big],
                         capture_output=True, text=True, timeout=30)
    check("run_root: >508 B refused with the curl hint",
          out.returncode != 0 and "508" in (out.stdout + out.stderr)
          and "curl" in (out.stdout + out.stderr))


def test_powershell_parse():
    for sh in ("pwsh", "powershell"):
        exe = shutil.which(sh)
        if exe:
            break
    else:
        print("SKIP: PowerShell not installed")
        return
    for name in ("root.ps1", "uninstall.ps1"):
        path = ROOT / name
        expr = (f"$t=$null;$e=$null;"
                f"[void][System.Management.Automation.Language.Parser]::"
                f"ParseFile('{path.as_posix()}',[ref]$t,[ref]$e);"
                f"if($e.Count){{throw ($e | ForEach-Object Message) -join '; '}}")
        out = subprocess.run([exe, "-NoProfile", "-Command", expr],
                             capture_output=True, text=True, timeout=120)
        check(f"ps1 parses: {name}", out.returncode == 0,
              out.stderr.strip().splitlines()[-1][:70] if out.stderr else "")


if __name__ == "__main__":
    test_beacons()
    test_root_shell_messages()
    test_run_root_refusal()
    test_powershell_parse()
    print(flush=True)
    if FAILS:
        print(f"{FAILS} check(s) failed")
        raise SystemExit(1)
    print("test_logs ok")
