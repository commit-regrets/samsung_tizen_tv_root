#!/bin/sh
# mask.sh - suppress systemd units for the CURRENT SESSION:
#   1. symlink /run/systemd/system/<unit> -> /dev/null (rank 2 of UnitPath;
#      verified mechanism - see models/qnx1d/run-2026-10-29-services-bind.md)
#   2. systemctl daemon-reload
#   3. stop each unit (masked units keep running until stopped)
#   4. start-refusal test (a masked unit must refuse; anything else = FAIL)
# SESSION-ONLY by design (/run is tmpfs, dies at reboot).  Durable
# suppression = the boot payload re-writing these masks each boot (v42).
# Undo = tools/unmask.sh with the same list.
#
#   MASK=0 sh mask.sh lists/services-units.txt    # dry run
#   sh mask.sh lists/services-units.txt           # mask + stop + refusal test
#
# Idempotent: an already-masked unit is counted and skipped, so re-running
# in the same boot session is safe.  Units without a unit file are skipped.
set -u

LIST="${1:-}"
[ -n "$LIST" ] && [ ! -f "$LIST" ] && { echo "list not found: $LIST"; exit 2; }
MASK="${MASK:-1}"
RUNDIR=/run/systemd/system

mkdir -p "$RUNDIR" 2>/dev/null
masked=0; stopped=0; refused=0; already=0; skip=0; fail=0; n=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  u=$(printf '%s' "$line" | tr -d '\r' | awk '{$1=$1};1')
  [ -n "$u" ] || continue
  case "$u" in *[!A-Za-z0-9@._-]*) echo "REFUSE (not a bare unit): $u"; fail=$((fail+1)); continue ;; esac

  if [ -L "$RUNDIR/$u" ] || [ -f "$RUNDIR/$u" ]; then
    already=$((already+1))
    echo "already-masked[$n]: $u"
    continue
  fi
  systemctl cat "$u" >/dev/null 2>&1 || { echo "skip[$n]: $u has no unit file"; skip=$((skip+1)); continue; }
  n=$((n+1))
  if [ "$MASK" != "1" ]; then
    echo "DRY[$n] ln -sf /dev/null $RUNDIR/$u + stop + refusal test"
    continue
  fi
  if ! ln -sf /dev/null "$RUNDIR/$u" 2>/dev/null; then
    echo "FAILED[$n]: symlink $u"
    fail=$((fail+1))
    continue
  fi
  masked=$((masked+1))
  echo "masked[$n]: $u"
  if systemctl stop "$u" 2>/dev/null; then
    stopped=$((stopped+1))
  fi
  if systemctl start "$u" >/dev/null 2>&1; then
    echo "FAILED[$n]: $u started despite mask (refusal test)"
    fail=$((fail+1))
  else
    refused=$((refused+1))
  fi
done < "${LIST:--}"

[ "$MASK" = "1" ] && systemctl daemon-reload 2>&1

echo
if [ "$MASK" = "1" ]; then
  echo "summary: masked=$masked stopped=$stopped refusal-ok=$refused already=$already no-unit=$skip failed=$fail"
  [ "$fail" = "0" ] || exit 1
else
  echo "dry run: would process $n units ($skip absent)"
fi
