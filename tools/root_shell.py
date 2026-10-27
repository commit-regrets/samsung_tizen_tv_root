"""Talk to the root channel on the TV (TCP 31337, line protocol).

Usage: python tools/root_shell.py "<command>" [tv-ip]

The address can also come from TV_IP or ROOT_TV (the name the .ps1 wrappers
use), so `$env:ROOT_TV = "..."; python tools/root_shell.py id` works.
Exit codes: 0 ok, 2 no address, 1 connection/protocol failure.
Connection failures diagnose themselves: the stderr block names the likely
cause and the next step (full dictionary: docs/LOGGUIDE.md).
"""
import errno
import os
import socket
import sys

# TV output is bytes; a Windows console can be cp1252 and a dump can contain
# anything.  Never crash the client because a byte did not decode (review
# 2026-10-26; Python 3.14 still uses locale encodings off a redirected stdout).
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

host = (sys.argv[2] if len(sys.argv) > 2
        else os.environ.get("TV_IP") or os.environ.get("ROOT_TV"))
if not host:
    print('usage: root_shell.py "<command>" [tv-ip]   (or set TV_IP / ROOT_TV)',
          file=sys.stderr)
    raise SystemExit(2)
cmd = sys.argv[1] if len(sys.argv) > 1 else "id"

BEACONS = "server/logs/beacons.log"

try:
    s = socket.create_connection((host, 31337), timeout=8)
    # A command may legitimately run for the payload's Run() budget (120 s), and
    # the reply only arrives at __END__, so the read timeout must be able to
    # exceed it (ROOT_SHELL_TIMEOUT; the .ps1 deploy/uninstall set 180).
    s.settimeout(float(os.environ.get("ROOT_SHELL_TIMEOUT", "30")))
except OSError as exc:
    # Windows note: a connect timeout raises socket.timeout (errno None);
    # the winerror spellings (10060/10061/...) differ from the errno ones.
    why = exc.errno if exc.errno is not None else getattr(exc, "winerror", None)
    refused = why in (errno.ECONNREFUSED, 10061)
    timed_out = isinstance(exc, socket.timeout) or why in (errno.ETIMEDOUT, 10060)
    unreachable = why in (errno.EHOSTUNREACH, errno.ENETUNREACH,
                          errno.EHOSTDOWN, 10065, 10051, 10064)
    print(f"root_shell: cannot connect to {host}:31337: {exc}", file=sys.stderr)
    if refused:
        print("""  the host answered but refused 31337. Either this is not the TV, or the
  app is up without the channel open:
  - beacons.log shows SUCCESS-R00T and then silence -> the app died since;
    AUL restarts it in ~1-45 s, or find it with the browser lane.
  - beacons.log has no SUCCESS this boot -> the boot chain failed; run
    'python tools/beacons.py --last 1' and read the verdict.
  - <tv-ip> stale (DHCP moved it to another device): confirm the address
    before deploying anything - the md5 gate in deploy.sh is the backstop.""",
              file=sys.stderr)
    elif timed_out or unreachable:
        # nobody answered, or the route does not exist.  Do NOT ping to
        # disambiguate: a VPN tunnel answers ICMP errors and Windows ping
        # reports 0% loss (AGENTS.md trap 17).
        print("""  nobody answered. Check, in order:
  1. tail server/logs/beacons.log - a fresh DSHROOT line after the last boot
     means the payload runs (then this is a network problem); no fresh line
     means the app never started (boot row gone, DLL broken, or the TV is in
     standby - the remote power button is standby, not a boot).
  2. this PC on the TV's LAN with the VPN off: 'ipconfig' should show an IPv4
     on the TV's subnet; 'route print -4' must route it locally, not into a
     tunnel gateway (198.51.100.1 = NordVPN here).
  3. if beacons look fine and the route is local, the payload may hold or wait
     on /dev/video40 - a 'fail open video40' line in the log names it.

  (ping proves nothing here - AGENTS.md trap 17: a VPN tunnel answers ICMP
  errors and Windows ping reports them as 0% loss / exit 0.)""",
              file=sys.stderr)
    else:
        print("  unexpected connect error - dictionary: docs/LOGGUIDE.md",
              file=sys.stderr)
    raise SystemExit(1)
s.sendall(cmd.encode() + b"\n")
buf = b""
while b"__END__" not in buf:
    try:
        d = s.recv(4096)
    except socket.timeout:
        break
    if not d:
        break
    buf += d
if b"__END__" not in buf:
    print("root_shell: 31337 answered but never sent __END__ - a foreign "
          "service owns the port, or the channel died mid-reply. "
          "The peer is dropped server-side after 30 s of silence; retry once, "
          "then re-check beacons.log.", file=sys.stderr)
    s.close()
    raise SystemExit(1)
sys.stdout.write(buf.decode("latin-1", "replace"))
s.close()
raise SystemExit(0)
