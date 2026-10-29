#!/bin/sh
# unmask.sh - remove the /run mask symlinks created by mask.sh (undo).
# Same list.  (The permanent /opt sentinel files used by vendor unit
# conditions are NOT touched by this tool.)
#   tools/unmask.sh lists/services-units.txt
set -u

LIST="${1:-}"
[ -n "$LIST" ] && [ ! -f "$LIST" ] && { echo "list not found: $LIST"; exit 2; }
RUNDIR=/run/systemd/system

ok=0; fail=0; absent=0; n=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  u=$(printf '%s' "$line" | tr -d '\r' | awk '{$1=$1};1')
  [ -n "$u" ] || continue
  case "$u" in *[!A-Za-z0-9@._-]*) echo "REFUSE (not a bare unit): $u"; fail=$((fail+1)); continue ;; esac
  n=$((n+1))
  if [ ! -L "$RUNDIR/$u" ]; then
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
done < "${LIST:--}"

systemctl daemon-reload 2>&1
echo
echo "summary: unmasked=$ok not-masked=$absent failed=$fail of $n"
[ "$fail" = "0" ] || exit 1
