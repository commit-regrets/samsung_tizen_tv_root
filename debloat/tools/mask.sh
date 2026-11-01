#!/bin/sh
# mask.sh - suppress systemd units for the CURRENT SESSION, in the order
# that actually works on this firmware:
#   pass 1: symlink /run/systemd/system/<unit> -> /dev/null for every unit
#   (rank 2 of UnitPath; verified mechanism - see
#   models/qnx1d/run-2026-10-29-services-bind.md)
#   one systemctl daemon-reload  (the masks are INERT until this - the
#   reload must happen before any stop/refusal step)
#   pass 2: stop every listed unit, then verify refusal (ONLY if reload
#   succeeded AND the /run symlink is ours - a start against an inert mask
#   is a real start)
#   pass 3: kill leftover processes whose /proc/<pid>/exe is /usr/bin/<name>
#   from the optional bind list (round 4: mask alone left launchpad copies up)
#   pass 4: picture-guard - one SetNewHome + verify, then the persistent
#   30 s `newhome-fix` transient unit (the flag can be re-set mid-session)
#   pass 5: restart-loop check - a listed unit that is still "activating"
#   fails the run (tcc's trap: a unit whose app is disabled restarts forever)
# SESSION-ONLY by design (/run is tmpfs, dies at reboot).  Durable
# suppression = the boot payload re-writing these masks each boot (v42).
# Undo = tools/unmask.sh with the same list; the picture loop is stopped with
# `systemctl stop newhome-fix` (it is a transient unit, gone at reboot).
#
#   MASK=0 sh mask.sh lists/services-units.txt
#   sh mask.sh lists/services-units.txt lists/services-bind.txt
#
# The unit list MUST be a file argument - no stdin fallback, because the
# usual invocation is `cat mask.sh | sh -s <list>` and stdin carries the
# script.  (Review 2026-10-30: the old `${LIST:--}` default was a literal
# "-" file, so a no-arg run masked nothing and exited 0.)
#
# Every listed unit is checked against the real unit directories first: a
# name with no unit file is reported MISSING and fails the run, because v42
# replays this list verbatim at every boot and a typo'd name would be
# reported "masked" while the service keeps running.  A start-refusal is
# only evidence when the unit exists and our mask is in place.
#
# Idempotent: re-running in the same boot session is safe and still stops
# any unit that is up (already-masked units are counted, not skipped from
# the stop pass), and the newhome-fix loop is not started twice.
set -u

LIST="${1:-}"
[ -n "$LIST" ] || { echo "usage: mask.sh <unit-list-file> [binary-list-file]  (lists must be files; stdin carries the script when piped)"; exit 2; }
[ -f "$LIST" ] || { echo "list not found: $LIST"; exit 2; }
BIND_LIST="${2:-${BIND_LIST:-}}"
[ -n "$BIND_LIST" ] && [ ! -f "$BIND_LIST" ] && { echo "bind list not found: $BIND_LIST"; exit 2; }
MASK="${MASK:-1}"
KILL="${KILL:-1}"
RUNDIR=/run/systemd/system
# /proc by default; overridable so the tests can point the kill pass at a
# fake tree (the TV always uses /proc).
PROCDIR="${PROCDIR:-/proc}"
# unit directories to check for a listed name.  /run is deliberately NOT
# searched: our own masks live there, so a stale symlink would make a
# nonexistent unit look real.
UNIT_DIRS="/etc/systemd/system /usr/lib/systemd/system /lib/systemd/system /prd/usr/lib/systemd/system"

# true when this unit has a unit file on this firmware.  -e, not -f: a unit
# the vendor masked at /etc is a symlink to /dev/null and must still count.
unit_exists() {
  for d in $UNIT_DIRS; do [ -e "$d/$1" ] && return 0; done
  return 1
}

# true when <unit> is masked in /run by us (a symlink on the TV; Git Bash
# and some test hosts materialise it as a plain file, so test existence too)
masked_here() {
  [ -L "$RUNDIR/$1" ] || [ -e "$RUNDIR/$1" ]
}

mkdir -p "$RUNDIR" 2>/dev/null

# ---- pass 1: create missing mask symlinks --------------------------------
new=0; already=0; bad=0; missing=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  u=$(printf '%s' "$line" | tr -d '\r' | awk '{$1=$1};1')
  [ -n "$u" ] || continue
  case "$u" in *[!A-Za-z0-9@._-]*) echo "REFUSE (not a bare unit): $u"; bad=$((bad+1)); continue ;; esac
  if ! unit_exists "$u"; then
    echo "MISSING: $u (no unit file in $UNIT_DIRS - fix the list)"
    missing=$((missing+1))
    continue
  fi
  if masked_here "$u"; then
    already=$((already+1))
    echo "already-masked: $u"
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
done < "$LIST"

# ---- the masks are inert until the reload --------------------------------
reload_ok=0
if [ "$MASK" = "1" ]; then
  if systemctl daemon-reload; then
    reload_ok=1
  else
    echo "FAIL: daemon-reload (masks inert - will stop+kill, will NOT start)"
  fi
fi

# ---- pass 2: stop every listed unit; start-refusal ONLY after a good
# reload and ONLY for a unit we actually masked (never start a unit whose
# mask is missing: that would be a real start of a service we must keep down)
stopped=0; refused=0; fail=0; n=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  u=$(printf '%s' "$line" | tr -d '\r' | awk '{$1=$1};1')
  [ -n "$u" ] || continue
  case "$u" in *[!A-Za-z0-9@._-]*) continue ;; esac
  unit_exists "$u" || continue
  n=$((n+1))
  if [ "$MASK" != "1" ]; then
    echo "DRY stop + refusal test $u"
    continue
  fi
  if systemctl stop "$u" 2>/dev/null; then
    # A stop that exits 0 does not prove the unit is down: a Restart= unit can
    # already be re-arming, and counting it stopped hid a running service
    # (2026-11-01 review).  Ask the unit itself; anything other than a clean
    # inactive/failed is a failure of this run.
    if systemctl is-active --quiet "$u" 2>/dev/null; then
      echo "FAIL: $u is still active after a successful stop"
      fail=$((fail+1))
    else
      stopped=$((stopped+1))
    fi
  else
    # A failed stop leaves the unit RUNNING even though the mask is in place.
    # Counting only successes made the run exit 0 while the service was still
    # up (2026-10-31 review, reproduced under busybox ash).
    echo "FAIL: systemctl stop $u"
    fail=$((fail+1))
  fi
  if [ "$reload_ok" != "1" ]; then
    continue
  fi
  if ! masked_here "$u"; then
    echo "SKIP refusal-test: $u (no /run mask of ours - not starting it)"
    continue
  fi
  if systemctl start "$u" >/dev/null 2>&1; then
    echo "FAIL: $u started despite mask"
    fail=$((fail+1))
  else
    refused=$((refused+1))
  fi
done < "$LIST"

# ---- pass 3: kill stragglers by /proc exe (launchpad copies ignore stop) -
killed=0; killbad=0; absent=0
if [ "$MASK" = "1" ] && [ "$KILL" = "1" ] && [ -n "$BIND_LIST" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) continue ;; esac
    name=$(printf '%s' "$line" | tr -d '\r' | awk '{$1=$1};1')
    [ -n "$name" ] || continue
    case "$name" in *[!A-Za-z0-9@._-]*) echo "REFUSE (not a bare binary): $name"; killbad=$((killbad+1)); continue ;; esac
    # A binary this unit does not ship is expected (3 of 24 on QNX1D) - skip
    # it, but count it so the summary does not read like a full pass.
    if [ ! -e "/usr/bin/$name" ] && [ ! -e "/prd/usr/bin/$name" ]; then
      absent=$((absent+1))
      continue
    fi
    for proc in "$PROCDIR"/[0-9]*; do
      pid=${proc##*/}
      [ "$pid" = "1" ] && continue
      exe=$(readlink "$proc/exe" 2>/dev/null) || continue
      exe=$(printf '%s' "$exe" | sed 's/ (deleted)$//')
      case "$exe" in
        /usr/bin/"$name"|/prd/usr/bin/"$name")
          if kill -9 "$pid" 2>/dev/null; then
            killed=$((killed+1))
            echo "killed: $name pid=$pid"
          fi
          ;;
      esac
    done
  done < "$BIND_LIST"
  echo "kill-pass: killed=$killed refused=$killbad absent-binaries=$absent"
else
  echo "kill-pass: skipped"
fi

# ---- finalize: avocd new_home flag (picture-settings grey-out guard) ----
# Stopping/killing services can race Samsung Home's flag reset and leave
# motion processing forced off (Picture Mode / Brightness greyed out).
# Resetting it is what Home itself does when it hides - safe, memory-only.
# See models/qnx1d/run-2026-10-29-services-bind.md round 5.
#
# Two parts, and both are needed:
#   * one immediate SetNewHome + verify (fast feedback, and the whole guard
#     still works where systemd-run is missing);
#   * the persistent `newhome-fix` 30 s loop.  The flag lives in memory only
#     and Samsung code can set it again at any time (tizen-tv-control-center
#     docs/picture-fix-any-launcher.md: "keeps resetting it every 30 s until
#     the next reboot"), so a one-shot at boot is not enough - the grey-out
#     comes back mid-session.
# AVOCD=0 skips the whole guard; NEWHOME_LOOP=0 keeps only the one-shot.
newhome=off
if [ "$MASK" = "1" ] && [ "${AVOCD:-1}" = "1" ] && command -v dbus-send >/dev/null 2>&1; then
  if dbus-send --system --print-reply --dest=org.tizen.tv.avoc /org/tizen/tv/avoc \
      org.tizen.tv.avoc.AvOutputControl.SetNewHome int32:0 >/dev/null 2>&1; then
    st=$(dbus-send --system --print-reply --dest=org.tizen.tv.avoc /org/tizen/tv/avoc \
      org.tizen.tv.avoc.AvOutputControl.CheckAutoMotionPlus 2>/dev/null \
      | awk '/int32/{print $NF}')
    # 1 = picture settings available now.  0 is NOT a failure by itself: while
    # Samsung Home is in front, Home keeps motion processing off, so the
    # readback is 0 regardless of the flag we just cleared.  Only an empty
    # answer means the verify call itself failed.
    echo "picture-guard: new_home=0 (CheckAutoMotionPlus=${st:-?}; 1 = settings available, 0 while Samsung Home is in front)"
    [ -n "$st" ] || echo "picture-guard: WARNING - the verify call returned nothing"
  else
    echo "picture-guard: dbus call failed - skipped (run the SetNewHome command manually)"
  fi
  if [ "${NEWHOME_LOOP:-1}" = "1" ]; then
    if systemctl is-active --quiet newhome-fix.service 2>/dev/null; then
      newhome=active
      echo "picture-guard: newhome-fix loop already active (30 s)"
    elif systemctl start newhome-fix.service 2>/dev/null; then
      newhome=started
      echo "picture-guard: newhome-fix loop re-started (30 s; stop: systemctl stop newhome-fix)"
    elif command -v systemd-run >/dev/null 2>&1 && systemd-run --unit=newhome-fix \
        /usr/bin/awk 'BEGIN { while (1) { system("dbus-send --system --dest=org.tizen.tv.avoc /org/tizen/tv/avoc org.tizen.tv.avoc.AvOutputControl.SetNewHome int32:0"); system("sleep 30") } }' \
        >/dev/null 2>&1; then
      newhome=started
      echo "picture-guard: newhome-fix loop started (30 s; stop: systemctl stop newhome-fix)"
    else
      newhome=failed
      echo "picture-guard: WARNING - newhome-fix loop not started; the flag can restick later"
    fi
  fi
fi

# ---- restart-loop check (tcc's trap) -------------------------------------
# A unit whose app is disabled or whose binary is gone restarts every 2-5 s
# forever ("activating (auto-restart)"): up to 130 restarts in minutes on
# tcc's S90D.  The global count is reported for context (an idle boot already
# has a couple), but the FAILURE signal is a LISTED unit still activating -
# that means the mask did not hold.
loops=0; ourloops=0; loopcheck=skipped
if [ "$MASK" = "1" ] && command -v systemctl >/dev/null 2>&1; then
  units_file=/tmp/.dsh_units.$$
  # --full: without it list-units clips names at the terminal width, and a
  # clipped name can never match a listed unit - the loop check would report a
  # clean 0 while a listed unit was restarting (2026-11-01 review).
  if systemctl list-units --all --no-legend --plain --full > "$units_file" 2>/dev/null; then
    loopcheck=ok
    loops=$(grep -c ' activating ' "$units_file" 2>/dev/null) || loops=0
    grep ' activating ' "$units_file" 2>/dev/null | awk '{print $1}' > "$units_file.active"
    # Count and name from the SAME sanitized reader (CR strip, comment skip) -
    # an awk pass over the raw list used to disagree with the LOOP: lines.
    while IFS= read -r lu || [ -n "$lu" ]; do
      case "$lu" in ''|\#*) continue ;; esac
      lu=$(printf '%s' "$lu" | tr -d '\r' | awk '{$1=$1};1')
      [ -n "$lu" ] || continue
      if grep -qxF "$lu" "$units_file.active" 2>/dev/null; then
        ourloops=$((ourloops+1))
        echo "LOOP: $lu is still activating (the mask did not hold)"
      fi
    done < "$LIST"
  else
    # Fail closed: a dump we could not read is NOT "no loops".  A manual run
    # must not report a clean result it did not measure, and v42 must beacon
    # loop-check=failed rather than listed-activating=0.
    loopcheck=failed
    echo "loop-check: FAILED - systemctl list-units did not answer; cannot prove there is no restart loop"
  fi
  rm -f "$units_file" "$units_file.active"
  if [ "$loopcheck" = "ok" ]; then
    echo "loop-check: activating=$loops listed-activating=$ourloops (an idle boot already has a couple)"
  fi
fi

echo
if [ "$MASK" = "1" ]; then
  echo "summary: newly-masked=$new already=$already stopped=$stopped refusal-ok=$refused missing-units=$missing symlink-fail=$bad kill-refused=$killbad fail=$fail killed=$killed reload_ok=$reload_ok loop-check=$loopcheck activating=$loops listed-activating=$ourloops newhome=$newhome"
else
  echo "dry run: would mask $new new units ($already already masked, $missing missing), stop + refusal-test $n"
fi
# An empty result is a failure, not a success: no listed unit matched a unit
# file (wrong names or the wrong file) must not report exit 0.
if [ "$n" = "0" ]; then
  echo "FAIL: no listed unit matched a unit file (see MISSING above)"
  exit 2
fi
if [ "$MASK" = "1" ]; then
  [ "$fail" = "0" ] && [ "$bad" = "0" ] && [ "$missing" = "0" ] \
    && [ "$killbad" = "0" ] && [ "$reload_ok" = "1" ] \
    && [ "$ourloops" = "0" ] && [ "$loopcheck" != "failed" ] || exit 1
else
  [ "$bad" = "0" ] && [ "$missing" = "0" ] || exit 1
fi
