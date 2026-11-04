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
    line(10, 0, 8, 33, "masks begin n=24"),
    line(10, 0, 9, 34, "ROOTCHAN 31337 uid=0 bind=192.0.2.10"),
    line(10, 0, 10, 35, "masks=24 stopped=24 killed=3 fail=0 missing=0 "
                        "activating=2 listed-activating=0 loop-check=ok "
                        "newhome=set(0),loop-started"),
]

# v42.0's first run: the stop loop ran out of budget (fixed in v42.1, but the
# line is still in logs written that day, so it must decode).
MASKFAIL = [
    line(13, 7, 1, 40, "start uid=5001 pid=400"),
    line(13, 7, 1, 41, "masks begin n=24"),
    line(13, 7, 2, 96, "masks deadline after 4/24 stops"),
    line(13, 7, 2, 97, "masks=24 stopped=2 killed=16 fail=22 missing=0 "
                       "activating=1 listed-activating=0 loop-check=ok "
                       "newhome=set(0),loop-active"),
]

MASKSKIP = [
    line(14, 0, 0, 50, "masks begin n=24"),
    line(14, 0, 1, 51, "masks skip (no /opt/usr/data/debloat-masks.txt)"),
]

MASKODD = [
    line(15, 0, 0, 60, "masks begin n=24"),
    line(15, 0, 1, 61, "masks counters unverified (list-units failed)"),
    line(15, 0, 1, 61, "masks exception IOException: list-units"),
]

# The 2026-11-01 deploy-restart shape: the app restarted inside the same boot,
# burned its four fast attempts and then the long-mode pass never saw a new
# landmark (seen=0 in every round, empty `tail:`).  That is the "blind walk":
# the task list is unreadable, so only a fresh process can help.
BLIND = [
    line(14, 20, 0, 5273, "start uid=5001 pid=14001"),
    line(14, 20, 1, 5275, "attempt=5 (long retry mode)"),
    line(14, 20, 2, 5279, "fail no new PHYRFORK seen=0 skip-orphan=0 "
                          "stale-tag=0 pu=ffffffff"),
    line(14, 20, 3, 5290, "fail no new PHYRFORK seen=0 skip-orphan=0 "
                          "stale-tag=0 pu=ffffffff"),
    line(14, 20, 4, 5300, "fail no new PHYRFORK seen=0 skip-orphan=0 "
                          "stale-tag=0 pu=ffffffff"),
]
BLIND_SEEN = (BLIND[:-1] +
              [line(14, 20, 4, 5300, "fail no new PHYRFORK seen=1 skip-orphan=0 "
                                     "stale-tag=0 pu=ffffffff")])

# v45's answer to the same state: after the long pass, exit for a fresh process
# (bounded), and the relaunch roots on the next attempt.
LONGEXIT = [
    line(15, 0, 0, 5300, "start uid=5001 pid=15001"),
    line(15, 0, 1, 5302, "attempt=5 (long retry mode)"),
    line(15, 0, 2, 5305, "fail no new PHYRFORK seen=0 skip-orphan=0 "
                        "stale-tag=0 pu=ffffffff"),
    line(15, 0, 3, 5390, "fail round 5"),
    line(15, 0, 4, 5392, "long-exit attempt=5 count=1"),
    line(15, 0, 5, 5394, "start uid=5001 pid=15002"),
    line(15, 0, 5, 5394, "attempt=6 (long retry mode)"),
    line(15, 0, 6, 5396, "round=0 pre=0"),
    line(15, 0, 7, 5397, "child=d1ce9140 self=cad25080 pu=5001 tag=exact stale=0"),
    line(15, 0, 7, 5397, "self cred=d1a76c80 real=d1a76c80"),
    line(15, 0, 8, 5398, "self-patch uid=0"),
    line(15, 0, 9, 5400, "SUCCESS-R00T DSHROOT uid=0 pid=15002 self=cad25080 "
                        "kernel=20008000 init_task=c0957180"),
    line(15, 0, 9, 5400, "ROOTCHAN 31337 uid=0 bind=192.0.2.10"),
]

# v46: the start beacon names the artifact the last deploy wrote (rootchan.art)
# as `art=<md5>`; the newest run's art is the DLL the answering process started
# with, so a deploy restart that failed to kill the old app is provable (its
# start beacon carries the PREVIOUS art).  The md5s here are made-up TEST values.
OLD_ART = "0123456789abcdef0123456789abcdef"
NEW_ART = "fedcba9876543210fedcba9876543210"
ARTSWAP = [
    line(16, 0, 0, 6000, f"start uid=5001 pid=16001 art={OLD_ART}"),
    line(16, 0, 1, 6010, "fail round 1"),
    line(16, 0, 9, 6050, f"start uid=5001 pid=16002 art={NEW_ART}"),
    line(16, 0, 10, 6055, "attempt=1 (fast mode)"),
    line(16, 0, 11, 6060, "SUCCESS-R00T DSHROOT uid=0 pid=16002 self=cad25080 "
                          "kernel=20008000 init_task=c0957180"),
    line(16, 0, 11, 6060, "ROOTCHAN 31337 uid=0 bind=192.0.2.10"),
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
    check("healthy: v42 mask step decoded as MASK-BEGIN + MASK-OK",
          {"MASK-BEGIN", "MASK-OK"} <= codes, str(codes))
    hs = next(f for f in r["findings"] if f["code"] == "HIGH-SCAN")
    check("healthy: HIGH-SCAN hint names the elsewhere meaning",
          "elsewhere" in hs["hint"])

    # v42.0 budget-exhausted boot: MASK-FAIL (and the retired deadline line)
    p3 = write_log(MASKFAIL)
    r3 = beacons.analyse_boot(
        beacons.group_boots(list(beacons.parse_lines(p3.read_text())))[0], 0)
    codes3 = {f["code"] for f in r3["findings"]}
    check("maskfail: MASK-FAIL + MASK-DEADLINE, never MASK-OK",
          {"MASK-FAIL", "MASK-DEADLINE"} <= codes3 and "MASK-OK" not in codes3,
          str(codes3))
    mf = next(f for f in r3["findings"] if f["code"] == "MASK-FAIL")
    check("maskfail: hint explains socket/path units", "socket" in mf["hint"])

    # missing policy = documented revert
    p4 = write_log(MASKSKIP)
    r4 = beacons.analyse_boot(
        beacons.group_boots(list(beacons.parse_lines(p4.read_text())))[0], 0)
    check("maskskip: MASK-SKIP decoded",
          "MASK-SKIP" in {f["code"] for f in r4["findings"]})

    # unreadable dump + thrown thread must not read as success
    p5 = write_log(MASKODD)
    r5 = beacons.analyse_boot(
        beacons.group_boots(list(beacons.parse_lines(p5.read_text())))[0], 0)
    codes5 = {f["code"] for f in r5["findings"]}
    check("maskodd: MASK-UNVERIFIED + MASK-CRASH decoded",
          {"MASK-UNVERIFIED", "MASK-CRASH"} <= codes5, str(codes5))

    # v44 deploy-restart shape (2026-11-01): long mode, blind walk in every
    # round -> BLIND-WALK, and the hint must name the ONLY remedy (a fresh
    # process), because an in-process retry cannot fix a blind read.
    p6 = write_log(BLIND)
    r6 = beacons.analyse_boot(
        beacons.group_boots(list(beacons.parse_lines(p6.read_text())))[0], 0)
    codes6 = {f["code"] for f in r6["findings"]}
    check("blind: not rooted", not r6["rooted"])
    check("blind: BLIND-WALK derived from the whole long-mode pass",
          "BLIND-WALK" in codes6, str(codes6))
    check("blind: hint names the fresh process / power-cycle",
          any("power-cycle" in n for n in r6["notes"]), str(r6["notes"]))

    # ... but one round that DID see a landmark means the walk was not blind
    p7 = write_log(BLIND_SEEN)
    r7 = beacons.analyse_boot(
        beacons.group_boots(list(beacons.parse_lines(p7.read_text())))[0], 0)
    check("blind: a round that saw a landmark suppresses BLIND-WALK",
          "BLIND-WALK" not in {f["code"] for f in r7["findings"]},
          str({f["code"] for f in r7["findings"]}))

    # v45: the long-mode pass exits for a fresh process, and the relaunch roots
    p8 = write_log(LONGEXIT)
    r8 = beacons.analyse_boot(
        beacons.group_boots(list(beacons.parse_lines(p8.read_text())))[0], 0)
    codes8 = {f["code"] for f in r8["findings"]}
    check("v45: long-exit decoded", "LONG-EXIT" in codes8, str(codes8))
    check("v45: the relaunched process roots (boot is ROOTED)",
          r8["rooted"] and "ROOTED" in r8["verdict"], r8["verdict"])
    check("v45: no BLIND-WALK note on the recovered boot",
          "BLIND-WALK" not in codes8, str(codes8))

    # v48: the counter-write failure line is decoded, not an unknown line
    cw = {f["code"] for f in beacons.scan(
        "counter-write-failed file=.dsh_long want=2 got=4")}
    check("v48: counter-write-failed decoded", "COUNTER-WRITE" in cw, str(cw))

    # v46: the start beacon carries the deployed artifact md5; the newest run's
    # art is what the answering process started with (deploy-restart proof).
    p9 = write_log(ARTSWAP)
    r9 = beacons.analyse_boot(
        beacons.group_boots(list(beacons.parse_lines(p9.read_text())))[0], 0)
    check("v46: newest run's art is reported",
          r9["art"] == NEW_ART, str(r9["art"]))
    check("v46: each run keeps its own art (the stale process's start beacon "
          "names the OLD artifact)",
          [a["art"] for a in r9["attempts"]] == [OLD_ART, NEW_ART],
          str(r9["attempts"]))
    out9 = subprocess.run([sys.executable, str(HERE / "beacons.py"),
                           "--file", str(p9)],
                          capture_output=True, text=True)
    check("v46: art printed in the CLI summary",
          NEW_ART in out9.stdout, out9.stdout[:200])

    # v46.1: the launcher's freshness witness must AGREE with this analyzer: the
    # NEWEST launch wins even when it carries no art=.  The v46 root.ps1 scan
    # kept the older md5, which is exactly the log a rollback leaves behind.
    ns = beacons.newest_start(p9.read_text())
    check("v46.1: newest_start reports the newest launch's art",
          bool(ns) and ns["art"] == NEW_ART, str(ns))
    pns = write_log([line(16, 0, 0, 6000, f"start uid=5001 pid=16001 art={OLD_ART}"),
                     line(16, 0, 1, 6010, "start uid=5001 pid=16002")])
    ns2 = beacons.newest_start(pns.read_text())
    check("v46.1: a newer launch without art= wins (unknown, not the older md5)",
          bool(ns2) and ns2["art"] is None, str(ns2))
    # production wire shape: tok= sits before the uptime prefix, and both
    # witnesses must survive the parse (root.ps1 compares them to ART_FILE=/TOKEN_FILE=)
    prod = write_log(["2026-11-01T18:00:00 DSHROOT tok=deadbeef t=30s "
                      f"start uid=5001 pid=900 art={NEW_ART}"])
    ns3 = beacons.newest_start(prod.read_text())
    check("v46.1: newest_start reads tok= and art= from a real log line",
          bool(ns3) and ns3["tok"] == "deadbeef" and ns3["art"] == NEW_ART,
          str(ns3))
    # same-bits redeploy: the art is identical, so only the rotated token can
    # tell a survivor from a relaunch (the reason tok= is compared at all).
    same = write_log([line(16, 0, 0, 6000, f"start uid=5001 pid=16003 art={NEW_ART}")])
    ns4 = beacons.newest_start(same.read_text())
    check("v46.1: an old start line has no token to match this deploy's",
          bool(ns4) and ns4["tok"] is None and ns4["art"] == NEW_ART, str(ns4))
    marker_ns = write_log([f"t=6000s start uid=5001 pid=16004 art={NEW_ART}"])
    ns5 = beacons.newest_start(marker_ns.read_text())
    check("v46.1: newest_start also reads the on-TV marker file",
          bool(ns5) and ns5["tok"] is None and ns5["art"] == NEW_ART, str(ns5))
    outns = subprocess.run([sys.executable, str(HERE / "beacons.py"),
                            "--file", str(pns), "--newest-start"],
                           capture_output=True, text=True)
    try:
        nsj = json.loads(outns.stdout)
    except ValueError:
        nsj = {}
    check("v46.1: --newest-start prints JSON for the launcher "
          "(null art on a newer no-art launch)",
          nsj.get("art") is None and outns.returncode == 0, outns.stdout[:120])

    # sick boot: device held, window off, bind fallback, crash -> error hint
    p2 = write_log(SICK)
    boots2 = beacons.group_boots(list(beacons.parse_lines(p2.read_text())))
    r2 = beacons.analyse_boot(boots2[0], 0)
    check("sick: not rooted", not r2["rooted"])
    check("v46: legacy start without art stays unknown, not stale",
          r2["art"] is None, str(r2["art"]))
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

    # a no-pid start line is test/forged noise (Program.cs always logs pid=):
    # its fake t=1s must not split a ghost boot out of a real one.
    beacons.TEST_NOISE["start_without_pid"] = 0
    noise = write_log(HEALTHY + [line(10, 10, 0, 1, "start uid=5001")])
    boots_noise = beacons.group_boots(list(beacons.parse_lines(noise.read_text())))
    check("no-pid start does not create a ghost boot", len(boots_noise) == 1,
          f"boots={len(boots_noise)}")
    check("no-pid start counted as test noise",
          beacons.TEST_NOISE["start_without_pid"] == 1)
    outn = subprocess.run([sys.executable, str(HERE / "beacons.py"),
                           "--file", str(noise)],
                          capture_output=True, text=True)
    check("no-pid start is reported, not silently dropped",
          "ignored 1" in outn.stdout and "without pid=" in outn.stdout,
          outn.stdout.splitlines()[0] if outn.stdout else outn.stderr[:80])

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

    # Behavioural strings, not just syntax (2026-11-01 review): the debloat
    # acceptance was added with a WARNING-only failure and an inert
    # `ROOT_SHELL_TIMEOUT`, so pin both decisions.
    root_ps1 = (ROOT / "root.ps1").read_text(encoding="utf-8")
    check("root.ps1: a health failure exits 4 (not a silent warning)",
          "exit 4" in root_ps1 and "the debloat acceptance did not" in root_ps1)
    check("root.ps1: the health call passes --timeout (env here is inert)",
          "--timeout 25" in root_ps1
          and 'tv_health.py") --tv $TvIp --timeout 25' in root_ps1)
    check("root.ps1: -NoWait dry run says the health check is skipped",
          "-NoWait skips the wait AND the health check" in root_ps1)


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
