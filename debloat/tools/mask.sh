#!/bin/sh
# mask.sh - suppress systemd units for the CURRENT SESSION by symlinking
# them to /dev/null in /run/systemd/system (rank 2 of this firmware's
# UnitPath, writable).  Dies at reboot BY DESIGN (/run is tmpfs): persistent
# service suppression needs the boot payload (v42); persistent APP disables
# are pkgcmd -D --global (see apply.sh).  Undo = tools/unmask.sh, same list.
#
#   MASK=0 sh mask.sh lists/services-units.txt    # dry run
#   sh mask.sh lists/services-units.txt           # mask + stop + refusal test
#
# Validation: bare unit names only; units that do not exist are skipped.
# Verified 2026-10-29: is-enabled flips to "masked", systemctl start is
# refused, process stays down.  (Empty files or /dev/null symlinks under
# /opt/usr/share/systemd/system do NOT work - that path is not in UnitPath.)
set -u

LIST="${1:-}"
[ -n "$LIST" ] && [ ! -f "$LIST" ] && { echo "list not found: $LIST"; exit 2; }
MASK="${MASK:-1}"
RUNDIR=/run/systemd/system

mkdir -p "$RUNDIR" 2>/dev/null
ok=0; fail=0; skip=0; n=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  u=$(printf '%s' "$line" | tr -d '\r' | awk '{$1=$1};1')
  [ -n "$u" ] || continue
  case "$u" in *[!A-Za-z0-9@._-]*) echo "REFUSE (not a bare unit): $u"; fail=$((fail+1)); continue ;; esac
  systemctl cat "$u" >/dev/null 2>&1 || { echo "skip[$n]: $u has no unit file"; skip=$((skip+1)); continue; }
  n=$((n+1))
  if [ "$MASK" != "1" ]; then
    echo "DRY[$n] ln -sf /dev/null $RUNDIR/$u"
    continue
  fi
  if ln -sf /dev/null "$RUNDIR/$u" 2>/dev/null; then
    echo "masked[$n]: $u"
    ok=$((ok+1))
  else
    echo "FAILED[$n]: $u"
    fail=$((fail+1))
  fi
done < "${LIST:--}"

[ "$MASK" = "1" ] && systemctl daemon-reload 2>&1

echo
if [ "$MASK" = "1" ]; then
  echo "summary: masked=$ok failed=$fail skipped(no unit)=$skip of $n (session-only: dies at reboot)"
  [ "$fail" = "0" ] || exit 1
else
  echo "dry run: would mask $ok of $n existing units ($skip absent)"
fi
