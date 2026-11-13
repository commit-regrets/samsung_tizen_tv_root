"""Protocol tests for a LIVE browser stub (needs a fresh page load on the TV).

    python tools/test_stub.py                 # read/write + clamp checks
    python tools/test_stub.py --bad-run       # also the op-7 overlong case (kills the stub)

The stub is the ARM shellcode the exploit page installs in the renderer; this
test speaks its RPC directly through the gateway on 127.0.0.1:9998. It checks
the parts of the wire contract that the PC tools rely on and that a bad client
must not be able to break:

  * the hello is sane and the kernel Image is readable;
  * a normal read/write works;
  * an over-long READ (offset+len past the 4 KB mapping) is refused with
    -EINVAL and the stub KEEPS SERVING (no payload follows, so no desync);
  * a WRITE at offset 0xFFE is refused the same way;
  * with --bad-run, an over-long op 7 (command buffer is 512 B) is refused and
    the stub exits instead of parsing the leftover bytes as a new header.

Run it on a fresh stub: a page reload is the only way to get one, and an op 7 or
a file write consumes the stub for good.
"""
import argparse
import struct
import sys
import time

import physmap as T

IMAGE = 0x20008000
IMG_SIG = bytes([0xEE, 0x44, 0x00, 0xEB, 0x00, 0x90, 0x0F, 0xE1])
EINVAL = -22


def status(rpc):
    return struct.unpack("<i", rpc._recv_exact(4))[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hello-timeout", type=float, default=25.0,
                    help="seconds to wait for a stub (default 25)")
    ap.add_argument("--bad-run", action="store_true",
                    help="also send an over-long op 7 (this ends the stub)")
    args = ap.parse_args()

    try:
        rpc = T.RPC(timeout=15, hello_timeout=args.hello_timeout)
    except (TimeoutError, OSError) as exc:
        print(f"[-] no stub: {exc}")
        return 2

    failed = 0

    def check(name, ok, note=""):
        nonlocal failed
        failed += not ok
        print(("PASS" if ok else "FAIL"), name, ("- " + note if note else ""), flush=True)

    try:
        check("hello magic", rpc.magic == b"PGDB", f"{rpc.magic!r} open_ret={rpc.open_ret}")

        sig = rpc.read(IMAGE, 8)
        check("kernel image readable", sig == IMG_SIG, sig.hex())

        check("normal read", len(rpc.read(IMAGE + 0x400, 16)) == 16)

        # READ: offset 0, len 0x2000 -> past the 4 KB page map
        rpc._cmd(0, IMAGE, 0, 0x2000)
        st = status(rpc)
        check("oversized READ refused", st == EINVAL, f"status {st}")

        # the stub must still be serving: no payload preceded this op
        check("stub alive after bad READ", len(rpc.read(IMAGE, 8)) == 8)

        # WRITE32: 4 bytes at 0xFFE would cross the page
        rpc._cmd(1, IMAGE, 0xFFE, 0)
        st = status(rpc)
        check("cross-page WRITE refused", st == EINVAL, f"status {st}")
        check("stub alive after bad WRITE", len(rpc.read(IMAGE, 8)) == 8)

        if args.bad_run:
            rpc._cmd(7, 0, 0, 600)          # cmdbuf is 512 B
            rpc.s.sendall(b"A" * 600)
            try:
                st = status(rpc)
            except (EOFError, OSError):
                st = None
            check("overlong RUN refused", st == EINVAL, f"status {st}")
            closed = False
            try:
                rpc.s.settimeout(5)
                closed = rpc.s.recv(1) == b""
            except OSError:
                closed = True
            check("overlong RUN ended the stub", closed, "stream would be desynced")
    except Exception as exc:
        print(f"[-] {type(exc).__name__}: {exc}")
        failed += 1
    finally:
        try:
            rpc.close()
        except Exception:
            pass

    print(flush=True)
    if failed:
        print(f"{failed} check(s) failed")
        return 1
    print("stub protocol ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
