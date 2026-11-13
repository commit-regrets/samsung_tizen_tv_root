#!/bin/sh
# Read-only boot diagnostics: why is MultiControl-Service not starting at boot?
B=/opt/usr/apps/com.samsung.tv.MultiControl-Service/bin
DB=/opt/dbspace/user/5001/.appsvc.db
GD=/opt/dbspace/.appsvc.db
P=/opt/dbspace/.pkgmgr_parser.db

echo DIAG_START
echo "== bin =="
ls -la "$B" 2>&1

echo "== boot_sequence (user) =="
sqlite3 "$DB" "select * from boot_sequence;" 2>&1
echo "== boot_sequence (global) =="
sqlite3 "$GD" "select * from boot_sequence;" 2>&1

echo "== pkgmgr tables =="
sqlite3 "$P" ".tables" 2>&1
echo "== app_onboot =="
sqlite3 "$P" "select * from app_onboot;" 2>&1 | grep -i multi
echo "== package row =="
sqlite3 "$P" "select * from package where appid like '%MultiControl%';" 2>&1 | head -3

echo "== aul processes =="
ps -ef 2>/dev/null | grep -iE 'aul|boot-manager|app-boot' | grep -v grep | head -8

echo "== aulctl =="
aulctl 2>&1 | head -6

echo "== journal (tail) =="
journalctl --no-pager 2>&1 | tail -8

echo "== logs =="
ls -lat /opt/var/log 2>/dev/null | head -10

echo "== share =="
ls -la /opt/usr/home/owner/share 2>/dev/null | grep -Ei 'mcs|allow|payload|root_boot'

echo "== dbus aul =="
ls -l /usr/bin/aulctl /usr/bin/aul* 2>&1 | head -5
echo DIAG_DONE
