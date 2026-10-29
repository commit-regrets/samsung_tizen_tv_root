"""Offline tests for the debloat/ tooling - no TV, no root channel.

Runs the TV-side scripts (apply/restore/mask/unmask)
under a POSIX sh with their absolute paths rewritten into a temp tree and
stub executables for everything that talks to the TV (pkgcmd, systemctl,
dbus-send).  The stubs record every call, so the tests assert on behaviour,
not output text:

  * every script refuses to run without a list FILE argument (exit 2, no TV
    command): the old `${LIST:--}` default was a literal file named "-", so
    a no-arg or piped run reported "0 of 0" and exited 0;
  * apply.sh dry run records NO pkgcmd call, and a denylisted entry fails
    the dry run (the dry run is the gate for the real one);
  * real run disables in list order and writes the undo log (echo + pkgcmd
    -A per package) BEFORE the first disable;
  * the hard denylist (carrier, coba.adagent, privacy UIs, Home/menu, DRM,
    screen-analysis, vetrotvapp) is refused even when the list asks;
  * canalysis/pisa plant their vendor sentinels, stop those units, and fail
    the run loudly when a sentinel cannot be written; restore.sh removes
    the sentinels again;
  * injection attempts (spaces, ;, &, |, backticks, $) are refused and
    reach no command;
  * a pkgcmd/sqlite failure is counted, still leaves its undo line, still
    runs picture-guard, and fails the script;
  * restore.sh re-activates everything with --global, stops at the first
    flag failure, and skips whitespace-only lines;
  * mask.sh masks only names that have a unit file (MISSING fails the run),
    does one daemon-reload before any stop, never starts a unit whose mask
    it could not create, and its optional kill pass kills a process whose
    exe is the listed /usr/bin binary (POSIX only - /proc + readlink);
  * whitespace-only list lines are skipped everywhere;
  * every committed list file contains bare ids only, never a denylist
    entry, and the unit count matches the documented number.

Needs `sh` (Git Bash is found even when it is not on PATH); skips (exit 77)
only where no sh exists at all.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEB = ROOT / "debloat"

DENY = ["com.samsung.tv.MultiControl-Service", "com.samsung.tv.coba.adagent",
        "com.samsung.tv.coba.privacy_app", "tv6pbVMQFF", "vetrotvapp",
        "org.tizen.menu", "com.samsung.tv.home.sidebar",
        "com.samsung.tv.screen-analysis-dbmgr",
        "unified-drm-playready-PontusM"]
TIER1 = ["adplatform.ADPlayer", "com.samsung.tizen.samsung-analytics",
         "com.samsung.tv.ad-web-framework", "com.samsung.tv.adplayer",
         "com.samsung.tv.canalysis-service", "com.samsung.tv.cis-api-service-app",
         "com.samsung.tv.contents-recognition-dbmgr",
         "com.samsung.tv.nvision-analysis-dbmgr", "com.samsung.tv.pisa-service",
         "com.samsung.tv.targeted-ad-service", "content-grab-service"]

# TV absolute paths -> the fixture tree.  Longest first: /prd/usr/bin must win
# over /usr/bin, and /usr/lib/systemd over nothing else, in ONE pass.
TV_MAP = {
    "/prd/usr/bin": "$T/prd/usr/bin",
    "/prd/usr/lib/systemd": "$T/prd/usr/lib/systemd",
    "/usr/lib/systemd": "$T/usr/lib/systemd",
    "/lib/systemd/system": "$T/lib/systemd/system",
    "/etc/systemd/system": "$T/etc/systemd/system",
    "/usr/bin": "$T/usr/bin",
    "/opt/usr": "$T/opt/usr",
    "/run/systemd": "$T/run/systemd",
    "/tmp/": "$T/tmp/",
}
TV_PATH = re.compile("|".join(re.escape(k) for k in
                              sorted(TV_MAP, key=len, reverse=True)))


def find_sh():
    """sh for the scripts.  Git Bash is not always on PATH on Windows; find
    its standard installs instead of skipping the whole layer (review
    2026-10-30: a skip was reported as PASS by test_all)."""
    found = shutil.which("sh")
    if found:
        return found
    cands = [Path("C:/Program Files/Git/bin/sh.exe"),
             Path("C:/Program Files (x86)/Git/bin/sh.exe"),
             Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Git/bin/sh.exe"]
    for c in cands:
        if c.is_file():
            os.environ["PATH"] = f"{c.parent}{os.pathsep}{os.environ.get('PATH','')}"
            return str(c)
    return None


class Fixture:
    """Temp tree + stub executables + path-rewritten copy of a script."""

    def __init__(self, script: Path):
        self.tmp = Path(tempfile.mkdtemp(prefix="debloat_test_"))
        self.root = self.tmp / "tv"
        self.stubs = self.tmp / "stubs"
        self.log = self.tmp / "calls.log"
        self.stubs.mkdir(parents=True, exist_ok=True)
        for d in ["opt/usr/home/owner/share", "opt/usr/data",
                  "opt/usr/share/systemd/system", "run/systemd/system",
                  "usr/bin", "usr/lib/systemd/system",
                  "prd/usr/bin", "prd/usr/lib/systemd/system",
                  "lib/systemd/system", "etc/systemd/system", "tmp"]:
            (self.root / d).mkdir(parents=True, exist_ok=True)
        self.state = self.tmp / "mounts.state"
        self.state.write_text("", encoding="utf-8")
        self.flags = self.tmp / "flags.state"
        self.flags.write_text("", encoding="utf-8")
        for name, body in {
            # pkgcmd: -D marks the app disabled, -A clears it (matches the
            # parser-DB semantics the real --global switch has); every call
            # is logged.  Exit 0 always (apply.sh gates on the sqlite
            # readback, not the exit code).
            "pkgcmd": ('#!/bin/sh\n'
                       'echo "pkgcmd $*" >> "$CALLS"\n'
                       'n=; act=; id=\n'
                       'prev=; while [ $# -gt 0 ]; do\n'
                       '  case "$1" in -D) n=1;; -A) act=1;; -n) shift; id="$1";; esac\n'
                       '  shift\n'
                       'done\n'
                       '[ -n "$id" ] || exit 0\n'
                       'if [ -n "$n" ]; then\n'
                       '  grep -vF "DISABLED $id" "$FLAGS" 2>/dev/null > "$FLAGS.n";\n'
                       '  mv "$FLAGS.n" "$FLAGS" 2>/dev/null\n'
                       '  echo "DISABLED $id" >> "$FLAGS"\n'
                       'elif [ -n "$act" ]; then\n'
                       '  grep -vF "DISABLED $id" "$FLAGS" 2>/dev/null > "$FLAGS.n";\n'
                       '  mv "$FLAGS.n" "$FLAGS" 2>/dev/null\n'
                       'fi\n'
                       'echo ok\n'),
            # sqlite3: answers apply.sh's app_disable readback from the
            # flags state; anything else answers empty.
            "sqlite3": ('#!/bin/sh\n'
                        'echo "sqlite3 $*" >> "$CALLS"\n'
                        'id=\n'
                        'for a; do\n'
                        '  case "$a" in *app_disable*app_id=*)\n'
                        '    id=$(printf "%s" "$a" | sed "s/.*app_id=\\x27//;s/\\x27.*//")\n'
                        '  ;; esac\n'
                        'done\n'
                        '[ -n "$id" ] || exit 0\n'
                        'if [ -f "$FLAGS" ] && grep -qF "DISABLED $id" "$FLAGS"; then\n'
                        '  echo true\n'
                        'else\n'
                        '  echo false\n'
                        'fi\n'),
            "systemctl": ('#!/bin/sh\n'
                          'echo "systemctl $*" >> "$CALLS"\n'
                          '# simulate real systemd: the mask only bites after a\n'
                          '# daemon-reload - model that with a reload marker\n'
                          'if [ "$1" = "daemon-reload" ]; then touch "$T/run/.reloaded"; fi\n'
                          'if [ "$1" = "start" ]; then\n'
                          '  shift\n'
                          '  for u in "$@"; do\n'
                          '    if [ -e "$T/run/systemd/system/$u" ] &&'
                          ' [ -f "$T/run/.reloaded" ]; then\n'
                          '      echo "Failed to start $u: Unit $u is masked." >&2\n'
                          '      exit 1\n'
                          '    fi\n'
                          '  done\n'
                          'fi\n'
                          'exit 0\n'),
            "mount": ('#!/bin/sh\n'
                      'case "$1" in\n'
                      '  --bind) echo "mount --bind $2 $3" >> "$CALLS"\n'
                      '          echo "$3" >> "$MOUNTS"\n'
                      '          exit 0;;\n'
                      'esac\n'
                      'sed "s|^|true on |;s|$| type none|" "$MOUNTS" 2>/dev/null\n'),
            "umount": '#!/bin/sh\necho "umount $*" >> "$CALLS"\nsed "\\|$1|d" "$MOUNTS" 2>/dev/null > "$MOUNTS.n"; mv "$MOUNTS.n" "$MOUNTS"\nexit 0\n',
            "id": '#!/bin/sh\necho 0\n',
            "stat": '#!/bin/sh\necho 5001\n',
            # dbus-send: simulate avocd - SetNewHome int32:0 clears new_home;
            # CheckAutoMotionPlus reports int32 1 after it, int32 0 before.
            "dbus-send": ('#!/bin/sh\n'
                          'echo "dbus-send $*" >> "$CALLS"\n'
                          'case "$*" in\n'
                          '  *SetNewHome*) echo "new_home=0" > "$FLAGS.newhome"\n'
                          '                echo "   int32 0"\n'
                          '                exit 0;;\n'
                          '  *CheckAutoMotionPlus*)\n'
                          '    if [ -f "$FLAGS.newhome" ]; then echo "   int32 1";\n'
                          '    else echo "   int32 0"; fi\n'
                          '    exit 0;;\n'
                          'esac\n'
                          'exit 1\n'),
        }.items():
            s = self.stubs / name
            s.write_text(body.replace("$CALLS", str(self.log))
                             .replace("$MOUNTS", str(self.state))
                             .replace("$FLAGS", str(self.flags)),
                         encoding="utf-8", newline="\n")
            s.chmod(0o755)
        # rewrite the script's absolute TV paths into the temp tree.  One
        # single-pass regex, longest key first: sequential str.replace would
        # turn "$T/prd/usr/bin" into "$T/prd$T/usr/bin" on the /usr/bin pass.
        text = script.read_text(encoding="utf-8")
        text = TV_PATH.sub(lambda m: TV_MAP[m.group(0)], text)
        (self.tmp / "script.sh").write_text(text, encoding="utf-8", newline="\n")

    def add_units(self, names):
        """Materialise unit files so mask.sh's existence check can find them."""
        for u in names:
            (self.root / "usr/lib/systemd/system" / u).write_text(
                "", encoding="utf-8", newline="\n")

    def write_list(self, name: str, ids):
        p = self.root / name
        p.write_text("\n".join(ids) + "\n", encoding="utf-8", newline="\n")
        return "$T/" + name

    def run(self, script_args, env_extra=None):
        env = dict(os.environ,
                   PATH=f"{self.stubs}{os.pathsep}{os.environ.get('PATH','')}",
                   T=str(self.root).replace("\\", "/"),
                   CALLS=str(self.log),
                   MOUNTS=str(self.state),
                   FLAGS=str(self.flags))
        if env_extra:
            env.update(env_extra)
        args = [a.replace("$T", str(self.root).replace("\\", "/"))
                for a in script_args]
        r = subprocess.run(["sh", str(self.tmp / "script.sh"), *args],
                           capture_output=True, text=True, timeout=120,
                           env=env)
        return r

    def calls(self, needle: str):
        try:
            return [l for l in self.log.read_text(encoding="utf-8").splitlines()
                    if needle in l]
        except OSError:
            return []

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def main() -> int:
    if find_sh() is None:
        print("SKIP: no sh on PATH (install Git Bash or put sh.exe on PATH)")
        return 77
    ok = True

    def check(name, cond, note=""):
        nonlocal ok
        print(("PASS" if cond else "FAIL"), name, ("- " + note if note else ""))
        ok = ok and cond

    tmpf = Fixture(DEB / "tools" / "apply.sh")

    # 1. dry run: zero pkgcmd calls
    lst = tmpf.write_list("t1.txt", TIER1)
    r = tmpf.run([lst], {"APPLY": "0"})
    check("apply dry: exit 0", r.returncode == 0)
    check("apply dry: no pkgcmd call", len(tmpf.calls("pkgcmd")) == 0,
          f"{len(tmpf.calls('pkgcmd'))} calls")
    check("apply dry: 11 DRY lines",
          len([l for l in r.stdout.splitlines() if l.startswith("DRY[")]) == 11)

    # 2. real run: 11 disables in order, undo log complete + before first disable
    r = tmpf.run([lst], {"APPLY": "1"})
    check("apply real: exit 0", r.returncode == 0)
    pkg = tmpf.calls("pkgcmd -D")
    check("apply real: 11 pkgcmd -D calls", len(pkg) == 11)
    dis = len([l for l in r.stdout.splitlines() if l.startswith("disabled[")])
    check("apply real: 11 disabled (sqlite readback true)", dis == 11)
    order = [l.split("-n ")[1].split(" ")[0] for l in pkg]
    check("apply real: list order preserved", order == TIER1, str(order[:3]))
    undo_path = next((l.split(": ", 1)[1].strip() for l in
                      r.stdout.splitlines() if l.startswith("undo log: ")), None)
    check("apply real: undo log path printed", undo_path is not None)
    undo_lines = Path(undo_path).read_text(encoding="utf-8").splitlines() \
        if undo_path else []
    check("apply real: undo log has pkgcmd -A for every package",
          len([l for l in undo_lines if l.startswith("pkgcmd -A")]) == 11)
    check("apply real: undo log is under opt/usr/data (not share/)",
          undo_path is not None
          and "opt/usr/data" in undo_path.replace("\\", "/")
          and "/share/" not in Path(undo_path).as_posix())
    check("apply real: undo replay is cat | sh (UEP)",
          "replay: cat " in r.stdout and "| sh" in r.stdout)
    check("apply real: canalysis/pisa sentinels planted",
          (tmpf.root / "opt/usr/share/systemd/system/canalysis-daemon").exists()
          and (tmpf.root / "opt/usr/share/systemd/system/pisa-service").exists())
    check("apply real: planting a sentinel stops its units",
          any("canalysis-service.service" in l for l in tmpf.calls("systemctl stop"))
          and any("pisa-service.service" in l for l in tmpf.calls("systemctl stop"))
          and any("adagent-service.service" in l for l in tmpf.calls("systemctl stop")))
    check("apply real: sentinels recorded in undo log",
          any("canalysis-daemon" in l and l.startswith("rm ") for l in undo_lines)
          and any("pisa-service" in l and l.startswith("rm ") for l in undo_lines))
    check("apply real: all disables are -D --global",
          all(" -D " in l and " --global" in l for l in pkg))
    check("apply real: picture-guard ran (SetNewHome + verified available)",
          "picture-guard: new_home=0" in r.stdout
          and "(CheckAutoMotionPlus=1" in r.stdout)
    check("apply real: SetNewHome recorded",
          len(tmpf.calls("SetNewHome")) == 1)
    check("apply real: sqlite used busy timeout",
          any(".timeout" in l for l in tmpf.calls("sqlite3")))

    # 3. denylist refused
    tmpf2 = Fixture(DEB / "tools" / "apply.sh")
    bad = tmpf2.write_list("deny.txt", DENY + TIER1[:1])
    r = tmpf2.run([bad], {"APPLY": "1"})
    check("apply: denylist refused (9 entries)",
          r.stdout.count("REFUSE (denylist)") == len(DENY))
    check("apply: denylist entry fails the run",
          r.returncode != 0)
    check("apply: denylist never reaches pkgcmd -D",
          len(tmpf2.calls("pkgcmd -D")) == 1)  # only the tier1 sample ran

    # the dry run is a GATE: a list that would be refused must fail it
    tmpf2b = Fixture(DEB / "tools" / "apply.sh")
    badb = tmpf2b.write_list("deny.txt", DENY[:1] + TIER1[:1])
    r = tmpf2b.run([badb], {"APPLY": "0"})
    check("apply dry: a denylisted entry fails the dry run", r.returncode != 0)
    check("apply dry gated: no pkgcmd call", len(tmpf2b.calls("pkgcmd")) == 0)

    # 4. injection refused
    tmpf3 = Fixture(DEB / "tools" / "apply.sh")
    inj = tmpf3.write_list("inj.txt", ["a;reboot", "b &c", "d|e", "f`g`h",
                                       "i$x", "two words"])
    r = tmpf3.run([inj], {"APPLY": "1"})
    check("apply: injection attempts refused (6)",
          r.stdout.count("REFUSE") == 6)
    check("apply: injection never reaches pkgcmd",
          len(tmpf3.calls("pkgcmd -D")) == 0)
    # whitespace-only line skipped
    tmpf4 = Fixture(DEB / "tools" / "apply.sh")
    ws = tmpf4.write_list("ws.txt", ["   ", "", TIER1[0]])
    r = tmpf4.run([ws], {"APPLY": "0"})
    check("apply: whitespace-only line skipped",
          len([l for l in r.stdout.splitlines() if l.startswith("DRY")]) == 1)

    # 4b. list-argument contract (review 2026-10-30): the list must be a file
    # argument.  The old `${LIST:--}` default expanded to a literal file named
    # "-", so a no-arg run printed "0 of 0" and exited 0 - and the documented
    # `cat list | sh restore.sh` form silently activated nothing.
    for name in ("apply.sh", "restore.sh", "mask.sh", "unmask.sh"):
        f = Fixture(DEB / "tools" / name)
        r = f.run([])
        check(f"{name}: no list argument exits 2", r.returncode == 2,
              str(r.returncode))
        check(f"{name}: no list argument runs no TV command",
              len(f.calls("pkgcmd")) == 0 and len(f.calls("systemctl")) == 0)
        check(f"{name}: no list argument prints a usage line",
              "usage:" in r.stdout)
        f.cleanup()
    fpipe = Fixture(DEB / "tools" / "restore.sh")
    r = subprocess.run(["sh", str(fpipe.tmp / "script.sh")],
                       input="adplatform.ADPlayer\n", capture_output=True,
                       text=True, timeout=60,
                       env=dict(os.environ, T=str(fpipe.root).replace("\\", "/"),
                                CALLS=str(fpipe.log), MOUNTS=str(fpipe.state),
                                FLAGS=str(fpipe.flags)))
    check("restore: a piped list with no argument is refused, not a silent 0 of 0",
          r.returncode == 2 and "usage: restore.sh" in r.stdout, str(r.returncode))
    check("restore: a refused piped list activates nothing",
          len(fpipe.calls("pkgcmd -A")) == 0)
    fpipe.cleanup()

    # the documented TV form: the SCRIPT on stdin, the list as $1.  Nothing
    # else covers this, and it is how every live run invoked the tools:
    #   cat apply.sh | sh -s /tmp/list.txt
    fstdin = Fixture(DEB / "tools" / "apply.sh")
    fstdin.write_list("t1.txt", TIER1[:2])
    env = dict(os.environ, T=str(fstdin.root).replace("\\", "/"),
               CALLS=str(fstdin.log), FLAGS=str(fstdin.flags), APPLY="0",
               PATH=f"{fstdin.stubs}{os.pathsep}{os.environ.get('PATH','')}")
    r = subprocess.run(["sh", "-s", (fstdin.root / "t1.txt").as_posix()],
                       input=(fstdin.tmp / "script.sh").read_text(encoding="utf-8"),
                       capture_output=True, text=True, timeout=60, env=env)
    check("apply: `cat script | sh -s <list>` (the TV form) reads the list arg",
          r.returncode == 0 and r.stdout.count("DRY[") == 2, r.stdout[-200:])
    fstdin.cleanup()
    fstdin2 = Fixture(DEB / "tools" / "mask.sh")
    munits = ["data-service.service", "nagsam-daemon.service"]
    fstdin2.add_units(munits)
    fstdin2.write_list("units.txt", munits)
    fstdin2.write_list("bind.txt", ["nagsam-daemon"])
    env2 = dict(os.environ, T=str(fstdin2.root).replace("\\", "/"),
                CALLS=str(fstdin2.log), MASK="0",
                PATH=f"{fstdin2.stubs}{os.pathsep}{os.environ.get('PATH','')}")
    r = subprocess.run(
        ["sh", "-s", (fstdin2.root / "units.txt").as_posix(),
         (fstdin2.root / "bind.txt").as_posix()],
        input=(fstdin2.tmp / "script.sh").read_text(encoding="utf-8"),
        capture_output=True, text=True, timeout=60, env=env2)
    check("mask: `cat script | sh -s <units> <binaries>` reads both args",
          r.returncode == 0 and r.stdout.count("DRY ln -sf") == len(munits),
          r.stdout[-200:])
    fstdin2.cleanup()

    # 5. sqlite-false after pkgcmd: counted, undo still recorded, exit 1
    # (apply.sh oracles the flag, not pkgcmd's exit code). Must use THIS
    # fixture's list — a leftover $T path from another tree is "list not
    # found" (exit 2) and a 0==0 calls comparison would false-pass.
    tmpf5 = Fixture(DEB / "tools" / "apply.sh")
    lst5 = tmpf5.write_list("t1.txt", TIER1)
    stub = tmpf5.stubs / "pkgcmd"
    stub.write_text('#!/bin/sh\necho "pkgcmd $*" >> "$CALLS"\nexit 1\n',
                    encoding="utf-8", newline="\n")
    stub.chmod(0o755)
    r = tmpf5.run([lst5], {"APPLY": "1"})
    check("apply: pkgcmd failure fails the script", r.returncode != 0)
    check("apply: failure stops at the first package (discipline #2)",
          len(tmpf5.calls("pkgcmd -D")) == 1, str(len(tmpf5.calls("pkgcmd -D"))))
    undo_path5 = next((l.split(": ", 1)[1].strip() for l in
                       r.stdout.splitlines() if l.startswith("undo log: ")), None)
    undo5 = Path(undo_path5).read_text(encoding="utf-8").splitlines() \
        if undo_path5 and Path(undo_path5).is_file() else []
    check("apply: failure still recorded undo lines",
          any(l.startswith("echo undo: ") for l in undo5)
          and any("pkgcmd -A" in l for l in undo5))
    check("apply: failure still runs picture-guard",
          "picture-guard:" in r.stdout)

    # 5b. a sentinel that cannot be planted must abort loudly (it is the
    # durable half of the canalysis/pisa suppression - a silent success here
    # means the units restart at the next boot)
    tmpf5b = Fixture(DEB / "tools" / "apply.sh")
    sd = tmpf5b.root / "opt/usr/share/systemd/system"
    shutil.rmtree(sd)
    sd.write_text("", encoding="utf-8")       # a file where the dir belongs
    lst5b = tmpf5b.write_list("t1.txt", ["com.samsung.tv.canalysis-service"])
    r = tmpf5b.run([lst5b], {"APPLY": "1"})
    check("apply: an unplantable sentinel fails the run",
          r.returncode != 0 and "FAILED: sentinel" in r.stdout,
          r.stdout[-160:])
    check("apply: sentinel failure still runs picture-guard",
          "picture-guard:" in r.stdout)

    # 6. restore.sh re-activates with --global
    tmpf6 = Fixture(DEB / "tools" / "restore.sh")
    lst6 = tmpf6.write_list("t1.txt", TIER1[:3])
    r = tmpf6.run([lst6])
    check("restore: exit 0", r.returncode == 0)
    act = tmpf6.calls("pkgcmd -A")
    check("restore: 3 pkgcmd -A --global calls",
          len(act) == 3 and all("--global" in l for l in act), str(act[:1]))
    tmpf6b = Fixture(DEB / "tools" / "restore.sh")
    ws6 = tmpf6b.write_list("ws.txt", ["   ", "", TIER1[0]])
    r = tmpf6b.run([ws6])
    check("restore: whitespace-only line skipped",
          len(tmpf6b.calls("pkgcmd -A")) == 1)
    tmpf6c = Fixture(DEB / "tools" / "restore.sh")
    lst6c = tmpf6c.write_list("t1.txt", TIER1[:3])
    tmpf6c.flags.write_text(
        "DISABLED " + TIER1[0] + "\nDISABLED " + TIER1[1] + "\n",
        encoding="utf-8")
    stub6 = tmpf6c.stubs / "pkgcmd"
    stub6.write_text('#!/bin/sh\necho "pkgcmd $*" >> "$CALLS"\nexit 1\n',
                     encoding="utf-8", newline="\n")
    stub6.chmod(0o755)
    r = tmpf6c.run([lst6c])
    check("restore: sqlite-false stops at first package",
          r.returncode != 0 and len(tmpf6c.calls("pkgcmd -A")) == 1,
          str(len(tmpf6c.calls("pkgcmd -A"))))
    # restore removes the vendor sentinel when its package is re-enabled
    # (apply.sh plants it; leaving it behind keeps the service down forever)
    tmpf6d = Fixture(DEB / "tools" / "restore.sh")
    sdir = tmpf6d.root / "opt/usr/share/systemd/system"
    (sdir / "canalysis-daemon").write_text("", encoding="utf-8")
    (sdir / "pisa-service").write_text("", encoding="utf-8")
    lst6d = tmpf6d.write_list("t1.txt", ["com.samsung.tv.canalysis-service",
                                        "com.samsung.tv.pisa-service"])
    r = tmpf6d.run([lst6d])
    check("restore: sentinel packages exit 0", r.returncode == 0, r.stdout[-200:])
    check("restore: canalysis/pisa sentinels removed",
          not (sdir / "canalysis-daemon").exists()
          and not (sdir / "pisa-service").exists())

    # 7. mask.sh / unmask.sh
    units = ["data-service.service", "nagsam-daemon.service", "pushd.socket"]
    tmpf7 = Fixture(DEB / "tools" / "mask.sh")
    tmpf7.add_units(units)          # mask.sh refuses names with no unit file
    ul = tmpf7.write_list("units.txt", units)
    r = tmpf7.run([ul], {"MASK": "1"})
    check("mask: exit 0", r.returncode == 0)
    for u in units:
        # Git Bash on Windows creates a file (copy of /dev/null) instead of
        # a symlink; the TV's busybox creates the real symlink.  Existence
        # is the portable assertion.
        check(f"mask: mask file created {u}",
              (tmpf7.root / "run/systemd/system" / u).exists())
    check("mask: stop called per unit",
          len(tmpf7.calls("systemctl stop")) >= len(units))
    check("mask: start-refusal test ran per unit",
          len(tmpf7.calls("systemctl start")) >= len(units))
    check("mask: daemon-reload called",
          len(tmpf7.calls("systemctl daemon-reload")) >= 1)
    check("mask: picture-guard ran (SetNewHome + verified available)",
          "picture-guard: new_home=0" in r.stdout
          and "(CheckAutoMotionPlus=1" in r.stdout)
    sysctl_log = tmpf7.calls("systemctl ")
    reload_at = next((i for i, l in enumerate(sysctl_log)
                      if "daemon-reload" in l), None)
    stop_at = next((i for i, l in enumerate(sysctl_log) if " stop " in l), None)
    start_at = next((i for i, l in enumerate(sysctl_log) if " start " in l), None)
    check("mask: daemon-reload before first stop",
          reload_at is not None and stop_at is not None and reload_at < stop_at,
          f"reload={reload_at} stop={stop_at}")
    check("mask: daemon-reload before first start",
          reload_at is not None and start_at is not None and reload_at < start_at,
          f"reload={reload_at} start={start_at}")
    check("mask: kill-pass skipped without bind list",
          "kill-pass: skipped" in r.stdout)
    # idempotency: a second run in the same session reports already-masked
    # and makes no new symlinks, but MUST still stop every listed unit
    # (idempotency does not mean "skip the stop pass" - review finding)
    before = len(tmpf7.calls("systemctl stop"))
    r = tmpf7.run([ul], {"MASK": "1"})
    check("mask: second run is idempotent (already counted)",
          r.stdout.count("already-masked") == len(units))
    check("mask: second run STILL stops every unit",
          len(tmpf7.calls("systemctl stop")) - before >= len(units))
    tmpf8 = Fixture(DEB / "tools" / "unmask.sh")
    ul8 = tmpf8.write_list("units.txt", units)
    r = tmpf8.run([ul8])
    check("unmask: exit 0", r.returncode == 0)
    left = [u for u in units
            if (tmpf8.root / "run/systemd/system" / u).exists()]
    check("unmask: all symlinks removed", not left, str(left))

    tmpf9 = Fixture(DEB / "tools" / "mask.sh")
    tmpf9.add_units(units)
    ul9 = tmpf9.write_list("units.txt", units)
    stub9 = tmpf9.stubs / "systemctl"
    stub9.write_text(
        '#!/bin/sh\n'
        'echo "systemctl $*" >> "$CALLS"\n'
        'if [ "$1" = "daemon-reload" ]; then echo FAIL; exit 1; fi\n'
        'if [ "$1" = "start" ]; then echo "started $2"; exit 0; fi\n'
        'exit 0\n',
        encoding="utf-8", newline="\n")
    stub9.chmod(0o755)
    r = tmpf9.run([ul9], {"MASK": "1"})
    check("mask: reload failure fails the script", r.returncode != 0)
    check("mask: reload failure does not start units",
          len(tmpf9.calls("systemctl start")) == 0,
          str(tmpf9.calls("systemctl start")[:2]))
    check("mask: reload failure still stops units",
          len(tmpf9.calls("systemctl stop")) >= len(units))

    tmpf10 = Fixture(DEB / "tools" / "mask.sh")
    tmpf10.add_units(units)
    ul10 = tmpf10.write_list("units.txt", units)
    bl10 = tmpf10.write_list("bind.txt", ["nagsam-daemon", "data-service"])
    r = tmpf10.run([ul10, bl10], {"MASK": "1"})
    check("mask: kill-pass runs when bind list given",
          "kill-pass: killed=" in r.stdout, r.stdout[-300:])
    check("mask: binaries this unit does not ship are counted, not killed",
          "absent-binaries=2" in r.stdout, r.stdout[-200:])

    # 8b. kill pass, POSIX only: a real process whose /proc exe entry points
    # at the listed /usr/bin binary must die; an unlisted one must survive.
    # Git Bash cannot resolve native symlinks (readlink returns nothing, so
    # -L is false), hence the platform guard - the TV and any Linux host run
    # this.  The fake tree is why mask.sh grew PROCDIR.
    if os.name != "nt":
        tk = Fixture(DEB / "tools" / "mask.sh")
        tk.add_units(units)
        ulk = tk.write_list("units.txt", units)
        blk = tk.write_list("bind.txt", ["nagsam-daemon"])
        (tk.root / "usr/bin/nagsam-daemon").write_text("", encoding="utf-8")
        fake = tk.root / "proc"
        victim = subprocess.Popen(["/bin/sleep", "60"])
        bystander = subprocess.Popen(["/bin/sleep", "60"])
        try:
            for pid, target in ((victim.pid,
                                 (tk.root / "usr/bin/nagsam-daemon").as_posix()),
                                (bystander.pid, "/bin/sleep")):
                (fake / str(pid)).mkdir(parents=True)
                os.symlink(target, (fake / str(pid) / "exe"))
            r = tk.run([ulk, blk],
                       {"MASK": "1", "PROCDIR": str(fake).replace("\\", "/")})
            check("mask: the listed /usr/bin binary's process is killed",
                  f"killed: nagsam-daemon pid={victim.pid}" in r.stdout,
                  r.stdout[-300:])
            check("mask: the killed pid is gone", victim.poll() is not None)
            check("mask: an unlisted process survives", bystander.poll() is None)
        finally:
            for p in (victim, bystander):
                if p.poll() is None:
                    p.kill()
        tk.cleanup()
    else:
        print("SKIP kill-pass live kill: needs POSIX /proc + working readlink")

    # 8c. a non-bare name in the bind list is refused and fails the run
    tmpf10b = Fixture(DEB / "tools" / "mask.sh")
    tmpf10b.add_units(units)
    ul10b = tmpf10b.write_list("units.txt", units)
    bl10b = tmpf10b.write_list("bind.txt", ["bad name; rm -rf /"])
    r = tmpf10b.run([ul10b, bl10b], {"MASK": "1"})
    check("mask: a non-bare bind-list name is refused",
          "REFUSE (not a bare binary)" in r.stdout)
    check("mask: a refused bind name fails the run", r.returncode != 0)
    check("mask: kill-refused is reported separately from symlink failures",
          "kill-refused=1" in r.stdout, r.stdout[-200:])

    # 8d. a listed name with no unit file is MISSING, gets no mask and fails
    # the run (v42 replays this list at every boot - a typo must be loud)
    tmpf10c = Fixture(DEB / "tools" / "mask.sh")
    tmpf10c.add_units(units[:1])
    ul10c = tmpf10c.write_list("units.txt", units[:1] + ["typoed-unit.service"])
    r = tmpf10c.run([ul10c], {"MASK": "1"})
    check("mask: a unit with no unit file is MISSING",
          "MISSING: typoed-unit.service" in r.stdout)
    check("mask: a missing unit fails the run", r.returncode != 0)
    check("mask: a missing unit gets no /run symlink",
          not (tmpf10c.root / "run/systemd/system" / "typoed-unit.service").exists())
    check("mask: missing-units is counted", "missing-units=1" in r.stdout)

    # 8e. all names missing -> exit 2, never a "0 masked" success
    tmpf10d = Fixture(DEB / "tools" / "mask.sh")
    ul10d = tmpf10d.write_list("units.txt", ["ghost.service"])
    r = tmpf10d.run([ul10d], {"MASK": "1"})
    check("mask: an all-missing list exits 2", r.returncode == 2,
          str(r.returncode))

    # 8f. when a mask cannot be created the refusal test must NOT start the
    # unit: a start against an unmasked unit is a real start
    tmpf10e = Fixture(DEB / "tools" / "mask.sh")
    tmpf10e.add_units(units)
    ul10e = tmpf10e.write_list("units.txt", units)
    rundir = tmpf10e.root / "run/systemd/system"
    shutil.rmtree(rundir)
    rundir.write_text("", encoding="utf-8")      # a file where the dir belongs
    r = tmpf10e.run([ul10e], {"MASK": "1"})
    check("mask: unmakeable masks fail the run",
          r.returncode != 0 and "symlink-fail=3" in r.stdout, r.stdout[-240:])
    check("mask: no mask of ours -> no unit is started",
          len(tmpf10e.calls("systemctl start")) == 0,
          str(tmpf10e.calls("systemctl start")[:2]))
    check("mask: the skipped refusal test is reported per unit",
          r.stdout.count("SKIP refusal-test") == len(units))

    # 9. committed list hygiene
    for lst in sorted((DEB / "lists").glob("*.txt")):
        for i, line in enumerate(lst.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            check(f"list {lst.name}:{i} bare id",
                  re.fullmatch(r"[A-Za-z0-9@._-]+", s) is not None, s)
    deny_hits = []
    for lst in (DEB / "lists").glob("*.txt"):
        for d in DENY:
            for i, line in enumerate(lst.read_text(encoding="utf-8").splitlines(), 1):
                s = line.strip()
                if s == d:
                    deny_hits.append(f"{lst.name}:{i}={d}")
    check("no denylist entry in any committed list", not deny_hits, str(deny_hits))
    units_list = [l.strip() for l in
                  (DEB / "lists" / "services-units.txt")
                  .read_text(encoding="utf-8").splitlines()
                  if l.strip() and not l.strip().startswith("#")]
    # 23 verified live in round 4 (2026-10-29) + cis-api.  bluetooth-monitor
    # is a COMMENTED candidate: added after the verified run, never masked
    # live, and the brief says never disable Bluetooth (review 2026-10-30).
    check("services-units.txt is 23 active entries incl. cis-api",
          len(units_list) == 23
          and "com.samsung.tv.cis-api-service-app.service" in units_list,
          str(len(units_list)))
    check("bluetooth-monitor is a commented candidate, not an active mask",
          "bluetooth-monitor.service" not in units_list
          and "# bluetooth-monitor.service" in
          (DEB / "lists" / "services-units.txt").read_text(encoding="utf-8"))

    # 10. merge determinism: regenerating the inventory from the committed
    # registry dump must reproduce it EXCEPT the two documented manual
    # overrides (iacr, screen-analysis-dbmgr) - anything else is catalog
    # drift (the exact bug class the Vetro PR #44 reclassification exposed).
    node = shutil.which("node")
    if node:
        regen = Path(tempfile.mkdtemp(prefix="debloat_regen_")) / "regen.json"
        r = subprocess.run(["node", str(DEB / "tools" / "merge.js"),
                            str(DEB / "models" / "qnx1d" / "registry-dump.txt"),
                            str(regen)], capture_output=True, text=True,
                           timeout=120)
        check("merge.js regen exits 0", r.returncode == 0, r.stderr[:200])
        import json
        committed = json.loads((DEB / "models" / "qnx1d" / "qnx1d-inventory.json")
                               .read_text(encoding="utf-8"))
        regened = json.loads(regen.read_text(encoding="utf-8"))
        # zip() alone would silently truncate if one side lost a package, so
        # compare the counts and the summary as well (review 2026-10-30)
        check("merge regen: same package count",
              len(committed["packages"]) == len(regened["packages"])
              == committed["summary"]["total"],
              f'{len(committed["packages"])} vs {len(regened["packages"])}')
        known = {"com.samsung.tv.iacr", "com.samsung.tv.screen-analysis-dbmgr"}
        flips = [(a["package"], a["role"], b["role"])
                 for a, b in zip(committed["packages"], regened["packages"])
                 if a["role"] != b["role"]]
        check("merge regen: only the 2 documented overrides flip",
              len(flips) == 2 and all(f[0] in known for f in flips), str(flips))
        # the summary is derived from the roles, so it may differ only by the
        # documented overrides - undo them and the two summaries must match
        expected = dict(regened["summary"])
        for _pkg, c_role, r_role in flips:
            expected[r_role] = expected.get(r_role, 0) - 1
            expected[c_role] = expected.get(c_role, 0) + 1
        check("merge regen: summary == committed once the overrides are applied",
              expected == committed["summary"],
              f'{expected} vs {committed["summary"]}')
        other = [(a["package"], k)
                 for a, b in zip(committed["packages"], regened["packages"])
                 if a["package"] not in known
                 for k in ("area", "purpose", "referencedBy")
                 if a[k] != b[k]]
        check("merge regen: area/purpose/referencedBy are reproducible",
              not other, str(other[:3]))
        # area is derived from the catalog role, so the two overrides carry
        # keep/system - the committed file must hold BOTH edits, not just one
        over = [p["package"] for p in committed["packages"]
                if p["package"] in known and p["role"] == "keep"
                and p["area"] == "system"]
        check("merge regen: the 2 overrides are committed as keep/system",
              len(over) == 2, str(over))
    else:
        print("SKIP merge determinism: node not on PATH")

    tmpf.cleanup(); tmpf2.cleanup(); tmpf2b.cleanup(); tmpf3.cleanup()
    tmpf4.cleanup(); tmpf5.cleanup(); tmpf5b.cleanup()
    tmpf6.cleanup(); tmpf6b.cleanup(); tmpf6c.cleanup(); tmpf6d.cleanup()
    tmpf7.cleanup(); tmpf8.cleanup(); tmpf9.cleanup(); tmpf10.cleanup()
    tmpf10b.cleanup(); tmpf10c.cleanup(); tmpf10d.cleanup(); tmpf10e.cleanup()

    print("\ndebloat tooling tests:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
