"""Decode server/logs/beacons.log into per-boot verdicts and next steps.

    python tools/beacons.py                    # analyse the default log
    python tools/beacons.py --file <log>       # any beacon log / marker file
    python tools/beacons.py --json             # machine-readable report
    python tools/beacons.py --last 3           # only the newest 3 boots

The beacon stream is the fastest way to see what the payload did on a boot
(no beacons at all = the app never started; beacons without 31337 = the chain
names the step that failed).  This tool groups the stream into boots (kernel
uptime `t=<n>s` resets on a cold boot), splits each boot into AUL launches
(`start uid=`), applies the signatures collected in docs/LOGGUIDE.md, and
prints one verdict per boot plus findings with hints.

Exit codes: 0 = log read and decoded (regardless of what the boots did),
2 = no log / nothing parseable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG = ROOT / "server" / "logs" / "beacons.log"

LINE = re.compile(r"^(?P<ts>\S+)\s+DSHROOT\s+(?P<rest>.*)$")
UPTIME = re.compile(r"(?:^|\s)t=(?P<t>\d+)s(?:\s|$)")
ATTEMPT = re.compile(r"^attempt=(\d+)")
START = re.compile(r"^start uid=(\d+) pid=(\d+)")

# ---- signatures: (code, regex, severity, message, hint) ---------------------
# Severity: "info" = expected on this design, "warn" = explains a slow boot or
# a failed attempt, "error" = the chain is broken.  Hints say the next action;
# docs/LOGGUIDE.md carries the full story per code.
SIGNATURES = [
    ("HIGH-ALLOC", re.compile(r"^high-alloc .*\bfast-exit$"), "info",
     "attempt drew a high (>= 0xE0000000) task/cred allocation and fast-exited",
     "normal since v33: attempt 1 is an allocation lottery, only a fresh "
     "process re-rolls it; expect the next attempt to root"),
    ("HIGH-SCAN", re.compile(r"^high-scan .*\bverdict=(?P<v>\S+)"), "info",
     "v38 read-only probe answered the high-half question",
     "verdict=linear -> video40 returned wrong bytes for a frame it can "
     "address; verdict=elsewhere -> va-0xA0000000 is the wrong frame (at= is "
     "the true task address, children-list validated, and cuid=5001 there "
     "would mean a locate-and-patch path could work); comm-only/miss -> "
     "inconclusive, read cov=; see docs/LOGGUIDE.md"),
    ("VID40-HELD", re.compile(r"^fail open video40 after"), "error",
     "/dev/video40 was held by another opener for the whole 120 s retry",
     "a browser stub or a wedged payload owns the device; wait ~2 min or "
     "power-cycle, then retry (AGENTS.md trap 3)"),
    ("VID40-RETRY", re.compile(r"^reopen video40 fd=-1"), "warn",
     "video40 was still held when the hunt needed it",
     "a landmark child or browser stub held it; the boot usually still roots "
     "on a later attempt"),
    ("WIN-OFF", re.compile(r"^physmap window (unavailable|off:)"), "warn",
     "the alias-correct physmap window is not in play (plain mmap fallback)",
     "stale reads become likelier (the v17/v27 family); if this boot failed, "
     "the next AUL launch re-rolls the mapping"),
    ("WIN-HOLE", re.compile(r"^physmap fixed map failed"), "warn",
     "a window slot was lost and restored (or the window switched off)",
     "informational; a follow-up 'window off' line means WIN-OFF applies"),
    ("BIND-FALLBACK", re.compile(r"^chan bind .* failed"), "warn",
     "31337 fell back to 0.0.0.0 because the TV had no route to the PC yet",
     "expected when the TV boots offline; the allowlist still filters peers, "
     "but keep the set off untrusted networks (SECURITY.md)"),
    ("STALE-SELFCRED", re.compile(r"^direct-probe .* cred=00000000"), "info",
     "our own task's cred-pointer line read stale zeros (v27 cold-boot "
     "signature) while the child side read coherently",
     "the v28 CredScanNear fallback exists for exactly this; attempt 2 roots"),
    ("NO-IMAGE", re.compile(r"^fail no (kernel image|init_task|task offsets)$"), "warn",
     "the kernel-memory scan found nothing this attempt",
     "usually early-boot read chaos; a later attempt recovers. Persistent "
     "across boots on new firmware = re-measure constants (docs/PORTABILITY.md)"),
    ("CRASH", re.compile(r"^exception "), "error",
     "the payload hit a CLR exception",
     "read the type in this line; a crash before ROOTCHAN means no channel "
     "this boot - the browser lane (tv_rootwatch.py) still works"),
    ("CHAN-DENY", re.compile(r"^chan deny "), "warn",
     "31337 refused a peer not in rootchan.allow",
     "expected for strangers; if this was YOU, the PC's address changed - "
     "update share/rootchan.allow (allowlist fails closed)"),
    ("CHAN-FAIL", re.compile(r"^chan fail "), "warn",
     "channel error after startup",
     "read the message; Run() timeouts return '[timeout: killed after 15s]' "
     "and keep serving by design"),
    ("UPDATE-OFF", re.compile(r"^autoupdate .*Int32: 0$"), "info",
     "auto-update re-asserted off", "nothing to do"),
    ("UPDATE-FAIL", re.compile(r"^autoupdate fail"), "warn",
     "could not re-assert auto-update off",
     "OTA could replace the app and the boot row; set it by hand "
     "(AGENTS.md 'Auto-update is pinned off')"),
]

ROOTED = re.compile(r"^SUCCESS-R00T ")
ROOTCHAN = re.compile(r"^ROOTCHAN 31337 uid=(?P<uid>\d+)")
FAILROUND = re.compile(r"^fail (round \d+|no new PHYRFORK.*)$")


def parse_lines(text):
    """Yield (ts, t_or_None, rest) for every DSHROOT line; skip garbage.

    `rest` has the leading `t=<n>s ` uptime prefix stripped (it is returned
    separately as `t`), so every signature regex below is anchored on the
    payload line text itself, exactly as Beacon() built it.
    """
    for raw in text.splitlines():
        m = LINE.match(raw.strip())
        if not m:
            continue
        rest = m.group("rest")
        um = UPTIME.search(rest)
        t = int(um.group("t")) if um else None
        if um:
            rest = rest[um.end():].lstrip()
        yield m.group("ts"), t, rest


def group_boots(entries):
    """Split the stream into boots: kernel uptime resets on a cold boot."""
    boots, cur, prev_t = [], [], None
    for ts, t, rest in entries:
        if prev_t is not None and t is not None and t < prev_t:
            boots.append(cur)
            cur = []
        cur.append((ts, t, rest))
        if t is not None:
            prev_t = t
    if cur:
        boots.append(cur)
    return boots


def split_runs(boot):
    """Split one boot's lines into AUL launches ('start uid=' markers)."""
    runs, cur = [], []
    for ts, t, rest in boot:
        if START.match(rest) and cur:
            runs.append(cur)
            cur = []
        cur.append((ts, t, rest))
    if cur:
        runs.append(cur)
    return runs


def scan(rest):
    """Return the signature matches for one payload line."""
    out = []
    for code, rx, sev, msg, hint in SIGNATURES:
        m = rx.search(rest)
        if m:
            out.append({"code": code, "sev": sev, "msg": msg, "hint": hint,
                        "line": rest})
    return out


def analyse_boot(boot, index):
    """One boot -> verdict dict (also used for --json)."""
    runs = split_runs(boot)
    findings, seen = [], set()
    rooted_at = chan_at = None
    chan_uid = None
    for ts, t, rest in boot:
        if ROOTED.match(rest) and rooted_at is None:
            rooted_at = t
        rm = ROOTCHAN.match(rest)
        if rm:
            chan_at, chan_uid = t, int(rm.group("uid"))
        for f in scan(rest):
            key = (f["code"], f["msg"])
            if key not in seen:
                seen.add(key)
                findings.append(f)

    attempts = []
    for run in runs:
        n = None
        result = "started"
        for ts, t, rest in run:
            am = ATTEMPT.match(rest)
            if am:
                n = int(am.group(1))
            if ROOTED.match(rest):
                result = "rooted"
            elif "fast-exit" in rest:
                # both spellings: "fast-exit attempt=1" and
                # "high-alloc ... fast-exit"
                result = "fast-exit"
            elif FAILROUND.match(rest) or rest.startswith("fail "):
                result = " ".join(rest.split()[:3])
        attempts.append({"attempt": n, "result": result})

    if rooted_at is not None:
        verdict = f"ROOTED at t={rooted_at}s of TV uptime"
    elif chan_at is not None and chan_uid == 0:
        verdict = f"ROOTED (channel 31337 up as uid 0 at t={chan_at}s)"
    else:
        last = boot[-1][2]
        verdict = f"NOT rooted - last line: {last[:90]}"

    # the lottery note: a high-alloc fast-exit attempt followed by a root
    notes = []
    if any(a["result"] == "fast-exit" for a in attempts) and rooted_at is not None:
        notes.append("attempt-1 style fast-exit before the root - the "
                     "allocation-lottery path, working as designed (v33+)")
    if not any(ROOTED.match(b[2]) for b in boot) and chan_uid != 0:
        hints = [f["hint"] for f in findings if f["sev"] == "error"] or \
                [f["hint"] for f in findings if f["sev"] == "warn"]
        if hints:
            notes.append(f"next step: {hints[0]}")

    return {
        "index": index,
        "first_ts": boot[0][0],
        "last_ts": boot[-1][0],
        "max_t": max((t for _, t, _ in boot if t is not None), default=None),
        "lines": len(boot),
        "runs": len(runs),
        "verdict": verdict,
        "rooted": rooted_at is not None or (chan_uid == 0),
        "attempts": attempts,
        "findings": findings,
        "notes": notes,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", default=str(DEFAULT_LOG), help="beacon log to read")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--last", type=int, default=0, help="only the newest N boots")
    args = ap.parse_args(argv)

    p = Path(args.file)
    if not p.exists():
        print(f"beacons: no log at {p} - no beacon has ever arrived here.\n"
              f"If the TV just booted: check the server on :80 (pysrv.exe, "
              f"never python.exe), the page load, and the boot row.",
              file=sys.stderr)
        return 2
    boots = group_boots(list(parse_lines(p.read_text(errors="replace"))))
    if not boots:
        print(f"beacons: no DSHROOT lines in {p}", file=sys.stderr)
        return 2
    if args.last > 0:
        boots = boots[-args.last:]

    report = [analyse_boot(b, i) for i, b in enumerate(boots)]
    if args.json:
        print(json.dumps({"boots": report, "log": str(p)}, indent=2))
        return 0

    print(f"beacons: {len(report)} boot(s) in {p}")
    for b in report:
        print(f"\n--- boot #{b['index']}  {b['first_ts']} .. {b['last_ts']}"
              f"  (max t={b['max_t']}s, {b['lines']} lines, {b['runs']} launch(es))")
        print(f"    verdict: {b['verdict']}")
        if b["attempts"]:
            desc = "; ".join(
                f"attempt {a['attempt']}: {a['result']}"
                if a["attempt"] else f"launch: {a['result']}"
                for a in b["attempts"])
            print(f"    attempts: {desc}")
        for n in b["notes"]:
            print(f"    note: {n}")
        for f in b["findings"]:
            print(f"    [{f['sev']}] {f['code']}: {f['msg']}")
            print(f"            -> {f['hint']}")
    last = report[-1]
    print(f"\nno beacons after {last['last_ts']}. If the TV has booted since "
          f"then, the app never started or the PC was unreachable "
          f"(server on :80? page loaded? boot row present?). "
          f"Line dictionary: docs/LOGGUIDE.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
