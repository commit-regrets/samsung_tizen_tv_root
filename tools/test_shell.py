"""Dry tests for server/deploy.sh and server/uninstall.sh — no TV, no root.

    python tools/test_shell.py

Both scripts drive absolute TV paths (`/opt/usr/...`, `/opt/dbspace/...`,
`/tmp/...`) and shell out to `chsmack`, `sqlite3`, `aulctl`, `curl`, `ls -lZ`.
This harness runs a *copy* of each script with those prefixes rewritten into a
throwaway tree, and with stubs for the TV-only commands on PATH, so the logic
that used to fail silently can be exercised on any PC with a POSIX `sh`
(Git Bash on Windows, /bin/sh elsewhere):

  * deploy refuses a payload whose md5/size do not match WANT/SIZE_WANT;
  * deploy creates the stock IL/AOT backups when they are absent, and records
    their md5 (the #3 regression: uninstall used to be impossible from a clone);
  * deploy aborts on a SMACK label mismatch and leaves the live DLL untouched
    (the #8 regression: it used to warn, replace the DLL anyway, and print
    DEPLOY_DONE);
  * deploy aborts when the boot row does not read back as 1;
  * uninstall hard-fails without a stock backup, rejects a corrupted one, and
    restores + relabels on the happy path (boot row removed);
  * uninstall aborts on a label mismatch instead of printing UNINSTALL_DONE.

The rewrites and the stock-hash substitution are the harness's; a green run
proves the scripts' control flow, not that the md5s in the repo are right (that
is what the on-TV checks in docs/TESTING.md are for).
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server"
PAYLOAD = SERVER / "payload.dll"
STOCK_IL = b"stock-il-fixture\n"
STOCK_NI = b"stock-ni-fixture\n"

STUBS = {
    "curl": r"""#!/bin/sh
out=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -fsS|-sS|-s|-f) shift ;;
    *) url="$1"; shift ;;
  esac
done
src="$TEST_DOCROOT/${url##*/}"
[ -f "$src" ] || exit 22
if [ -n "$out" ]; then cp "$src" "$out"; else cat "$src"; fi
exit 0
""",
    "chsmack": r"""#!/bin/sh
# chsmack -a LABEL FILE...
[ "$1" = "-a" ] || exit 1
label="$2"; shift 2
[ -n "$TEST_CHSMACK_FAIL" ] && exit 1
for f in "$@"; do
  printf '%s' "$label" > "$f.label"
done
exit 0
""",
    "ls": r"""#!/bin/sh
# Only the forms the scripts use: `-lZ FILE`, `-dt DIRS...`, plain `ls GLOB`.
case " $* " in
  *" -lZ "*)
    for f in "$@"; do
      [ "$f" = "-lZ" ] && continue
      [ -e "$f" ] || continue
      if [ -f "$f.label" ]; then label=$(cat "$f.label")
      else label="User::Pkg::org.tizen.browser"; fi
      size=$(wc -c < "$f")
      printf -- '-rw-r--r-- 1 root root %s %s Oct 24 20:00 %s\n' "$label" "$size" "$f"
    done ;;
  *" -dt "*)
    for f in "$@"; do [ "$f" = "-dt" ] || printf '%s\n' "$f"; done ;;
  *)
    for f in "$@"; do printf '%s\n' "$f"; done ;;
esac
exit 0
""",
    "sqlite3": r"""#!/bin/sh
# sqlite3 DB SQL ...  (boot_sequence bookkeeping only)
db="$1"; shift
sql="$*"
case "$sql" in
  *"select count(*)"*)
    n=$(cat "$TEST_ROOT/db.count" 2>/dev/null || echo 0); printf '%s\n' "$n" ;;
  *"insert or replace into boot_sequence"*)
    [ -n "$TEST_SQLITE_NOOP" ] || printf '1' > "$TEST_ROOT/db.count" ;;
  *"delete from boot_sequence"*)
    [ -n "$TEST_SQLITE_NOOP" ] || printf '0' > "$TEST_ROOT/db.count" ;;
esac
exit 0
""",
    "aulctl": r"""#!/bin/sh
case "$1" in
  reload) echo "Reload result: 0"; exit ${TEST_AULCTL_RC:-0} ;;
  *) exit 0 ;;
esac
""",
    "id": r"""#!/bin/sh
# The scripts run as root on the TV; the harness must claim the same.
case "$1" in
  -u) echo 0 ;;
  *)  echo "uid=0(root) gid=0(root) groups=0(root)" ;;
esac
exit 0
""",
}


def find_sh():
    for c in (os.environ.get("TEST_SH"), r"C:\Program Files\Git\bin\sh.exe",
              "/bin/sh", "/usr/bin/sh"):
        if c and Path(c).exists():
            return c
    return None


def write_stubs(bin_dir: Path):
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name, body in STUBS.items():
        p = bin_dir / name
        p.write_text(body.replace("\r\n", "\n"), encoding="ascii", newline="\n")
        try:
            os.chmod(p, 0o755)
        except OSError:
            pass


def rewrite(script: Path, dest: Path, *, stock_il_md5: str, stock_ni_md5: str,
            host: str):
    text = script.read_text(encoding="ascii", errors="replace")
    text = text.replace("/opt/usr", "@ROOT@/opt/usr")
    text = text.replace("/opt/dbspace", "@ROOT@/opt/dbspace")
    text = text.replace("/tmp/", "@ROOT@/tmp/")
    text = re.sub(r"(?m)^IL_STOCK=.*$", f"IL_STOCK={stock_il_md5}", text)
    text = re.sub(r"(?m)^NI_STOCK=.*$", f"NI_STOCK={stock_ni_md5}", text)
    text = re.sub(r"(?m)^IL_MD5=.*$", f"IL_MD5={stock_il_md5}", text)
    text = re.sub(r"(?m)^NI_MD5=.*$", f"NI_MD5={stock_ni_md5}", text)
    text = re.sub(r"(?m)^H=.*$", f"H=http://{host}", text)
    text = text.replace("@ROOT@", "$TEST_ROOT")
    dest.write_text(text, encoding="ascii", newline="\n")


class Fixture:
    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="shelltest-"))
        self.root = self.dir
        self.bin = self.root / "opt/usr/apps/com.samsung.tv.MultiControl-Service/bin"
        self.share = self.root / "opt/usr/home/owner/share"
        self.db = self.root / "opt/dbspace/user/5001"
        self.tmp = self.root / "tmp"
        self.stubs = self.root / "bin"
        self.docroot = self.root / "docroot"
        for d in (self.bin / ".native_image", self.share, self.db, self.tmp,
                  self.docroot, self.stubs):
            d.mkdir(parents=True, exist_ok=True)
        (self.bin / "MultiControlService.dll").write_bytes(STOCK_IL)
        (self.bin / ".native_image/MultiControlService.ni.dll").write_bytes(STOCK_NI)
        (self.db / ".appsvc.db").write_bytes(b"")
        shutil.copy(PAYLOAD, self.docroot / "payload.dll")
        write_stubs(self.stubs)
        self.il_md5 = hashlib.md5(STOCK_IL).hexdigest()
        self.ni_md5 = hashlib.md5(STOCK_NI).hexdigest()
        self.deploy = self.root / "deploy.sh"
        self.uninstall = self.root / "uninstall.sh"
        rewrite(SERVER / "deploy.sh", self.deploy, stock_il_md5=self.il_md5,
                stock_ni_md5=self.ni_md5, host="pc.test")
        rewrite(SERVER / "uninstall.sh", self.uninstall, stock_il_md5=self.il_md5,
                stock_ni_md5=self.ni_md5, host="pc.test")
        self.runner = self.root / "runner.sh"
        self.runner.write_text(
            'HERE=$(pwd)\nPATH="$HERE/bin:/usr/bin:/bin:/mingw64/bin"\n'
            'export PATH\nexport TEST_ROOT="$HERE"\n. ./"$1"\n',
            encoding="ascii", newline="\n")

    def run(self, script, env_extra=None):
        env = dict(os.environ)
        env.pop("TEST_SH", None)
        env.update(TEST_ROOT=str(self.root), TEST_DOCROOT=str(self.docroot),
                   MSYS2_ARG_CONV_EXCL="*")
        env.update(env_extra or {})
        sh = find_sh()
        cmd = [sh, "-c",
               'cd "$1" || exit 9; HERE=$(pwd); '
               'PATH="$HERE/bin:/usr/bin:/bin:/mingw64/bin"; export PATH; '
               'TEST_ROOT="$HERE"; export TEST_ROOT; . ./"$2"',
               "_", str(self.root).replace("\\", "/"), script]
        return subprocess.run(cmd, env=env, capture_output=True, text=True,
                              timeout=90)

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def check(name, ok, note=""):
    print(("PASS" if ok else "FAIL"), name, ("- " + note if note else ""), flush=True)
    return ok


def deploy_cases(sh):
    failed = 0

    def fresh():
        return Fixture()

    # --- happy path from a stock state: backups must be created -------------
    f = fresh()
    try:
        r = f.run("deploy.sh")
        out = r.stdout + r.stderr
        ok = (r.returncode == 0 and "BACKUP_IL=ok" in out and "BACKUP_NI=ok" in out
              and "COPY=ok" in out and "DEPLOY_DONE" in out)
        failed += not check("deploy: stock backups created", ok,
                            f"rc={r.returncode} " + " ".join(
                                l for l in out.splitlines()
                                if l.startswith(("BACKUP_", "COPY", "DEPLOY_DONE", "BOOT"))))
        ok = ((f.share / "mcs_orig.dll").read_bytes() == STOCK_IL
              and (f.share / "mcs_ni_orig.dll").read_bytes() == STOCK_NI
              and (f.share / "mcs_orig.md5").read_text().strip() == f.il_md5)
        failed += not check("deploy: backups are byte-exact stock + md5 recorded", ok)
        ok = (f.bin / "MultiControlService.dll").read_bytes() == PAYLOAD.read_bytes()
        failed += not check("deploy: payload installed", ok)
    finally:
        f.cleanup()

    # --- wrong payload bytes: the size/md5 gate must abort ------------------
    f = fresh()
    try:
        bad = bytearray(PAYLOAD.read_bytes())
        bad[100] ^= 0xFF
        (f.docroot / "payload.dll").write_bytes(bytes(bad))
        r = f.run("deploy.sh")
        out = r.stdout + r.stderr
        ok = r.returncode != 0 and "COPY=skip" in out and "DEPLOY_DONE" not in out
        failed += not check("deploy: bad payload refused", ok,
                            f"rc={r.returncode}")
        ok = (f.bin / "MultiControlService.dll").read_bytes() == STOCK_IL
        failed += not check("deploy: live DLL untouched after refusal", ok)
    finally:
        f.cleanup()

    # --- label mismatch: abort BEFORE the rename, keep the live DLL ---------
    f = fresh()
    try:
        r = f.run("deploy.sh", {"TEST_CHSMACK_FAIL": "1"})
        out = r.stdout + r.stderr
        ok = r.returncode != 0 and "DLL_LABEL_MISMATCH" in out and "COPY=ok" not in out
        failed += not check("deploy: label mismatch aborts", ok, f"rc={r.returncode}")
        ok = (f.bin / "MultiControlService.dll").read_bytes() == STOCK_IL
        failed += not check("deploy: live DLL untouched on label mismatch", ok)
        ok = not (f.bin / "MultiControlService.dll.tmp").exists()
        failed += not check("deploy: temp DLL removed on label mismatch", ok)
    finally:
        f.cleanup()

    # --- boot row does not read back: abort, no DEPLOY_DONE -----------------
    f = fresh()
    try:
        r = f.run("deploy.sh", {"TEST_SQLITE_NOOP": "1"})
        out = r.stdout + r.stderr
        ok = r.returncode != 0 and "BOOT_ROW_WARN" in out and "DEPLOY_DONE" not in out
        failed += not check("deploy: bad boot row aborts", ok, f"rc={r.returncode}")
    finally:
        f.cleanup()

    return failed


def uninstall_cases(sh):
    failed = 0

    def prepared(with_backups=True, corrupt=False):
        f = Fixture()
        # bin holds the payload, boot row set, backups on the share as a deploy
        # would have left them.
        (f.bin / "MultiControlService.dll").write_bytes(PAYLOAD.read_bytes())
        (f.root / "db.count").write_text("1")
        if with_backups:
            il = b"corrupt\n" if corrupt else STOCK_IL
            (f.share / "mcs_orig.dll").write_bytes(il)
            (f.share / "mcs_ni_orig.dll").write_bytes(STOCK_NI)
        return f

    f = prepared(with_backups=False)
    try:
        r = f.run("uninstall.sh")
        out = r.stdout + r.stderr
        failed += not check("uninstall: no backup hard-fails",
                            r.returncode != 0 and "NO_IL_BACKUP" in out,
                            f"rc={r.returncode}")
    finally:
        f.cleanup()

    f = prepared(corrupt=True)
    try:
        r = f.run("uninstall.sh")
        out = r.stdout + r.stderr
        failed += not check("uninstall: corrupt backup rejected",
                            r.returncode != 0 and "BAD_IL_BACKUP" in out,
                            f"rc={r.returncode}")
    finally:
        f.cleanup()

    f = prepared()
    try:
        r = f.run("uninstall.sh")
        out = r.stdout + r.stderr
        ok = (r.returncode == 0 and "UNINSTALL_DONE" in out
              and "BOOT_ROW=removed" in out)
        failed += not check("uninstall: happy path restores", ok, f"rc={r.returncode}")
        ok = (f.bin / "MultiControlService.dll").read_bytes() == STOCK_IL
        failed += not check("uninstall: stock IL restored", ok)
        ok = (f.bin / ".native_image/MultiControlService.ni.dll").read_bytes() == STOCK_NI
        failed += not check("uninstall: stock AOT restored", ok)
        ok = (f.root / "db.count").read_text().strip() == "0"
        failed += not check("uninstall: boot row removed", ok)
        ok = not (f.share / "rootchan.allow").exists()
        failed += not check("uninstall: our leftovers removed", ok)
    finally:
        f.cleanup()

    f = prepared()
    try:
        r = f.run("uninstall.sh", {"TEST_CHSMACK_FAIL": "1"})
        out = r.stdout + r.stderr
        failed += not check("uninstall: label mismatch aborts",
                            r.returncode != 0 and "LABEL_WARN" in out
                            and "UNINSTALL_DONE" not in out,
                            f"rc={r.returncode}")
    finally:
        f.cleanup()

    return failed


def main() -> int:
    sh = find_sh()
    if sh is None:
        print("SKIP: no POSIX sh found (set TEST_SH=/path/to/sh)")
        return 0
    print(f"using {sh}", flush=True)
    failed = deploy_cases(sh) + uninstall_cases(sh)
    print(flush=True)
    if failed:
        print(f"{failed} check(s) failed")
        return 1
    print("shell tests ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
