#!/bin/sh
# bindapply.sh - neutralize system services by bind-mounting /bin/true over
# /usr/bin/<name> (from tizen-tv-control-center).  /usr is read-only, so the
# overlay IS the disable; it reverses with umount and dies at reboot unless
# the boot payload re-applies it (see README).
#
#   BIND=0 sh bindapply.sh lists/services-bind.txt    # dry run
#   sh bindapply.sh lists/services-bind.txt           # one-shot overlay
#   tools/bindrestore.sh lists/services-bind.txt      # undo (umount)
#
# This does NOT persist across a reboot by itself.  A one-shot overlay is
# still useful to measure the effect before wiring it into the boot payload.
set -u

LIST="${1:-}"
[ -n "$LIST" ] && [ ! -f "$LIST" ] && { echo "list not found: $LIST"; exit 2; }
BIND="${BIND:-1}"
[ "$(id -u)" = "0" ] || { echo "must run as root"; exit 1; }

ok=0; fail=0; dry=0; n=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  name=$(printf '%s' "$line" | tr -d '\r' | awk '{$1=$1};1')
  case "$name" in
    *[!A-Za-z0-9_-]*|'') echo "REFUSE (not a bare program name): $name"; fail=$((fail+1)); continue ;;
  esac
  path="/usr/bin/$name"
  [ -f "$path" ] || { echo "skip: $path not present"; continue; }
  n=$((n+1))
  if [ "$BIND" != "1" ]; then
    echo "DRY[$n] mount --bind /bin/true $path"
    dry=$((dry+1))
    continue
  fi
  if mount --bind /bin/true "$path" 2>/dev/null; then
    echo "overlaid[$n]: $path"
    ok=$((ok+1))
  else
    echo "FAILED[$n]: $path"
    fail=$((fail+1))
  fi
done < "${LIST:--}"

if [ "$BIND" = "1" ]; then
  echo
  echo "summary: overlaid=$ok failed=$fail of $n (undo: tools/bindrestore.sh with the same list)"
  [ "$fail" = "0" ] || exit 1
else
  echo
  echo "dry run: would overlay $dry of $n (re-run with BIND=1)"
fi
