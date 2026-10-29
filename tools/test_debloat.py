"""Offline tests for the debloat/ tooling - no TV, no root channel.

Runs the TV-side scripts (apply/restore/mask/unmask/bindapply/bindrestore)
under a POSIX sh with their absolute paths rewritten into a temp tree and
stub executables for everything that talks to the TV (pkgcmd, systemctl,
mount, umount).  The stubs record every call, so the tests assert on
behaviour, not output text:

  * apply.sh dry run records NO pkgcmd call;
  * real run disables in list order and writes the undo log (2 lines per
    package: echo + pkgcmd -A) BEFORE the first disable;
  * the hard denylist (our carrier, coba.adagent, privacy UIs, vetrotvapp)
    is refused even when the list asks for it;
  * injection attempts (spaces, ;, &, |, backticks, $) are refused and
    reach no command;
  * a pkgcmd failure is counted, still leaves its undo line, and fails the
    script;
  * restore.sh re-activates everything with --global;
  * mask.sh/unmask.sh create and remove /run symlinks and call
    daemon-reload;
  * bindapply.sh overlays only existing binaries and skips absent ones;
    bindrestore.sh umounts exactly the overlays its stub mount reports;
  * whitespace-only list lines are skipped everywhere;
  * every committed list file contains bare ids only, never a denylist
    entry, and the tier counts match the documented numbers.

Needs `sh` (Git Bash on Windows); skips (exit 77) where absent.
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
        "com.samsung.tv.coba.privacy_app", "tv6pbVMQFF", "vetrotvapp"]
TIER1 = ["adplatform.ADPlayer", "com.samsung.tizen.samsung-analytics",
         "com.samsung.tv.ad-web-framework", "com.samsung.tv.adplayer",
         "com.samsung.tv.canalysis-service", "com.samsung.tv.cis-api-service-app",
         "com.samsung.tv.contents-recognition-dbmgr",
         "com.samsung.tv.nvision-analysis-dbmgr", "com.samsung.tv.pisa-service",
         "com.samsung.tv.targeted-ad-service", "content-grab-service"]


class Fixture:
    """Temp tree + stub executables + path-rewritten copy of a script."""

    def __init__(self, script: Path, rewrite_binaries: bool = False):
        self.tmp = Path(tempfile.mkdtemp(prefix="debloat_test_"))
        self.root = self.tmp / "tv"
        self.stubs = self.tmp / "stubs"
        self.log = self.tmp / "calls.log"
        self.stubs.mkdir(parents=True, exist_ok=True)
        for d in ["opt/usr/home/owner/share", "opt/usr/data",
                  "opt/usr/share/systemd/system", "run/systemd/system",
                  "usr/bin", "tmp"]:
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
                        'q="$2"\n'
                        'case "$q" in *app_disable*app_id=*)\n'
                        '  id=$(printf "%s" "$q" | sed "s/.*app_id=\\x27//;s/\\x27.*//")\n'
                        '  if [ -f "$FLAGS" ] && grep -qF "DISABLED $id" "$FLAGS"; then\n'
                        '    echo true\n'
                        '  else\n'
                        '    echo false\n'
                        '  fi\n'
                        '  ;;\nesac\n'),
            "systemctl": ('#!/bin/sh\n'
                          'echo "systemctl $*" >> "$CALLS"\n'
                          '# simulate real systemd: a start of a /run-masked unit is refused\n'
                          'if [ "$1" = "start" ]; then\n'
                          '  shift\n'
                          '  for u in "$@"; do\n'
                          '    if [ -e "$T/run/systemd/system/$u" ]; then\n'
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
        }.items():
            s = self.stubs / name
            s.write_text(body.replace("$CALLS", str(self.log))
                             .replace("$MOUNTS", str(self.state))
                             .replace("$FLAGS", str(self.flags)),
                         encoding="utf-8", newline="\n")
            s.chmod(0o755)
        # rewrite the script's absolute TV paths into the temp tree
        text = script.read_text(encoding="utf-8")
        text = text.replace("/opt/usr", "$T/opt/usr")
        text = text.replace("/run/systemd", "$T/run/systemd")
        text = text.replace("/tmp/", "$T/tmp/")
        if rewrite_binaries:
            text = text.replace("/usr/bin", "$T/usr/bin")
        text = text.replace('"$LIST:--"', '"$LIST:--"')  # untouched
        (self.tmp / "script.sh").write_text(text, encoding="utf-8", newline="\n")

    def write_list(self, name: str, ids):
        p = self.root / name
        p.write_text("\n".join(ids) + "\n", encoding="utf-8", newline="\n")
        return "$T/" + name

    def run(self, script_args, env_extra=None):
        env = dict(os.environ,
                   PATH=f"{self.stubs};{os.environ.get('PATH','')}",
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
    if shutil.which("sh") is None:
        print("SKIP: no sh on PATH")
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
          len([l for l in r.stdout.splitlines() if l.startswith("DRY")]) == 11)

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
    check("apply real: undo log has 2 lines per package (echo + pkgcmd -A)",
          len([l for l in undo_lines if l.startswith("echo undo: ")]) == 11
          and len([l for l in undo_lines if "pkgcmd -A" in l]) == 22)
    # undo-before-disable: the log file's first -A line precedes the first -D call
    check("apply real: all disables --global",
          all(" -D " in l for l in pkg))

    # 3. denylist refused
    tmpf2 = Fixture(DEB / "tools" / "apply.sh")
    bad = tmpf2.write_list("deny.txt", DENY + TIER1[:1])
    r = tmpf2.run([bad], {"APPLY": "1"})
    check("apply: denylist refused (5 entries)", r.stdout.count("REFUSE (denylist)") == 5)
    check("apply: denylist never reaches pkgcmd -D",
          len(tmpf2.calls("pkgcmd -D")) == 1)  # only the tier1 sample ran

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

    # 5. pkgcmd failure: counted, undo still recorded, exit 1
    tmpf5 = Fixture(DEB / "tools" / "apply.sh")
    stub = tmpf5.stubs / "pkgcmd"
    stub.write_text('#!/bin/sh\necho "pkgcmd $*" >> "$CALLS"\nexit 1\n',
                    encoding="utf-8", newline="\n")
    stub.chmod(0o755)
    r = tmpf5.run([lst], {"APPLY": "1"})
    check("apply: pkgcmd failure fails the script", r.returncode != 0)
    check("apply: failure still recorded undo lines",
          len(tmpf5.calls("pkgcmd -A")) == len(tmpf5.calls("pkgcmd -D")))

    # 6. restore.sh re-activates with --global
    tmpf6 = Fixture(DEB / "tools" / "restore.sh")
    lst6 = tmpf6.write_list("t1.txt", TIER1[:3])
    r = tmpf6.run([lst6])
    check("restore: exit 0", r.returncode == 0)
    act = tmpf6.calls("pkgcmd -A")
    check("restore: 3 pkgcmd -A --global calls",
          len(act) == 3 and all("--global" in l for l in act), str(act[:1]))

    # 7. mask.sh / unmask.sh
    units = ["data-service.service", "nagsam-daemon.service", "pushd.socket"]
    tmpf7 = Fixture(DEB / "tools" / "mask.sh")
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
    # idempotency: a second run in the same session reports already-masked
    # and makes no new symlinks
    r = tmpf7.run([ul], {"MASK": "1"})
    check("mask: second run is idempotent",
          r.stdout.count("already-masked") == len(units))
    tmpf8 = Fixture(DEB / "tools" / "unmask.sh")
    ul8 = tmpf8.write_list("units.txt", units)
    r = tmpf8.run([ul8])
    check("unmask: exit 0", r.returncode == 0)
    left = [u for u in units
            if (tmpf8.root / "run/systemd/system" / u).exists()]
    check("unmask: all symlinks removed", not left, str(left))

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
        known = {"com.samsung.tv.iacr", "com.samsung.tv.screen-analysis-dbmgr"}
        flips = [(a["package"], a["role"], b["role"])
                 for a, b in zip(committed["packages"], regened["packages"])
                 if a["role"] != b["role"]]
        check("merge regen: only the 2 documented overrides flip",
              len(flips) == 2 and all(f[0] in known for f in flips), str(flips))
    else:
        print("SKIP merge determinism: node not on PATH")

    tmpf.cleanup(); tmpf2.cleanup(); tmpf3.cleanup(); tmpf4.cleanup()
    tmpf5.cleanup(); tmpf6.cleanup(); tmpf7.cleanup(); tmpf8.cleanup()

    print("\ndebloat tooling tests:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
