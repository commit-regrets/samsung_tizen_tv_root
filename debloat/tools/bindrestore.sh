#!/bin/sh
# bindrestore.sh - remove the /bin/true overlays created by bindapply.sh
# (umount).  Same list, same validation.
#   tools/bindrestore.sh lists/services-bind.txt
set -u

LIST="${1:-}"
[ -n "$LIST" ] && [ ! -f "$LIST" ] && { echo "list not found: $LIST"; exit 2; }
[ "$(id -u)" = "0" ] || { echo "must run as root"; exit 1; }

ok=0; fail=0; skip=0; n=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  name=$(printf '%s' "$line" | tr -d '\r' | awk '{$1=$1};1')
  case "$name" in
    *[!A-Za-z0-9_-]*|'') echo "REFUSE (not a bare program name): $name"; fail=$((fail+1)); continue ;;
  esac
  path="/usr/bin/$name"
  n=$((n+1))
  if ! mount | grep -q " on $path "; then
    echo "not-overlaid: $path"
    skip=$((skip+1))
    continue
  fi
  if umount "$path" 2>/dev/null; then
    echo "restored[$n]: $path"
    ok=$((ok+1))
  else
    echo "FAILED[$n]: umount $path"
    fail=$((fail+1))
  fi
done < "${LIST:--}"

echo
echo "summary: restored=$ok not-overlaid=$skip failed=$fail of $n"
[ "$fail" = "0" ] || exit 1
