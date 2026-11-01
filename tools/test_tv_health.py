"""Offline tests for `tools/tv_health.py` - no TV, no root channel.

    python tools/test_tv_health.py

The comparison logic (`evaluate`) is pure, so each check gets a healthy fixture
plus one mutation; `read()` is exercised with an injected `run()` that answers
the channel commands from a canned TV, and the registry parser with a temp
ledger.  A new check without a fixture shows up here as an untested PASS.
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tv_health as H  # noqa: E402

FAILS = 0
MD5 = "c540a6ab454d3085044e8ab068c38369"
REG = {"applied": {"com.a", "com.b"}, "never": {"com.keep"},
       "deferred": {"com.later"}, "reverted": {"com.back"}}
UNITS = 29


def check(name, ok, note=""):
    global FAILS
    print(("PASS" if ok else "FAIL"), name, "-", note, flush=True)
    if not ok:
        FAILS += 1


def healthy():
    return {
        "uid": 0, "caps": H.FULL_CAPS, "dll_md5": MD5, "art": MD5,
        "rows": {"com.a": True, "com.b": True, "com.keep": False,
                 "com.later": False, "com.back": False},
        "masks": UNITS, "masked_units": UNITS, "unmasked": 0,
        "activating": 0, "sentinels": 2,
        "easysetup": "active", "beacon": {"tok": "deadbeef", "art": MD5},
    }


def failed(r, reg=REG, units=UNITS, md5=MD5):
    return [c["name"] for c in H.evaluate(r, reg, units, md5) if not c["ok"]]


def test_evaluate():
    checks = H.evaluate(healthy(), REG, UNITS, MD5)
    check("healthy TV passes every check", not failed(healthy()), str(failed(healthy())))
    check("evaluate returns the 12 checks", len(checks) == 12, str(len(checks)))
    check("check names are unique", len({c["name"] for c in checks}) == len(checks))

    muts = {
        "root": lambda r: r.update(uid=5001),
        "caps too narrow": lambda r: r.update(caps="0000003fffffff0"),
        "artifact": lambda r: r.update(dll_md5="0" * 32),
        "witness": lambda r: r.update(art=""),
        "applied": lambda r: r["rows"].update({"com.b": False}),
        "off-list": lambda r: r["rows"].update({"com.keep": True}),
        "count (extra disabled)": lambda r: (r["rows"].update({"com.extra": True}),),
        "masks": lambda r: r.update(masks=28),
        "masked (one not masked-runtime)": lambda r: r.update(masked_units=UNITS - 1),
        "masked (one unmasked)": lambda r: r.update(unmasked=1),
        "loops": lambda r: r.update(activating=1),
        "sentinels": lambda r: r.update(sentinels=1),
        "smarthome": lambda r: r.update(easysetup="inactive"),
        "beacon art": lambda r: r.update(beacon={"tok": "deadbeef", "art": "0" * 32}),
        "beacon token": lambda r: r.update(beacon={"tok": None, "art": MD5}),
    }
    for label, mut in muts.items():
        r = healthy()
        mut(r)
        f = failed(r)
        check(f"mutation caught: {label}", bool(f), str(f))

    r = healthy()
    r["rows"]["com.a"] = True
    r["rows"]["com.b"] = False
    f = failed(r)
    check("missing applied row fails 'applied' and 'count'",
          {"applied", "count"} <= set(f), str(f))

    r = healthy()
    r["rows"]["com.later"] = True
    check("a disabled deferred app fails 'off-list'",
          "off-list" in failed(r), str(failed(r)))

    # an extra disabled app that is not in any registry status: count only
    r = healthy()
    r["rows"]["com.extra"] = True
    f = failed(r)
    check("unknown disabled app fails 'count' but not 'off-list'",
          "count" in f and "off-list" not in f, str(f))


def test_read():
    def fake(cmd):
        if "id -u" in cmd:
            return "0\nCapEff:\t0000003fffffffff"
        if cmd.startswith("md5sum"):
            return f"{MD5}  /opt/usr/apps/com.samsung.tv.MultiControl-Service/bin/MultiControlService.dll"
        if cmd.startswith("cat "):
            return MD5
        if "SELECT app_id" in cmd:
            return "com.a,true\ncom.b,true\ncom.keep,false"
        if "is-enabled" in cmd:
            return "masked=3 bad=0"
        if "find /run" in cmd:
            return "29"
        if "activating" in cmd:
            return "0"
        if cmd.startswith("ls "):
            return "/opt/usr/share/systemd/system/canalysis-daemon\n/opt/usr/share/systemd/system/pisa-service"
        if "is-active" in cmd:
            return "active"
        raise AssertionError(f"unexpected command: {cmd}")

    log = Path(tempfile.mkdtemp()) / "beacons.log"
    log.write_text("2026-01-01T00:00:00 DSHROOT tok=deadbeef t=5s "
                   f"start uid=5001 pid=1 art={MD5}\n", encoding="utf-8")
    r = H.read("198.51.100.1", run=fake, log=log)
    check("read: uid and caps", r["uid"] == 0 and r["caps"] == H.FULL_CAPS, str((r["uid"], r["caps"])))
    check("read: installed md5", r["dll_md5"] == MD5, r["dll_md5"])
    check("read: rootchan.art", r["art"] == MD5, r["art"])
    check("read: app rows", r["rows"] == {"com.a": True, "com.b": True, "com.keep": False}, str(r["rows"]))
    check("read: masks/loops/sentinels", (r["masks"], r["activating"], r["sentinels"]) == (29, 0, 2),
          str((r["masks"], r["activating"], r["sentinels"])))
    check("read: masked-runtime counts", (r["masked_units"], r["unmasked"]) == (3, 0),
          str((r["masked_units"], r["unmasked"])))
    check("read: easysetup", r["easysetup"] == "active", r["easysetup"])
    check("read: newest beacon launch", (r["beacon"] or {}).get("tok") == "deadbeef"
          and (r["beacon"] or {}).get("art") == MD5, str(r["beacon"]))


def test_registry():
    d = Path(tempfile.mkdtemp())
    p = d / "registry.tsv"
    p.write_text(
        "# comment\n"
        "com.a\tapp\tapplied\tr\te\t2026-11-01\towner\n"
        "com.u\tunit\tnever\tr\te\t2026-11-01\t\n"
        "com.c\tapp\tnever\tr\te\t2026-11-01\t\n", encoding="utf-8")
    reg = H.registry(p)
    check("registry parser: groups by status, apps only",
          reg == {"applied": {"com.a"}, "never": {"com.c"}}, str(reg))
    real = H.registry()
    check("real registry parses with a non-empty applied set",
          len(real.get("applied", set())) > 0, str({k: len(v) for k, v in real.items()}))


def test_cli():
    # main() reads TV_IP / ROOT_TV when --tv is absent, so an exported address
    # (as the live layers need) would make this call hit the TV instead of
    # exiting 2.  Clear them for the assertion, then put them back.
    saved = {k: os.environ.pop(k, None) for k in ("TV_IP", "ROOT_TV")}
    try:
        check("no --tv exits 2", H.main([]) == 2)
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def main() -> int:
    test_evaluate()
    test_read()
    test_registry()
    test_cli()
    print()
    print("tv-health tests ok" if not FAILS else f"{FAILS} failure(s)")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
