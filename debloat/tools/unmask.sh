#!/bin/sh
# unmask.sh - remove the /run mask symlinks created by mask.sh (undo).
# Same unit list.  Does not restart units (they come back at the next boot
# or when something starts them).  The /opt sentinel files used by vendor
# unit conditions are NOT touched - restore.sh removes those.
# The picture-settings loop (transient unit `newhome-fix`) is deliberately
# LEFT RUNNING: it is not a mask, and removing it would let the avocd
# grey-out race come back.  Stop it yourself with `systemctl stop
# newhome-fix` if you want it gone (it dies at reboot either way).
#   cat tools/unmask.sh | sh -s lists/services-units.txt
# The list MUST be a file argument - no stdin fallback, because the usual
# invocation pipes the script in and stdin carries the script.
set -u

LIST="${1:-}"
[ -n "$LIST" ] || { echo "usage: unmask.sh <unit-list-file>  (the list must be a file; stdin carries the script when piped)"; exit 2; }
[ -f "$LIST" ] || { echo "list not found: $LIST"; exit 2; }
RUNDIR=/run/systemd/system

ok=0; fail=0; absent=0; n=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  u=$(printf '%s' "$line" | tr -d '\r' | awk '{$1=$1};1')
  [ -n "$u" ] || continue
  case "$u" in *[!A-Za-z0-9@._-]*) echo "REFUSE (not a bare unit): $u"; fail=$((fail+1)); continue ;; esac
  n=$((n+1))
  if [ ! -L "$RUNDIR/$u" ] && [ ! -f "$RUNDIR/$u" ]; then
    echo "not-masked: $u"
    absent=$((absent+1))
    continue
  fi
  if rm -f "$RUNDIR/$u"; then
    echo "unmasked[$n]: $u"
    ok=$((ok+1))
  else
    echo "FAILED[$n]: $u"
    fail=$((fail+1))
  fi
done < "$LIST"

# The symlinks are gone, but systemd keeps the masks loaded until a successful
# reload/reboot - so a failed reload means "unmasked" is NOT in effect.  mask.sh
# already treats the same failure as fatal; this pair used to disagree
# (2026-10-31 review, reproduced under busybox ash).
if ! systemctl daemon-reload 2>&1; then
  echo "FAIL: daemon-reload - the masks may still be loaded in systemd"
  fail=$((fail+1))
fi
echo
echo "summary: unmasked=$ok not-masked=$absent failed=$fail of $n"
if [ "$n" = "0" ]; then
  echo "FAIL: $LIST yielded no valid unit names"
  exit 2
fi
[ "$fail" = "0" ] || exit 1
