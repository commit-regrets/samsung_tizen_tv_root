#!/bin/sh
# q3deps.sh - reverse-dependency gate for the mask list (v42 brief Q3).
# For every unit in the list: any OTHER unit file that Requires=/Wants=/
# BindsTo=/Requisite=s it. Over-approximates (matches comments too) - that
# is the safe direction for a gate.
#   cat q3deps.sh | sh -s /tmp/units.txt
set -u
LIST="${1:-}"
[ -n "$LIST" ] && [ ! -f "$LIST" ] && { echo "list not found: $LIST"; exit 2; }

coupled=0; checked=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  u=$(printf '%s' "$line" | tr -d '\r' | awk '{$1=$1};1')
  [ -n "$u" ] || continue
  case "$u" in *[!A-Za-z0-9@._-]*) echo "REFUSE: $u"; continue ;; esac
  checked=$((checked+1))
  refs=$(grep -lE "(Requires|Wants|BindsTo|Requisite)[^=]*=[^=]*$u" \
      /usr/lib/systemd/system/*.service \
      /usr/lib/systemd/system/*.target \
      /usr/lib/systemd/system/*.socket 2>/dev/null \
      | grep -v "/$u" | tr '\n' ' ')
  if [ -n "$refs" ]; then
    coupled=$((coupled+1))
    echo "COUPLED $u <- $refs"
  fi
done < "$LIST"
echo
echo "q3: $coupled coupled of $checked checked (0 = mask list is dependency-safe)"
