"""Decode server/logs/beacons.log into per-boot verdicts and next steps.

    python tools/beacons.py                    # analyse the default log
    python tools/beacons.py --file <log>       # any beacon log OR the on-TV marker
    python tools/beacons.py --json             # machine-readable report
    python tools/beacons.py --last 3           # only the newest 3 boots

The beacon stream is the fastest way to see what the payload did on a boot
(no beacons at all = the app never started; beacons without 31337 = the chain
names the step that failed).  This tool groups the stream into boots (kernel
uptime `t=<n>s` resets on a cold boot), splits each boot into AUL launches
(`start uid=`), applies the signatures collected in docs/LOGGUIDE.md, and
prints one verdict per boot plus findings with hints.

Two input shapes are accepted: the PC-side log (`<timestamp> DSHROOT t=…`) and
the on-TV marker file (`t=…`, no prefix) - so the durable record on the TV can
be pulled and analysed without the PC log.

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
# The payload's on-TV marker file holds the same lines without the PC-side
# timestamp or the DSHROOT prefix (`t=<n>s …`).  beacons.py --file <marker>
# used to report "no DSHROOT lines" for exactly that file.
MARKER = re.compile(r"^(?P<rest>t=\d+s\s+\S.*)$")
UPTIME = re.compile(r"(?:^|\s)t=(?P<t>\d+)s(?:\s|$)")
ATTEMPT = re.compile(r"^attempt=(\d+)")
START = re.compile(r"^start uid=(\d+) pid=(\d+)(?: art=(?P<art>[0-9a-f]{32}))?(?:\s|$)")
# The `(?:\s|$)` tail keeps the line matching if a future beacon field is
# appended after art= (start= lines historically grow fields: child= gained
# pu=/tag=/stale=); an anchored $ would silently stop SPLITTING boots instead.
# v46: the payload reads the deploy-rendered artifact md5 (rootchan.art) once
# at startup and appends it to the start beacon.  The newest run's art says
# which DLL the answering process started with - a stale old process beaconed
# the PREVIOUS art (CHANGELOG 2026-11-01, v46).  A start line without art=
# predates v46 or the file was absent (hand-built payload): unknown, not stale.
# Program.cs always prints pid= in its start line.  A start line without one is
# test or forged noise (the gateway tests used to write exactly this shape into
# the production log).  Never let it open a boot: its hard-coded t=1s would
# otherwise read as a cold boot (found 2026-10-26).
START_NO_PID = re.compile(r"^start uid=(\d+)$")
TEST_NOISE = {"start_without_pid": 0}

# v46.1: the deploy-freshness witness for root.ps1.  The launcher used to
# re-implement this scan (last `art=` in the tail, skipping a newer start line
# that carried none), which disagreed with this analyzer: here the newest launch
# wins even when it has no art=, so a relaunch after a rollback must read
# "unknown", never the older process's md5.  One implementation, used by both.
TOK = re.compile(r"(?:^|\s)tok=(?P<tok>[0-9a-f]{8})(?=\s|$)")
LAUNCH = re.compile(r"(?:^|\s)start uid=\d+ pid=\d+"
                    r"(?:\s+art=(?P<art>[0-9a-f]{32}))?(?=\s|$)")


def newest_start(text):
    """The newest payload launch line, or None.

    Returns {"ts", "tok", "art", "line"}: `tok` is the deploy token that process
    read at startup (`deploy.sh` prints the current one as TOKEN_FILE=), `art`
    the artifact md5 it read from rootchan.art.  Raw lines are scanned because
    parse_lines() drops the `tok=` that sits before the uptime prefix on the
    wire (`DSHROOT tok=<hex> t=<n>s start uid=... pid=... art=<md5>`).

    The LAST matching line wins - beacons.py's newest-run rule - so a later
    launch with no art= reports None instead of inheriting an older process's
    md5 (the v46 scan did inherit it, and called it the newest).
    """
    found = None
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        m = LINE.match(raw)
        if m:
            ts, rest = m.group("ts"), m.group("rest")
        else:
            mm = MARKER.match(raw)
            if not mm:
                continue
            ts, rest = "", mm.group("rest")
        lm = LAUNCH.search(rest)
        if not lm:
            continue
        tm = TOK.search(rest)
        found = {"ts": ts,
                 "tok": tm.group("tok") if tm else None,
                 "art": lm.group("art"),
                 "line": rest}
    return found

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
     "address (cuid=5001 there only means the frame was readable); "
     "verdict=elsewhere -> va-0xA0000000 is the wrong frame (at= is the true "
     "task address, children-list validated, and cuid=5001 there would mean a "
     "locate-and-patch path could work); cred-elsewhere -> an owner-ids cred "
     "was found in the sweep but it is NOT evidence about the high half "
     "(at=/cred= are physical, C=/P= are virtual); comm-only/miss/cred-miss -> "
     "inconclusive, read cov=; docs/LOGGUIDE.md"),
    ("OPEN-NODE", re.compile(r"^open \S+ (?:errno=|failed errno=)"), "info",
     "a physmap node open failed; v39.1 retries the SAME node on EBUSY and only "
     "moves on when it is absent",
     "busy is normal (a browser stub or a dying payload holds it) - the payload "
     "waits for video40 rather than switching, because video30 hangs at phys "
     "0x46000000 and the scans reach 0x60000000. 'absent' means this model has "
     "a different node numbering: docs/PORTABILITY.md"),
    ("VID40-HELD", re.compile(r"^fail open (?:node|video\d+) after"), "error",
     "every physmap node was held for the whole 120 s retry",
     "a browser stub or a wedged payload owns the nodes; wait ~2 min or "
     "power-cycle, then retry (AGENTS.md trap 3)"),
    ("VID40-RETRY", re.compile(r"^(?:reopen \S+ fd=-1|fail reopen )"), "warn",
     "the physmap node was still held when the hunt needed it",
     "the payload now exits early for a fresh process instead of burning the "
     "rounds; the boot usually still roots on the next attempt"),
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
     "the 31337 listener failed and is retrying (it no longer gives up)",
     "read the message; the payload retries every 5 s, so a transient bind "
     "failure heals without a reboot. Run() timeouts return "
     "'[timeout: killed after 120s]' and keep serving by design"),
    ("UPDATE-OFF", re.compile(r"^autoupdate .*Int32: 0$"), "info",
     "auto-update re-asserted off", "nothing to do"),
    ("UPDATE-FAIL", re.compile(r"^autoupdate fail"), "warn",
     "could not re-assert auto-update off",
     "OTA could replace the app and the boot row; set it by hand "
     "(AGENTS.md 'Auto-update is pinned off')"),
    ("LONG-EXIT", re.compile(r"^long-exit attempt=\d+ count=\d+$"), "info",
     "v45: a LONG-mode pass ended without root and exited for a fresh process",
     "expected after the four fast attempts when this process's mapping is "
     "stale; AUL relaunches and the next attempt re-rolls the mmap. Three "
     "exits per boot, then the old in-process idle - a boot that still fails "
     "after count=3 needs a power-cycle"),
    # ---- v42 service masks (debloat) --------------------------------------
    ("MASK-BEGIN", re.compile(r"^masks begin n=\d+"), "info",
     "the v42 service-mask step started",
     "expect the 'masks=' result line within ~25 s; without it the thread "
     "died - look for MASK-CRASH"),
    ("MASK-SKIP", re.compile(r"^masks skip"), "warn",
     "the mask step was skipped (no policy file, or it ran before uid 0)",
     "no /opt/usr/data/debloat-masks.txt means the documented revert is in "
     "effect and the masks stay session-only: re-run deploy.sh to restore the "
     "list. uid= means a code path error - report it"),
    ("MASK-OK", re.compile(r"^masks=\d+ stopped=\d+ killed=\d+ fail=0 missing=0 "
                           r".*loop-check=ok newhome="), "info",
     "the service-mask step is applied and verified",
     "nothing to do. activating=<n> is context only (unrelated units); "
     "newhome=set(0) is expected while Samsung Home is in front, and "
     "loop-started is normal after a reboot (the transient unit dies with it)"),
    ("MASK-FAIL", re.compile(r"^masks=\d+(?=.*(?:fail=[1-9]|missing=[1-9]|"
                             r"loop-check=(?:failed|skipped)))"), "warn",
     "the mask step ran but did not come out clean (fail>0, missing>0 or "
     "loop-check=failed)",
     "fail = listed units still up after the stop window plus reload/kill "
     "errors; missing = names with no unit file (a vendor rename - drop or "
     "re-map them). A .socket/.path unit has no process, so only its stop job "
     "can take it down. Re-run debloat/tools/mask.sh for a human-paced retry"),
    ("MASK-DEADLINE", re.compile(r"^masks deadline after "), "info",
     "v42.0 only: the per-unit stop loop ran out of budget",
     "fixed in v42.1 - one batched --no-block stop plus a list-units poll; "
     "this line can only come from the first v42 build, and the kill pass "
     "still took the survivors down"),
    ("MASK-UNVERIFIED", re.compile(r"^masks counters unverified"), "warn",
     "the list-units dump failed, so stopped/fail are not measurements",
     "the masks are still written; read the state by hand: systemctl "
     "list-units --all --no-legend --plain | grep <unit>"),
    ("MASK-CRASH", re.compile(r"^masks exception "), "error",
     "the v42 mask thread threw",
     "masks may be partially written; the channel and the rest of the boot are "
     "unaffected (own thread). Read the exception type, then re-run "
     "debloat/tools/mask.sh"),
]

ROOTED = re.compile(r"^SUCCESS-R00T ")
ROOTCHAN = re.compile(r"^ROOTCHAN 31337 uid=(?P<uid>\d+)")
FAILROUND = re.compile(r"^fail (round \d+|no new PHYRFORK.*)$")


def parse_lines(text):
    """Yield (ts, t_or_None, rest) for every beacon line; skip garbage.

    Accepts both the PC log (timestamp + DSHROOT) and the on-TV marker file
    (bare `t=<n>s …`).  For the log, `rest` has the leading `t=<n>s ` uptime
    prefix stripped (it is returned separately as `t`), so every signature
    regex below is anchored on the payload line text itself, exactly as
    Beacon() built it.
    """
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        m = LINE.match(raw)
        if m:
            ts, rest = m.group("ts"), m.group("rest")
        else:
            mm = MARKER.match(raw)
            if not mm:
                continue
            ts, rest = "", mm.group("rest")
        um = UPTIME.search(rest)
        t = int(um.group("t")) if um else None
        if um:
            rest = rest[um.end():].lstrip()
        yield ts, t, rest


def group_boots(entries):
    """Split the stream into boots: kernel uptime resets on a cold boot.

    A `start uid=` line without `pid=` is dropped first: it is not a payload
    launch (Main always logs pid=), and its fake `t=1s` would otherwise split a
    fresh boot out of the log.
    """
    boots, cur, prev_t = [], [], None
    for ts, t, rest in entries:
        if START_NO_PID.match(rest):
            TEST_NOISE["start_without_pid"] += 1
            continue
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
    art = None  # the newest run's artifact md5 (None = pre-v46 or file absent)
    for run in runs:
        n = None
        result = "started"
        run_art = None
        for ts, t, rest in run:
            am = ATTEMPT.match(rest)
            if am:
                n = int(am.group(1))
            sm = START.match(rest)
            if sm and sm.group("art"):
                run_art = sm.group("art")
            if ROOTED.match(rest):
                result = "rooted"
            elif "fast-exit" in rest:
                # both spellings: "fast-exit attempt=1" and
                # "high-alloc ... fast-exit"
                result = "fast-exit"
            elif FAILROUND.match(rest) or rest.startswith("fail "):
                result = " ".join(rest.split()[:3])
        art = run_art  # later runs overwrite: only the newest launch counts
        attempts.append({"attempt": n, "result": result, "art": run_art})

    if rooted_at is not None:
        verdict = f"ROOTED at t={rooted_at}s of TV uptime"
    elif chan_at is not None and chan_uid == 0:
        verdict = f"ROOTED (channel 31337 up as uid 0 at t={chan_at}s)"
    else:
        last = boot[-1][2]
        verdict = f"NOT rooted - last line: {last[:90]}"

    # BLIND-WALK: a whole LONG-MODE pass that never saw a new landmark at all.
    # `seen=0` (and usually an empty `tail:`) means the task list was unreadable,
    # not that the fork failed - so waiting in-process cannot fix it; only a
    # fresh process re-rolls.  The 2026-11-01 deploy restart hunted for 5+
    # minutes in exactly this state.  Line-level signatures cannot see "every
    # round", so this is derived per boot (and only when nothing rooted).
    blind = [b for b in boot if b[2].startswith("fail no new PHYRFORK")]
    long_mode = any("long retry mode" in b[2] for b in boot)
    if (rooted_at is None and chan_uid != 0 and long_mode and blind
            and all("seen=0" in b[2] for b in blind)):
        findings.append({
            "code": "BLIND-WALK", "sev": "warn",
            "msg": "the long-mode pass never saw a new landmark (seen=0 in "
                   "every round): the task list was unreadable",
            "hint": "an in-process retry cannot fix a blind read - only a FRESH "
                    "PROCESS can. v45+ exits for one on its own (the long-exit "
                    "line follows); on v44 and earlier, power-cycle the TV "
                    "(AGENTS.md trap 18, docs/V45-BLIND-WALK.md)",
            "line": blind[-1][2],
        })

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
        "art": art,
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
    ap.add_argument("--newest-start", action="store_true",
                    help="print the newest payload launch line as JSON "
                         "(tok= + art=) and exit; used by root.ps1")
    args = ap.parse_args(argv)

    p = Path(args.file)
    if not p.exists():
        print(f"beacons: no log at {p} - no beacon has ever arrived here.\n"
              f"If the TV just booted: check the server on :80 (pysrv.exe, "
              f"never python.exe), the page load, and the boot row.",
              file=sys.stderr)
        return 2
    if args.newest_start:
        # One implementation of "which launch is newest" for the launcher too;
        # exit 1 with null fields when there is no launch line at all.
        ns = newest_start(p.read_text(encoding="utf-8", errors="replace"))
        print(json.dumps(ns or {"ts": None, "tok": None, "art": None,
                                "line": None}))
        return 0 if ns else 1
    boots = group_boots(list(parse_lines(p.read_text(encoding="utf-8",
                                                        errors="replace"))))
    if not boots:
        print(f"beacons: no DSHROOT lines in {p}", file=sys.stderr)
        return 2
    total = len(boots)
    base = 0
    if args.last > 0:
        boots = boots[-args.last:]
        base = total - len(boots)

    # Number the boots from the FULL log, not from the slice: `--last 1` used to
    # print "boot #0" for what may be the 27th boot (review 2026-10-31).
    report = [analyse_boot(b, base + i) for i, b in enumerate(boots)]
    noise = TEST_NOISE["start_without_pid"]
    if args.json:
        print(json.dumps({"boots": report, "log": str(p),
                          "ignored_start_without_pid": noise}, indent=2))
        return 0

    print(f"beacons: {len(report)} boot(s) in {p}")
    if noise:
        print(f"beacons: ignored {noise} `start uid=` line(s) without pid= "
              f"(test/forged beacons, not a launch)")
    for b in report:
        print(f"\n--- boot #{b['index']}  {b['first_ts']} .. {b['last_ts']}"
              f"  (max t={b['max_t']}s, {b['lines']} lines, {b['runs']} launch(es))")
        print(f"    verdict: {b['verdict']}")
        if b["art"]:
            # the artifact identity the newest process started with; compare it
            # with the deployed md5 (deploy.sh's ART_FILE= line, the state row)
            print(f"    artifact md5: {b['art']}")
        elif b["runs"] and any(a["art"] is None for a in b["attempts"]):
            print("    artifact md5: unknown (pre-v46 start beacon or no "
                  "rootchan.art)")
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
    if last["last_ts"]:
        print(f"\nno beacons after {last['last_ts']}. If the TV has booted since "
              f"then, the app never started or the PC was unreachable "
              f"(server on :80? page loaded? boot row present?). "
              f"Line dictionary: docs/LOGGUIDE.md")
    else:
        print(f"\nend of {p.name} (marker file: no PC timestamps). If the TV has "
              f"booted since then, the app never started or the PC was "
              f"unreachable. Line dictionary: docs/LOGGUIDE.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
