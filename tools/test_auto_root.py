"""Offline test for auto_root's fresh-stub retry loop.

A failed root must not end the run: auto_root prints a reload request, resets the
gateway, waits for a new stub, and tries again. This test fakes the RPC/kernel
layers so it never touches a TV.
"""
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import auto_root  # noqa: E402


class FakeRPC:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def main() -> int:
    state = {"rpc": 0, "root": 0, "reset": 0, "run": 0}

    def fake_rpc(*_a, **_k):
        state["rpc"] += 1
        return FakeRPC()

    def fake_root(_rpc):
        state["root"] += 1
        return state["root"] >= 2         # first stub fails, second roots

    def fake_run(_rpc, _cmd, _wait):
        state["run"] += 1
        return b"COPY=ok\nDEPLOY_DONE\n"

    def fake_reset():
        state["reset"] += 1

    with mock.patch.object(auto_root.T, "RPC", fake_rpc), \
         mock.patch.object(auto_root.T, "reset_stub", fake_reset), \
         mock.patch.object(auto_root.kroot, "root_via_fork", fake_root), \
         mock.patch.object(auto_root, "run", fake_run), \
         mock.patch.object(auto_root, "start_heartbeat", lambda *_a: None), \
         mock.patch.object(auto_root.time, "sleep", lambda _s: None):
        argv = sys.argv
        sys.argv = ["auto_root.py", "--host", "192.0.2.1", "--root-retries", "2"]
        try:
            rc = auto_root.main()
        finally:
            sys.argv = argv

    ok = (rc == 0 and state["rpc"] == 2 and state["root"] == 2
          and state["reset"] == 1 and state["run"] == 1)
    print("auto_root retry:", state, "rc=", rc, "=>", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
