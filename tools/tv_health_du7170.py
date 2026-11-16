"""DU7170 post-boot health check over TCP 31337.

    python tools/tv_health_du7170.py [--tv IP] [--json]

Read-only. Exit 0 = all pass, 1 = at least one FAIL, 2 = connect error.
"""
import argparse
import hashlib
import json
import socket
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DLL_LOCAL = ROOT / "payload-du7170" / "bin" / "Release" / "net6.0" / "MultiControlService.dll"
DLL_TV = "/opt/usr/apps/com.samsung.tv.MultiControl-Service/bin/MultiControlService.dll"
MASKS_FILE = "/opt/usr/data/debloat-masks.txt"
APPS_FILE = "/opt/usr/data/debloat-apps.txt"
HOSTS_FILE = "/opt/usr/data/hosts.custom"
ENFORCE_FILE = "/opt/usr/data/debloat-enforce"
SETHOME_DLL = "/opt/usr/data/sethome/SetHome.dll"
PKG_DB = "/opt/dbspace/.pkgmgr_parser.db"


def tv_cmd(tv: str, cmd: str, timeout: float = 15) -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((tv, 31337))
    s.recv(64)
    s.sendall((cmd + "\n").encode())
    time.sleep(3)
    buf = b""
    while True:
        try:
            chunk = s.recv(16384)
            if not chunk:
                break
            buf += chunk
            if b"du7170#" in buf:
                break
        except socket.timeout:
            break
    s.close()
    return buf.decode("utf-8", errors="replace").replace("du7170# ", "").strip()


def check(name: str, passed: bool, detail: str = "") -> dict:
    return {"name": name, "status": "PASS" if passed else "FAIL", "detail": detail}


def run_checks(tv: str) -> list[dict]:
    results = []

    # 1. Root
    uid = tv_cmd(tv, "id -u")
    results.append(check("root", uid.strip() == "0", f"uid={uid.strip()}"))

    # 2. Capabilities
    caps = tv_cmd(tv, "cat /proc/self/status | grep CapEff | awk '{print $2}'")
    results.append(check("capabilities", "3fffffffff" in caps, caps.strip()))

    # 3. Payload artifact
    if DLL_LOCAL.exists():
        local_md5 = hashlib.md5(DLL_LOCAL.read_bytes()).hexdigest()
        remote = tv_cmd(tv, f"md5sum {DLL_TV}")
        remote_md5 = remote.split()[0] if remote else ""
        results.append(check("artifact", local_md5 == remote_md5,
                             f"local={local_md5[:8]} tv={remote_md5[:8]}"))
    else:
        results.append(check("artifact", False, "no local build"))

    # 4. Service masks
    mask_count = tv_cmd(tv, "ls /run/systemd/system/ 2>/dev/null | grep -v '^$' | wc -l")
    expected = tv_cmd(tv, f"grep -v '^#' {MASKS_FILE} 2>/dev/null | grep -v '^$' | wc -l")
    results.append(check("masks", int(mask_count or 0) >= int(expected or 0),
                         f"masked={mask_count.strip()} expected>={expected.strip()}"))

    # 5. Apps disabled (check that no listed app is still enabled)
    disabled = tv_cmd(tv, f"sqlite3 -readonly {PKG_DB} \"select count(*) from package_app_info where app_disable='true';\"")
    not_disabled = tv_cmd(tv, (
        f"grep -v '^#' {APPS_FILE} | grep -v '^$' | while read id; do "
        f"sqlite3 -readonly {PKG_DB} \"select app_disable from package_app_info where app_id='$id';\" "
        f"| grep -qv true && echo $id; done | wc -l"))
    n = 0
    try:
        n = int(not_disabled.strip().split("\n")[-1])
    except (ValueError, IndexError):
        pass
    results.append(check("apps-disabled", n == 0,
                         f"disabled={disabled.strip()} still-enabled={n}"))

    # 6. Hosts bind mount
    hosts_entries = tv_cmd(tv, "grep -c '127.0.0.1' /etc/hosts")
    results.append(check("hosts", int(hosts_entries or 0) > 5, f"entries={hosts_entries.strip()}"))

    # 7. Home button
    home = tv_cmd(tv, f"/usr/bin/dotnet {SETHOME_DLL} query 2>&1 | grep current_home")
    results.append(check("home-remap", "HomeScreen.Launcher" in home, home.strip()))

    # 8. Policy files exist
    for name, path in [("masks-file", MASKS_FILE), ("apps-file", APPS_FILE),
                       ("hosts-file", HOSTS_FILE), ("enforce-marker", ENFORCE_FILE),
                       ("sethome-dll", SETHOME_DLL)]:
        r = tv_cmd(tv, f"test -f {path} && echo EXISTS || echo MISSING")
        results.append(check(name, "EXISTS" in r, path))

    # 9. CEC standby ignore (session-only, re-applied at boot)
    # Can't easily verify, just check hdmicec-service is running
    r = tv_cmd(tv, "pidof hdmicec-service 2>/dev/null")
    results.append(check("hdmicec-service", len(r.strip()) > 0, f"pid={r.strip()}"))

    # 10. Boot payload log
    r = tv_cmd(tv, "grep -c 'thread:' /tmp/.dsh_du7170.log 2>/dev/null")
    results.append(check("boot-enforcement", int(r or 0) >= 4, f"threads-logged={r.strip()}"))

    return results


def main():
    parser = argparse.ArgumentParser(description="DU7170 TV health check")
    parser.add_argument("--tv", default="192.168.178.70")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        results = run_checks(args.tv)
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        print(f"CONNECT ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        fails = 0
        for r in results:
            mark = "PASS" if r["status"] == "PASS" else "FAIL"
            if mark == "FAIL":
                fails += 1
            print(f"  [{mark}] {r['name']:20s}  {r['detail']}")
        total = len(results)
        print(f"\n{total - fails}/{total} passed" + (" — ALL GREEN" if fails == 0 else f" — {fails} FAILED"))

    sys.exit(0 if all(r["status"] == "PASS" for r in results) else 1)


if __name__ == "__main__":
    main()
