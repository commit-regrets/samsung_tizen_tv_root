#!/bin/sh
# mask.sh - suppress systemd units for the CURRENT SESSION, in the order
# that actually works on this firmware:
#   pass 1: symlink /run/systemd/system/<unit> -> /dev/null for every unit
#   (rank 2 of UnitPath; verified mechanism - see
#   models/qnx1d/run-2026-10-29-services-bind.md)
#   one systemctl daemon-reload  (the masks are INERT until this - the
#   reload must happen before any stop/refusal step)
#   pass 2: stop every listed unit, then verify refusal (a masked unit must
#   refuse to start; a successful start = FAIL)
# SESSION-ONLY by design (/run is tmpfs, dies at reboot).  Durable
# suppression = the boot payload re-writing these masks each boot (v42).
# Undo = tools/unmask.sh with the same list.
#
#   MASK=0 sh mask.sh lists/services-units.txt    # dry run
#   sh mask.sh lists/services-units.txt           # mask + reload + stop + refusal
#
# Idempotent: re-running in the same boot session is safe and still stops
# any unit that is up (already-masked units are counted, not skipped from
# the stop pass).  Units without a unit file are skipped.
set -u

LIST="${1:-}"
[ -n "$LIST" ] && [ ! -f "$LIST" ] && { echo "list not found: $LIST"; exit 2; }
MASK="${MASK:-1}"
RUNDIR=/run/systemd/system

mkdir -p "$RUNDIR" 2>/dev/null

# ---- pass 1: create missing mask symlinks --------------------------------
new=0; already=0; skip=0; bad=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  u=$(printf '%s' "$line" | tr -d '\r' | awk '{$1=$1};1')
  [ -n "$u" ] || continue
  case "$u" in *[!A-Za-z0-9@._-]*) echo "REFUSE (not a bare unit): $u"; bad=$((bad+1)); continue ;; esac
  if [ -e "$RUNDIR/$u" ] || [ -L "$RUNDIR/$u" ]; then
    already=$((already+1))
    continue
  fi
  if [ "$MASK" != "1" ]; then
    echo "DRY ln -sf /dev/null $RUNDIR/$u"
    new=$((new+1))
    continue
  fi
  if ln -sf /dev/null "$RUNDIR/$u" 2>/dev/null; then
    new=$((new+1))
    echo "masked: $u"
  else
    echo "FAILED: symlink $u"
    bad=$((bad+1))
  fi
done < "${LIST:--}"

# ---- the masks are inert until the reload --------------------------------
[ "$MASK" = "1" ] && systemctl daemon-reload 2>&1

# ---- pass 2: stop + refusal test for EVERY listed unit (already-masked
# included: a second run in the same boot must still stop a running unit) --
stopped=0; refused=0; fail=0; n=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  u=$(printf '%s' "$line" | tr -d '\r' | awk '{$1=$1};1')
  [ -n "$u" ] || continue
  case "$u" in *[!A-Za-z0-9@._-]*) continue ;; esac
  n=$((n+1))
  if [ "$MASK" != "1" ]; then
    echo "DRY stop + refusal test $u"
    continue
  fi
  if systemctl stop "$u" 2>/dev/null; then
    stopped=$((stopped+1))
  fi
  if systemctl start "$u" >/dev/null 2>&1; then
    echo "FAIL: $u started despite mask"
    fail=$((fail+1))
  else
    refused=$((refused+1))
  fi
done < "${LIST:--}"

# ---- finalize: avocd new_home flag (picture-settings grey-out guard) ----
# Stopping/killing services can race Samsung Home's flag reset and leave
# motion processing forced off (Picture Mode / Brightness greyed out).
# Resetting it is what Home itself does when it hides - safe, memory-only.
# See models/qnx1d/run-2026-10-29-services-bind.md round 5.
# AVOCD=0 skips this (e.g. while diagnosing avocd itself).
if [ "$MASK" = "1" ] && [ "${AVOCD:-1}" = "1" ] && command -v dbus-send >/dev/null 2>&1; then
  if dbus-send --system --print-reply --dest=org.tizen.tv.avoc /org/tizen/tv/avoc \
      org.tizen.tv.avoc.AvOutputControl.SetNewHome int32:0 >/dev/null 2>&1; then
    st=$(dbus-send --system --print-reply --dest=org.tizen.tv.avoc /org/tizen/tv/avoc \
      org.tizen.tv.avoc.AvOutputControl.CheckAutoMotionPlus 2>/dev/null \
      | awk '/int32/{print $NF}')
    echo "picture-guard: new_home=0 (CheckAutoMotionPlus=${st:-?}; 1 = picture settings available)"
    [ "$st" = "1" ] || echo "picture-guard: WARNING - still forced off; rerun SetNewHome or use the 30 s loop (tcc ch. 6)"
  else
    echo "picture-guard: dbus call failed - skipped (run the SetNewHome command manually)"
  fi
fi

echo
if [ "$MASK" = "1" ]; then
  echo "summary: newly-masked=$new already=$already stopped=$stopped refusal-ok=$refused no-unit-or-bad=$((skip+bad)) start-failures=$fail"
  [ "$fail" = "0" ] || exit 1
else
  echo "dry run: would mask $new new units ($already already masked), stop + refusal-test $n"
fi
