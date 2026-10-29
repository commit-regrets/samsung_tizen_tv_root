#!/bin/sh
# restore.sh - re-activate every app_id in a debloat list (the undo of
# apply.sh, driven from the SAME list so apply and restore never diverge).
#   cat tools/restore.sh | sh -s lists/batch1-tracking.txt
# Or replay a recorded undo log:  cat /opt/usr/data/debloat-undo-*.sh | sh
# (UEP blocks `sh /path/to/file`.)
# The list MUST be a file argument - no stdin fallback, because the usual
# invocation is `cat restore.sh | sh -s <list>` and stdin carries the script.
# (Review 2026-10-30: the old `${LIST:--}` default was a literal "-" file,
# so `cat list | sh restore.sh` silently activated nothing and exited 0.)
set -u

LIST="${1:-}"
[ -n "$LIST" ] || { echo "usage: restore.sh <list-file>  (the list must be a file; stdin carries the script when piped)"; exit 2; }
[ -f "$LIST" ] || { echo "list not found: $LIST"; exit 2; }

DB=/opt/dbspace/.pkgmgr_parser.db
SENTINEL_DIR=/opt/usr/share/systemd/system

ok=0; fail=0; n=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  id=$(printf '%s' "$line" | tr -d '\r' | awk '{$1=$1};1')
  [ -n "$id" ] || continue   # whitespace-only line
  case "$id" in *[!A-Za-z0-9@._-]*) echo "REFUSE (not a bare id): $id"; fail=$((fail+1)); continue ;; esac
  n=$((n+1))
  pkgcmd -A -t app -n "$id" --global >/tmp/pkgcmd-restore.out 2>&1
  flag=$(sqlite3 "$DB" ".timeout 5000" "select app_disable from package_app_info where app_id='$id';")
  if [ "$flag" = "false" ]; then
    echo "activated[$n]: $id"
    ok=$((ok+1))
    case "$id" in
      com.samsung.tv.canalysis-service) rm -f "$SENTINEL_DIR/canalysis-daemon" ;;
      com.samsung.tv.pisa-service) rm -f "$SENTINEL_DIR/pisa-service" ;;
    esac
  else
    echo "FAILED[$n]: $id flag=${flag:-missing} (stopping per discipline #2)"
    tail -2 /tmp/pkgcmd-restore.out
    exit 1
  fi
done < "$LIST"

echo
echo "summary: activated=$ok failed=$fail of $n"
if [ "$n" = "0" ]; then
  echo "FAIL: $LIST yielded no valid app ids"
  exit 2
fi
[ "$fail" = "0" ] || exit 1
