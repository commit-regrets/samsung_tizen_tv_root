"""Offline test for tools/sanitize_for_public.py - no repo content needed.

Covers, on a scratch tree:
  * copy mode replaces every token class (device, firmware, IPs, subnets) and
    leaves the placeholders behind;
  * binary files pass through byte-identical (payload.dll / the shellcode blob
    must keep their md5s in a public copy);
  * files under skipped trees (server/logs, payload/obj, .git) are not copied;
  * "10.0.301" (pinned SDK in payload/global.json) is NOT matched by the
    <WIFI_SUBNET>. Wi-Fi subnet token - the trailing dot is load-bearing;
  * --check exits 1 on a tree that still holds a token and 0 once clean.
"""
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAN = HERE / "sanitize_for_public.py"

TOKENS = {
    "tv_ip": "<TV_IP>",
    "host_ip": "<HOST_IP>",
    "lan": "<LAN>.0",
    "vpn": "<VPN_GW>",
    "wifi": "<WIFI_SUBNET>.7",
    "fw": "<FIRMWARE_BUILD>",
    "fw_short": "<FIRMWARE> 01400",
    "platform": "<PLATFORM_INTERNAL>",
    "model": "<MODEL>",
    "duid": "<DUID>",
    # computed, not literal - same reason as SUBS in the sanitizer itself
    "home": "C:\\Users\\" + Path.home().name,
}
PLACE = ["<TV_IP>", "<HOST_IP>", "<LAN>.", "<VPN_GW>", "<WIFI_SUBNET>.",
         "<FIRMWARE_BUILD>", "<FIRMWARE>", "<PLATFORM_INTERNAL>", "<MODEL>",
         "<DUID>", "<HOME>"]


def run(*args):
    return subprocess.run([sys.executable, str(SAN), *args],
                          capture_output=True, text=True)


def main() -> int:
    ok = True

    def check(name, cond, note=""):
        nonlocal ok
        print(("PASS" if cond else "FAIL"), name, ("- " + note if note else ""))
        ok = ok and cond

    tmp = Path(tempfile.mkdtemp(prefix="san_selftest_"))
    try:
        src = tmp / "src"
        (src / "server" / "logs").mkdir(parents=True)
        (src / "payload" / "obj").mkdir(parents=True)
        notes = src / "docs" / "notes.md"
        notes.parent.mkdir(parents=True)
        notes.write_text(
            "TV at " + TOKENS["tv_ip"] + " PC at " + TOKENS["host_ip"] +
            " lan " + TOKENS["lan"] + " vpn " + TOKENS["vpn"] +
            " wifi " + TOKENS["wifi"] + "\nfw " + TOKENS["fw"] +
            " fw2 " + TOKENS["fw_short"] + "\nplat " + TOKENS["platform"] +
            " model " + TOKENS["model"] + " duid " + TOKENS["duid"] +
            "\nlog from " + TOKENS["home"] + "\\projects\\samsung_tv_root" +
            '\nper-deploy tok=<BEACON_TOKEN> and "beacon_token": "<BEACON_TOKEN>"' +
            '\ntranscript TOKEN_FILE=<BEACON_TOKEN> (the prose form that shipped)' +
            " forged tok=deadbeef stays" +
            "\nsdk pin 10.0.301 stays\n", encoding="utf-8")
        binary = src / "server" / "payload.bin"
        payload = b"MZ" + struct.pack("<Q", 0xDEADBEEF) + bytes(range(256))
        binary.write_bytes(payload)
        (src / "server" / "logs" / "beacons.log").write_text(
            TOKENS["tv_ip"] + " leaked?\n", encoding="utf-8")
        (src / "payload" / "obj" / "junk.json").write_text(
            TOKENS["host_ip"] + "\n", encoding="utf-8")

        # Copy mode publishes tracked files only: git init, track everything
        # except one secret log (the rootwatch.log class that leaked into the
        # 2026-11-13 snapshot until the filter existed).  No commit needed -
        # git ls-files lists staged files.
        secret = src / "tools" / "state" / "rootwatch.log"
        secret.parent.mkdir(parents=True)
        secret.write_text(TOKENS["tv_ip"] + " in an untracked log\n",
                          encoding="utf-8")
        subprocess.run(["git", "-C", str(src), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(src), "add", "docs", "server"],
                       check=True)

        # --check must fail on the dirty tree, naming the file
        r = run("--check", str(src))
        check("--check exits 1 on tokens", r.returncode == 1, r.stdout.strip())
        check("--check names notes.md", "notes.md" in r.stdout)
        check("--check ignores skipped trees",
              "beacons.log" not in r.stdout and "junk.json" not in r.stdout)

        # copy mode
        dst = tmp / "pub"
        r = run(str(src), str(dst))
        check("copy exits 0", r.returncode == 0, r.stdout.splitlines()[0]
              if r.stdout else "")
        out = (dst / "docs" / "notes.md").read_text(encoding="utf-8")
        for t in TOKENS.values():
            check(f"token gone: {t}", t not in out)
        for p in PLACE:
            check(f"placeholder present: {p}", p in out)
        check("sdk pin survives", "10.0.301" in out)
        check("per-deploy token redacted",
              "abcd1234" not in out and "<BEACON_TOKEN>" in out)
        check("TOKEN_FILE prose form redacted",
              "TOKEN_FILE=<BEACON_TOKEN>" in out and "abcd1234" not in out)
        check("home path redacted",
              "<HOME>" in out and Path.home().name not in out)
        check("forged test token allowed", "tok=deadbeef" in out)
        check("binary passthrough byte-exact",
              (dst / "server" / "payload.bin").read_bytes() == payload)
        check("skipped trees not copied", not (dst / "server" / "logs").exists()
              and not (dst / "payload" / "obj").exists())
        check("untracked files not copied", not (dst / "tools").exists(),
              "the untracked secret log must not leave the tree")

        # a clean tree passes --check
        r = run("--check", str(dst))
        check("--check exits 0 on sanitized copy", r.returncode == 0,
              r.stdout.strip())

        # copy refuses to overwrite
        r = run(str(src), str(dst))
        check("copy refuses existing dst", r.returncode == 2)

        # invalid utf-8 in --check is skipped, not a crash
        (dst / "docs" / "blob.bin").write_bytes(b"\xff\xfe\x00abc")
        r = run("--check", str(dst))
        check("--check skips binary files", r.returncode == 0)

        # --check also accepts a single FILE path (it crashed on one until
        # the rel value was made a Path - found gating docs/VETRO.md)
        r = run("--check", str(notes))
        check("--check exits 1 on a single dirty file", r.returncode == 1,
              r.stdout.strip())
        r = run("--check", str(dst / "docs" / "notes.md"))
        check("--check exits 0 on a single clean file", r.returncode == 0,
              r.stdout.strip())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nsanitize selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
