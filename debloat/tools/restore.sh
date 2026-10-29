#!/bin/sh
# restore.sh - re-activate every app_id in a debloat list (the undo of
# apply.sh, driven from the SAME list so apply and restore never diverge).
#   tools/restore.sh lists/batch1-tracking.txt
#   cat lists/batch1.txt | sh restore.sh
# Or replay a recorded undo log:  sh /opt/usr/home/owner/share/debloat-undo-*.sh
set -u

LIST="${1:-}"
[ -n "$LIST" ] && [ ! -f "$LIST" ] && { echo "list not found: $LIST"; exit 2; }

DB=/opt/dbspace/.pkgmgr_parser.db

ok=0; fail=0; n=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  id=$(printf '%s' "$line" | tr -d '\r' | awk '{$1=$1};1')
  case "$id" in *[!A-Za-z0-9@._-]*) echo "REFUSE (not a bare id): $id"; fail=$((fail+1)); continue ;; esac
  n=$((n+1))
  pkgcmd -A -t app -n "$id" --global >/tmp/pkgcmd-restore.out 2>&1
  flag=$(sqlite3 "$DB" "select app_disable from package_app_info where app_id='$id';")
  if [ "$flag" = "false" ]; then
    echo "activated[$n]: $id"
    ok=$((ok+1))
  else
    echo "FAILED[$n]: $id flag=${flag:-missing}"
    tail -2 /tmp/pkgcmd-restore.out
    fail=$((fail+1))
  fi
done < "${LIST:--}"

echo
echo "summary: activated=$ok failed=$fail of $n"
[ "$fail" = "0" ] || exit 1
