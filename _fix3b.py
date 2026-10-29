from pathlib import Path

ROOT = Path("C:/Users/Raghav/Documents/projects/samsung_tv_root")
DEB = ROOT / "debloat"

# --- 1. mask.sh: full rewrite matching its claimed behaviour ---
mask = """#!/bin/sh
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
  case "$line" in ''|\\#*) continue ;; esac
  u=$(printf '%s' "$line" | tr -d '\\r' | awk '{$1=$1};1')
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
"""
(DEB / "tools" / "mask.sh").write_text(mask, encoding="utf-8", newline="\n")
print("mask.sh rewritten")

# --- 2. unmask.sh: same idempotency (already handled via -L check) ---
unmask = """#!/bin/sh
# unmask.sh - remove the /run mask symlinks created by mask.sh (undo).
# Same list.  (The /opt sentinel files used by vendor unit conditions are
# NOT touched by this tool.)
#   tools/unmask.sh lists/services-units.txt
set -u

LIST="${1:-}"
[ -n "$LIST" ] && [ ! -f "$LIST" ] && { echo "list not found: $LIST"; exit 2; }
RUNDIR=/run/systemd/system

ok=0; fail=0; absent=0; n=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\\#*) continue ;; esac
  u=$(printf '%s' "$line" | tr -d '\\r' | awk '{$1=$1};1')
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
done < "${LIST:--}"

systemctl daemon-reload 2>&1
echo
echo "summary: unmasked=$ok not-masked=$absent failed=$fail of $n"
[ "$fail" = "0" ] || exit 1
"""
(DEB / "tools" / "unmask.sh").write_text(unmask, encoding="utf-8", newline="\n")
print("unmask.sh rewritten")

# --- 3. q3deps.sh: escape dots, add /prd + *.path ---
q3 = """#!/bin/sh
# q3deps.sh - reverse-dependency gate for the mask list (v42 brief Q3).
# For every unit in the list: any OTHER unit file that Requires=/Wants=/
# BindsTo=/Requisite=s it.  Over-approximates (matches comments and
# substring-adjacent names are escaped, so it can only over-report - the
# safe direction for a gate).  Searches every unit path on this firmware
# (incl. /prd/usr/lib/systemd/system) and every unit file type.
#   cat q3deps.sh | sh -s /tmp/units.txt
set -u
LIST="${1:-}"
[ -n "$LIST" ] && [ ! -f "$LIST" ] && { echo "list not found: $LIST"; exit 2; }

DIRS="/usr/lib/systemd/system /prd/usr/lib/systemd/system"
coupled=0; checked=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\\#*) continue ;; esac
  u=$(printf '%s' "$line" | tr -d '\\r' | awk '{$1=$1};1')
  [ -n "$u" ] || continue
  case "$u" in *[!A-Za-z0-9@._-]*) echo "REFUSE: $u"; continue ;; esac
  checked=$((checked+1))
  u_esc=$(printf '%s' "$u" | sed 's/\\./\\\\./g')
  refs=""
  for d in $DIRS; do
    for f in "$d"/*.service "$d"/*.target "$d"/*.socket "$d"/*.path; do
      [ -f "$f" ] || continue
      case "$f" in *"/$u") continue ;; esac
      if grep -qE "(Requires|Wants|BindsTo|Requisite)[^=]*=[^=]*$u_esc" "$f" 2>/dev/null; then
        refs="$refs $f"
      fi
    done
  done
  if [ -n "$refs" ]; then
    coupled=$((coupled+1))
    echo "COUPLED $u <-$refs"
  fi
done < "$LIST"
echo
echo "q3: $coupled coupled of $checked checked (0 = mask list is dependency-safe)"
"""
(DEB / "tools" / "q3deps.sh").write_text(q3, encoding="utf-8", newline="\n")
print("q3deps.sh rewritten")

# --- 4. delete the falsified overlay scripts (technique preserved in the
#        run log + AGENTS rule 13; services-bind.txt stays as the kill list)
for dead in ["bindapply.sh", "bindrestore.sh"]:
    (DEB / "tools" / dead).unlink()
    print("deleted", dead)

# --- 5. apply.sh: fail-fast, drop dead uid block, prefix denylist ---
p = DEB / "tools" / "apply.sh"
t = p.read_text(encoding="utf-8")

# remove the unused owner-uid resolution (Vetro leftover; --global needs no uid)
old_uid = """u=$(stat -c %u "$OWNER_HOME" 2>/dev/null)
case "$u" in ""|*[!0-9]*) echo "VETRO-UID-NOT-RESOLVED"; exit 1;; esac
[ "$u" -gt 0 ] || { echo "VETRO-UID-INVALID"; exit 1; }
"""
assert old_uid in t
t = t.replace(old_uid, "")

# prefix deny for vetrotvapp (vetrotvapp.svc must also be denied)
old_deny = 'for d in $DENY; do [ "$id" = "$d" ] && denied=1; done'
new_deny = 'for d in $DENY; do [ "$id" = "$d" ] && denied=1; done\ncase "$id" in vetrotvapp*) denied=1 ;; esac'
assert old_deny in t
t = t.replace(old_deny, new_deny, 1)

# stop at the first unexpected failure (discipline #2)
old_fail = """  if pkgcmd -D -t app -n "$id" --global >/tmp/pkgcmd-apply.out 2>&1; then
    echo "disabled[$n]: $id"
    ok=$((ok+1))
  else
    echo "FAILED[$n]: $id (undo line already recorded)"
    fail=$((fail+1))
  fi"""
new_fail = """  if pkgcmd -D -t app -n "$id" --global >/tmp/pkgcmd-apply.out 2>&1; then
    echo "disabled[$n]: $id"
    ok=$((ok+1))
  else
    echo "FAILED[$n]: $id (undo line already recorded; stopping per discipline #2)"
    fail=$((fail+1))
    exit 1
  fi"""
assert old_fail in t
t = t.replace(old_fail, new_fail, 1)
p.write_text(t, encoding="utf-8", newline="")
print("apply.sh fixed")
print("PART B DONE")
