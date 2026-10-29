#!/bin/sh
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
  case "$line" in ''|\#*) continue ;; esac
  u=$(printf '%s' "$line" | tr -d '\r' | awk '{$1=$1};1')
  [ -n "$u" ] || continue
  case "$u" in *[!A-Za-z0-9@._-]*) echo "REFUSE: $u"; continue ;; esac
  checked=$((checked+1))
  u_esc=$(printf '%s' "$u" | sed 's/\./\\./g')
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
