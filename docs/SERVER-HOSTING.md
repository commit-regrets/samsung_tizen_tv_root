# Running the PC-side server (and keeping it alive)

The server is the only thing the TV talks to: it serves `index.html` + the two JS
files, receives `/save` dumps, receives the app-payload beacons, and multiplexes
the physmap RPC gateway on port 80. If it dies, the TV page goes **blank a few
seconds after loading** — the symptoms look like a TV problem but are not.

## The trap that cost an afternoon

The server is a console program (`pysrv.exe`). Windows terminates a console
program when its console goes away, with **no traceback and no exit code worth
reading**:

* started from an agent/terminal job -> dies when that job is cancelled
* started by Task Scheduler as a bare console app -> dies when its console closes

Both look identical: `server.err` empty, task status `Ready`, page blank.

## How it runs now

Windows scheduled task **`TV-LabServer`** -> `lab_server\run_server.vbs` ->
`wscript.exe` (no console) -> `cmd /c pysrv.exe server.py` with stdout/stderr
appended to `logs\server.task.out` / `logs\server.task.err`.

Create it **without** `/RL HIGHEST` (that needs elevation and fails with
"Access is denied"):

```
schtasks /Create /TN "TV-LabServer" /TR "wscript.exe \"C:\...\lab_server\run_server.vbs\"" /SC ONCE /ST 23:59 /F
schtasks /Run   /TN "TV-LabServer"
```

Day to day:

```
schtasks /Query /TN "TV-LabServer" /FO LIST     # Status: Running = up
schtasks /End   /TN "TV-LabServer"              # stop
schtasks /Run   /TN "TV-LabServer"              # start
```

Verify from the outside:

```
Invoke-WebRequest http://<pc-ip>/index.html -UseBasicParsing   # expect 200
netstat -ano | findstr LISTENING | findstr ":80 :9998 :9999"   # three listeners
```

## Hardening in `server.py`

* `safe_accept()` wraps every `accept()` (http, control, rpc). A transient
  `OSError` there used to end the main thread, which ends the process.
* The `RSET` reply is guarded: a client that disconnects early no longer raises
  `BrokenPipeError` inside the RPC thread.
* `RSET` drops **both** the TV stub and any stale local client, so a cancelled
  client can't hold the gateway slot forever (`BUSY` for every later client).
* A crash now leaves a traceback in `logs\server.task.err`.

## Firewall

Inbound TCP 80/8080 must be allowed for **that exact program path**
(`...\pythoncore-3.14-64\pysrv.exe`), for **all profiles** — a Wi-Fi network
classified "Public" de-scoped the auto-created rule once and produced the same
blank page. Rule name used here: `TV lab HTTP (pysrv)`.

## Logs (first place to look)

| file | what |
|---|---|
| `logs\server.task.out` | lifecycle + every HTTP request + `[rpc] TV physmap stub connected` |
| `logs\server.task.err` | tracebacks (should be empty) |
| `logs\beacons.log` | one line per app-payload beacon — the boot diagnostic |
| `logs\tv\tv_output_*.txt` | page `/save` dumps (HARNESS_UP / WASM_LOADED / PAYLOAD_LOADED / RUNNING_AT) |

`/logs/**` is 404 on the server, so logs are never served to the TV.

## Reading the task status correctly

`wscript ... False` launches the server detached and returns immediately, so
**`schtasks /Query` shows `Status: Ready` even while the server is running.** Do
not treat that as "down". The real checks are:

```
netstat -ano | findstr LISTENING | findstr ":80 :9998 :9999"   # three listeners
Invoke-WebRequest http://<pc-ip>/index.html -UseBasicParsing    # 200
Get-Process pysrv                                               # one process
```