#!/bin/sh
# Undo the root payload: restore the stock MultiControl-Service app.
# Run on the TV as root (via the 31337 channel or the browser root).
# Reboot afterwards; the app keeps the old code in memory until then.
#
# The stock files we copy back MUST get the app's SMACK label.  A file created
# by the deployer keeps the *deployer's* label, and the app is then denied read
# on its own assembly and dies before Main - that is the 2026-10-22 boot
# regression, and the undo path had the same bug.

B=/opt/usr/apps/com.samsung.tv.MultiControl-Service/bin
S=/opt/usr/home/owner/share
DB=/opt/dbspace/user/5001/.appsvc.db
IL_MD5=f61f60dd2f581f60bcb716c336cd78f2
NI_MD5=6c9bdcc40d685e4adc3e2c9ea64870d1
WANT_LABEL=User::Pkg::com.samsung.tv.MultiControl-Service::RO

relabel() {
  chsmack -a "$WANT_LABEL" "$1" 2>/dev/null
  GOT=$(ls -lZ "$1" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i ~ /^User::|^System::|^_$/) {print $i; exit}}')
  echo "LABEL($1)=$GOT"
  [ "$GOT" = "$WANT_LABEL" ] || echo LABEL_WARN
}

echo UNINSTALL_START
U=$(id -u)
echo "UID=$U"
if [ "$U" != "0" ]; then
  echo NOT_ROOT
  exit 1
fi

# --- stock IL -----------------------------------------------------------
if [ ! -f "$S/mcs_orig.dll" ]; then
  echo NO_IL_BACKUP
  exit 1
fi
if ! md5sum "$S/mcs_orig.dll" | grep -q "^$IL_MD5"; then
  echo BAD_IL_BACKUP
  exit 1
fi
cp "$S/mcs_orig.dll" "$B/MultiControlService.dll.tmp" &&
  mv "$B/MultiControlService.dll.tmp" "$B/MultiControlService.dll" ||
  { echo IL_FAIL; exit 1; }
echo "IL=$(md5sum "$B/MultiControlService.dll")"
relabel "$B/MultiControlService.dll"

# --- stock AOT ----------------------------------------------------------
A=$(ls -dt "$B"/.native_image.disabled.* 2>/dev/null | head -n1)
if [ -n "$A" ] && [ ! -e "$B/.native_image" ]; then
  mv "$A" "$B/.native_image" && echo AOT_DIR=restored
fi
if [ -f "$S/mcs_ni_orig.dll" ]; then
  if ! md5sum "$S/mcs_ni_orig.dll" | grep -q "^$NI_MD5"; then
    echo BAD_NI_BACKUP
    exit 1
  fi
  mkdir -p "$B/.native_image"
  cp "$S/mcs_ni_orig.dll" "$B/.native_image/MultiControlService.ni.dll.tmp" &&
    mv "$B/.native_image/MultiControlService.ni.dll.tmp" \
       "$B/.native_image/MultiControlService.ni.dll" || {
    echo NI_FAIL
    exit 1
  }
  echo "NI=$(md5sum "$B/.native_image/MultiControlService.ni.dll")"
  relabel "$B/.native_image/MultiControlService.ni.dll"
fi

# --- our leftovers ------------------------------------------------------
rm -f "$S/payload_backup.dll" "$S/rootchan.allow" /tmp/mcs_payload.dll /tmp/v4.dll /tmp/v5.dll

# --- boot row (ours; /tmp/keep_boot keeps it) ---------------------------
if [ -f /tmp/keep_boot ]; then
  echo BOOT_ROW=kept
else
  sqlite3 "$DB" "delete from boot_sequence where appid='com.samsung.tv.MultiControl-Service';" || {
    echo DB_FAIL
    exit 1
  }
  # trust nothing: read the table back (a DELETE that silently matched nothing, or
  # a locked DB, looks identical to success otherwise)
  LEFT=$(sqlite3 "$DB" "select count(*) from boot_sequence where appid='com.samsung.tv.MultiControl-Service';" 2>/dev/null)
  echo "BOOT_ROW=removed remain=${LEFT:-unknown}"
  [ "$LEFT" = "0" ] || { echo BOOT_ROW_WARN; exit 1; }
fi
echo UNINSTALL_DONE
