using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

// Minimal Samsung Tizen remote daemon.
//
// observe: read the remote event device and log key events; keys still work.
// filter: EVIOCGRAB the device, forward every unmapped key through /dev/uinput,
//         and run configured actions for mapped key-down events.
//
// The remote on this QNX1D is /dev/input/event6 ("Smart Control 2016").
// The daemon needs root only for filter mode (grab + /dev/uinput).
static class RemoteDaemon
{
    const int O_RDONLY = 0;
    const int O_WRONLY = 1;
    const int O_NONBLOCK = 0x800;
    const uint EVIOCGRAB = 0x40044590;
    const uint UI_SET_EVBIT = 0x40045564;
    const uint UI_SET_KEYBIT = 0x40045565;
    const uint UI_DEV_CREATE = 0x5501;
    const uint UI_DEV_DESTROY = 0x5502;
    const ushort EV_SYN = 0;
    const ushort EV_KEY = 1;
    const int EVENT_SIZE = 16;
    const int UINPUT_USER_DEV_SIZE = 1116;

    [DllImport("libc", SetLastError = true)]
    static extern int open(string path, int flags);
    [DllImport("libc", SetLastError = true)]
    static extern int read(int fd, byte[] buffer, int count);
    [DllImport("libc", SetLastError = true)]
    static extern int write(int fd, byte[] buffer, int count);
    [DllImport("libc", SetLastError = true)]
    static extern int close(int fd);
    [DllImport("libc", SetLastError = true)]
    static extern int ioctl(int fd, uint request, int value);

    sealed class Config
    {
        public string Device = "/dev/input/event6";
        public string Mode = "observe";
        public Dictionary<int, string> Map = new Dictionary<int, string>();

        public static Config Load(string path)
        {
            Config config = new Config();
            if (!File.Exists(path))
            {
                return config;
            }
            foreach (string raw in File.ReadAllLines(path))
            {
                string line = raw.Trim();
                if (line.Length == 0 || line.StartsWith("#"))
                {
                    continue;
                }
                int eq = line.IndexOf('=');
                if (eq <= 0)
                {
                    continue;
                }
                string key = line.Substring(0, eq).Trim();
                string value = line.Substring(eq + 1).Trim();
                if (key == "device")
                {
                    config.Device = value;
                }
                else if (key == "mode")
                {
                    config.Mode = value;
                }
                else if (key.StartsWith("map."))
                {
                    int code;
                    if (int.TryParse(key.Substring(4), out code) && code >= 0 && code <= 0x2ff)
                    {
                        config.Map[code] = value;
                    }
                }
            }
            return config;
        }
    }

    static string _logPath;
    static StreamWriter _log;
    static int _inputFd = -1;
    static int _uinputFd = -1;
    static bool _grabbed;

    static void Log(string message)
    {
        string line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " " + message;
        try
        {
            _log.WriteLine(line);
            _log.Flush();
        }
        catch
        {
        }
    }

    static bool Launch(string appId)
    {
        if (appId.Length == 0 || appId.Length > 120)
        {
            return false;
        }
        foreach (char c in appId)
        {
            if (!(char.IsLetterOrDigit(c) || c == '.' || c == '_' || c == '-'))
            {
                return false;
            }
        }
        try
        {
            ProcessStartInfo info = new ProcessStartInfo("/usr/bin/app_launcher");
            info.ArgumentList.Add("-s");
            info.ArgumentList.Add(appId);
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            Process.Start(info);
            return true;
        }
        catch (Exception ex)
        {
            Log("launch failed app=" + appId + " error=" + ex.Message);
            return false;
        }
    }

    static int CreateUinput(string name)
    {
        int fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
        if (fd < 0)
        {
            return -1;
        }
        if (ioctl(fd, UI_SET_EVBIT, EV_KEY) != 0 || ioctl(fd, UI_SET_EVBIT, EV_SYN) != 0)
        {
            close(fd);
            return -1;
        }
        for (int code = 0; code <= 0x2ff; code++)
        {
            ioctl(fd, UI_SET_KEYBIT, code);
        }
        byte[] device = new byte[UINPUT_USER_DEV_SIZE];
        byte[] encoded = Encoding.ASCII.GetBytes(name);
        Array.Copy(encoded, 0, device, 0, Math.Min(encoded.Length, 79));
        if (write(fd, device, device.Length) != device.Length)
        {
            close(fd);
            return -1;
        }
        if (ioctl(fd, UI_DEV_CREATE, 0) != 0)
        {
            close(fd);
            return -1;
        }
        return fd;
    }

    static void Forward(ushort type, ushort code, int value)
    {
        if (_uinputFd < 0)
        {
            return;
        }
        byte[] ev = new byte[EVENT_SIZE];
        ev[8] = (byte)(type & 0xff);
        ev[9] = (byte)(type >> 8);
        ev[10] = (byte)(code & 0xff);
        ev[11] = (byte)(code >> 8);
        ev[12] = (byte)(value & 0xff);
        ev[13] = (byte)((value >> 8) & 0xff);
        ev[14] = (byte)((value >> 16) & 0xff);
        ev[15] = (byte)((value >> 24) & 0xff);
        write(_uinputFd, ev, ev.Length);
    }

    static void Release()
    {
        if (_grabbed && _inputFd >= 0)
        {
            ioctl(_inputFd, EVIOCGRAB, 0);
            _grabbed = false;
        }
        if (_uinputFd >= 0)
        {
            ioctl(_uinputFd, UI_DEV_DESTROY, 0);
            close(_uinputFd);
            _uinputFd = -1;
        }
        if (_inputFd >= 0)
        {
            close(_inputFd);
            _inputFd = -1;
        }
    }

    static int Main(string[] args)
    {
        string configPath = "/opt/usr/data/remote-map.conf";
        string logPath = "/opt/usr/data/remote-daemon.log";
        string modeOverride = null;
        string deviceOverride = null;
        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] == "--config" && i + 1 < args.Length)
            {
                configPath = args[++i];
            }
            else if (args[i] == "--log" && i + 1 < args.Length)
            {
                logPath = args[++i];
            }
            else if (args[i] == "--mode" && i + 1 < args.Length)
            {
                modeOverride = args[++i];
            }
            else if (args[i] == "--device" && i + 1 < args.Length)
            {
                deviceOverride = args[++i];
            }
        }

        Config config = Config.Load(configPath);
        string mode = modeOverride ?? config.Mode;
        string device = deviceOverride ?? config.Device;
        if (mode != "observe" && mode != "filter")
        {
            Console.Error.WriteLine("mode must be observe or filter");
            return 2;
        }

        _logPath = logPath;
        _log = new StreamWriter(logPath, true) { AutoFlush = true };
        Console.CancelKeyPress += delegate { Release(); };
        AppDomain.CurrentDomain.ProcessExit += delegate { Release(); };

        _inputFd = open(device, O_RDONLY);
        if (_inputFd < 0)
        {
            Log("open failed device=" + device);
            return 1;
        }

        if (mode == "filter")
        {
            _uinputFd = CreateUinput("dsh-remote");
            if (_uinputFd < 0)
            {
                Log("uinput create failed; refusing filter mode");
                Release();
                return 1;
            }
            if (ioctl(_inputFd, EVIOCGRAB, 1) != 0)
            {
                Log("EVIOCGRAB failed; refusing filter mode");
                Release();
                return 1;
            }
            _grabbed = true;
        }

        Log("start mode=" + mode + " device=" + device + " maps=" + config.Map.Count);
        HashSet<ushort> withheld = new HashSet<ushort>();
        byte[] buffer = new byte[EVENT_SIZE];
        while (true)
        {
            int count = read(_inputFd, buffer, buffer.Length);
            if (count != EVENT_SIZE)
            {
                if (count < 0)
                {
                    Thread.Sleep(10);
                }
                continue;
            }
            ushort type = BitConverter.ToUInt16(buffer, 8);
            ushort code = BitConverter.ToUInt16(buffer, 10);
            int value = BitConverter.ToInt32(buffer, 12);
            if (type == EV_KEY)
            {
                Log("key code=" + code + " value=" + value);
            }

            bool mapped = false;
            if (type == EV_KEY)
            {
                if (value == 1 && config.Map.ContainsKey(code))
                {
                    mapped = true;
                    withheld.Add(code);
                    string action = config.Map[code];
                    if (action.StartsWith("launch:"))
                    {
                        string appId = action.Substring(7);
                        bool ok = Launch(appId);
                        Log("code=" + code + " action=launch app=" + appId + " ok=" + ok);
                    }
                    else
                    {
                        Log("code=" + code + " action=unknown value=" + action);
                    }
                }
                else if (value == 0 && withheld.Remove(code))
                {
                    mapped = true;
                }
                else if (withheld.Contains(code))
                {
                    mapped = true;
                }
            }

            if (mode == "filter")
            {
                if (type == EV_SYN)
                {
                    Forward(type, code, value);
                }
                else if (type == EV_KEY && !mapped)
                {
                    Forward(type, code, value);
                }
            }
        }
    }
}
