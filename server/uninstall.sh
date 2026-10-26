#!/bin/sh
# Undo the root payload: restore the stock MultiControl-Service app.
# Run on the TV as root (via the 31337 channel or the browser root).
# Reboot afterwards; the app keeps the old code in memory until then.
#
# The stock files we copy back MUST get the app's SMACK label.  A file created
# by the deployer keeps the *deployer's* label, and the app is then denied read
# on its own assembly and dies before Main - that is the 2026-10-22 boot
# regression, and the undo path had the same bug.
#
# Ordering is deliberate (review 2026-10-26):
#   * every replacement is relabelled and verified on a TEMP file before the
#     rename, so a relabel failure can never leave an unreadable stock DLL in
#     bin/ (the old code copied first and relabelled after);
#   * the allowlist is deleted LAST: it fails closed, so removing it before a
#     step that can fail would lock the channel while the payload still runs.
B=/opt/usr/apps/com.samsung.tv.MultiControl-Service/bin
S=/opt/usr/home/owner/share
DB=/opt/dbspace/user/5001/.appsvc.db
IL_MD5=f61f60dd2f581f60bcb716c336cd78f2
NI_MD5=6c9bdcc40d685e4adc3e2c9ea64870d1
WANT_LABEL=User::Pkg::com.samsung.tv.MultiControl-Service::RO
APPID=com.samsung.tv.MultiControl-Service

D_TMP="$B/MultiControlService.dll.tmp"
NI_TMP="$B/.native_image/MultiControlService.ni.dll.tmp"
cleanup() {
  rm -f "$D_TMP" "$NI_TMP" 2>/dev/null
}
trap cleanup 0
trap 'exit 130' 1 2 15

# A backup is trusted if it is the retail build OR if deploy.sh recorded this
# exact md5 when it snapshotted it (a non-retail TV can then still uninstall).
_matches() {
  got=$1; stock=$2; rec=$3
  [ "$got" = "$stock" ] && return 0
  [ -n "$got" ] && [ -f "$rec" ] && [ "$got" = "$(cat "$rec" 2>/dev/null)" ]
}

relabel_tmp() {
  chsmack -a "$WANT_LABEL" "$1" 2>/dev/null
  GOT=$(ls -lZ "$1" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i ~ /^User::|^System::|^_$/) {print $i; exit}}')
  echo "LABEL($1)=$GOT"
  if [ "$GOT" != "$WANT_LABEL" ]; then
    echo LABEL_WARN
    return 1
  fi
  return 0
}

echo UNINSTALL_START
U=$(id -u)
echo "UID=$U"
if [ "$U" != "0" ]; then
  echo NOT_ROOT
  exit 1
fi
if [ ! -f "$DB" ]; then
  echo DB_MISSING
  echo "HINT: $DB is not present - refusing to report success against the wrong database"
  exit 1
fi

# --- stock IL -----------------------------------------------------------
if [ ! -f "$S/mcs_orig.dll" ]; then
  echo NO_IL_BACKUP
  exit 1
fi
GOT_IL=$(md5sum "$S/mcs_orig.dll" | cut -d' ' -f1)
if ! _matches "$GOT_IL" "$IL_MD5" "$S/mcs_orig.md5"; then
  echo BAD_IL_BACKUP
  exit 1
fi
cp -p "$S/mcs_orig.dll" "$D_TMP" || { echo IL_FAIL; exit 1; }
relabel_tmp "$D_TMP" || exit 1
mv "$D_TMP" "$B/MultiControlService.dll" || { echo IL_FAIL; exit 1; }
echo "IL=$(md5sum "$B/MultiControlService.dll")"

# --- stock AOT ----------------------------------------------------------
A=$(ls -dt "$B"/.native_image.disabled.* 2>/dev/null | head -n1)
if [ -n "$A" ] && [ ! -e "$B/.native_image" ]; then
  mv "$A" "$B/.native_image" && echo AOT_DIR=restored
fi
if [ -f "$S/mcs_ni_orig.dll" ]; then
  GOT_NI=$(md5sum "$S/mcs_ni_orig.dll" | cut -d' ' -f1)
  if ! _matches "$GOT_NI" "$NI_MD5" "$S/mcs_ni_orig.md5"; then
    echo BAD_NI_BACKUP
    exit 1
  fi
  mkdir -p "$B/.native_image" || { echo NI_FAIL; exit 1; }
  cp -p "$S/mcs_ni_orig.dll" "$NI_TMP" || { echo NI_FAIL; exit 1; }
  relabel_tmp "$NI_TMP" || exit 1
  mv "$NI_TMP" "$B/.native_image/MultiControlService.ni.dll" || { echo NI_FAIL; exit 1; }
  echo "NI=$(md5sum "$B/.native_image/MultiControlService.ni.dll")"
fi

# --- boot row (ours; /tmp/keep_boot keeps it) ---------------------------
if [ -f /tmp/keep_boot ]; then
  echo BOOT_ROW=kept
else
  sqlite3 "$DB" ".timeout 5000" "delete from boot_sequence where appid='$APPID';" || {
    echo DB_FAIL
    exit 1
  }
  # trust nothing: read the table back (a DELETE that silently matched nothing, or
  # a locked DB, looks identical to success otherwise)
  LEFT=$(sqlite3 "$DB" ".timeout 5000" "select count(*) from boot_sequence where appid='$APPID';" 2>/dev/null)
  echo "BOOT_ROW=removed remain=${LEFT:-unknown}"
  [ "$LEFT" = "0" ] || { echo BOOT_ROW_WARN; exit 1; }
fi

# --- our leftovers ------------------------------------------------------
# rootchan.allow goes LAST: it fails closed, and every step above can still exit
# non-zero.  Deleting it earlier would leave the payload running but deaf to the
# PC, forcing a browser-lane retry.
rm -f "$S/payload_backup.dll" "$S/rootchan.host" /tmp/mcs_payload.dll
rm -f /tmp/v4.dll /tmp/v5.dll 2>/dev/null
rm -f "$S/rootchan.allow"
echo "ALLOW=removed"
rm -f /tmp/keep_boot 2>/dev/null
echo UNINSTALL_DONE
