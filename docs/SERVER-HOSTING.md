# Running the PC-side server (and keeping it alive)

The server is the only thing the TV talks to: it serves `index.html` and the two JS
files, receives `/save` dumps and app-payload beacons, and multiplexes the physmap
RPC gateway on port 80. **If it dies, the TV page goes blank a few seconds after
loading** — the symptoms look like a TV fault but they are not.

## The trap

The server is a console program. Windows terminates a console program when its
console goes away, with **no traceback and no meaningful exit code**:

- started from a terminal or agent job → dies when that job is cancelled;
- started by Task Scheduler as a bare console app → dies when its console closes.

Both look identical afterwards: an empty error log, a task that reports `Ready`, and
a blank page. This is worth stating plainly because it cost an afternoon of
debugging the TV that was never at fault.

## How it should run

```
Task Scheduler ──▶ wscript.exe server\run_server.vbs    (no console)
                        └─▶ cmd /c server\run_server.cmd
                                └─▶ <interpreter> server.py  >> logs\server.task.out
                                                              2>> logs\server.task.err
```

`server/run_server.vbs` exists so there is **no console to close**.
`server/run_server.cmd` does the actual launch and creates `logs/` if needed.

Create the task **without** `/RL HIGHEST` — that needs elevation and fails with
"Access is denied":

```
schtasks /Create /TN "TV-LabServer" /TR "wscript.exe \"<repo>\server\run_server.vbs\"" /SC ONCE /ST 23:59 /F
schtasks /Run    /TN "TV-LabServer"
```

Day to day:

```
schtasks /Query /TN "TV-LabServer" /FO LIST     # note: Ready != down, see below
schtasks /End   /TN "TV-LabServer"              # stop
schtasks /Run   /TN "TV-LabServer"              # start
```

## The interpreter, and the firewall

Set `TV_PY` to whichever interpreter the firewall permits before starting; the
launcher falls back to `python`. On Windows the firewall rule is **per program
path**, so a renamed copy of the interpreter (for example `pysrv.exe`) is the usual
workaround when a Block rule exists for the original path.

Inbound TCP 80 must be allowed for **that exact path**, for **all profiles**. A
Wi-Fi network classified as "Public" de-scoped the auto-created rule once and
produced the same blank page. Also allow 8080 if you experiment with it.

The RPC gateway and control channel bind `127.0.0.1` (`9998`, `9999`) and need no
firewall rule; the TV only ever talks to port 80 and to `31337` on its own side.

## Hardening in `server.py`

- `safe_accept()` wraps every `accept()` (http, control, rpc). A transient `OSError`
  there used to end the main thread, which ends the process.
- The `RSET` reply is guarded: a client that disconnects early no longer raises
  `BrokenPipeError` inside the RPC thread.
- `RSET` evicts the **paired** stub and its client. A client that is still *waiting*
  for a stub is deliberately left alone — evicting it destroyed stubs that connected
  between two attempts.
- **A request line is always answered as HTTP.** Anything that is not
  GET/POST/HEAD/OPTIONS gets 405. Before v39 every other method fell through to
  the reverse-shell handler, so any LAN client could take the operator's shell
  slot with one `PATCH /` (found live during the 2026-10-26 review).
- **The shell slot is TV-only and token-gated**: a silent raw connection is
  accepted only from a peer that announced itself — a `PGDB` stub whose 4-byte
  pairing token matches the page's `POST /pair` announcement (v40), or a
  `DSHROOT` beacon whose `tok=` matches the deploy-rendered `rootchan.token`
  (v41). Unknown tokens are refused outright; token-less beacons are logged but
  never admitted.
- **`/deploy.sh` is rendered per request** (`H=` from the IPv4 `Host` header,
  `WANT=`/`SIZE_WANT=` from the md5/size of `payload.dll`, `TOKEN=` fresh per
  render — the last two renders stay valid so a stray GET cannot orphan the
  running payload); a non-IPv4 `Host` gets 409, and a static file server's
  unrendered copy is refused by the script itself (`NEED_RENDER`).
- **`PGDB` queue is capped** at 8 (oldest closed) and `/save` refuses a
  cross-origin POST; beacon lines are capped at 4 KB.
- A crash leaves a traceback in `logs/server.task.err`.

- **Every post-peek read is bounded** (2 s at accept, 10 s for the HTTP body):
  a peer that sends `DSHROOT`/`GET ` and stalls can no longer hold the single
  accept thread.
- **The shell slot cannot be evicted by another peer**; the same TV may replace
  its own. `tv_sock` is only aimed at a stub after op5/op7 (before that,
  keystrokes would be parsed as an RPC header and desync the operation).
- **`RSET` is matched across split TCP segments** (`RSE` + `T`), and
  `beacons.log` rotates at 16 MiB (`beacons.log.1`) so a LAN peer cannot fill
  the disk with 4 KB lines.
## Reading the task status correctly

`wscript … , False` launches the server detached and returns immediately, so
**`schtasks /Query` reports `Status: Ready` even while the server is running.** Do
not treat that as "down". The real checks:

```
netstat -ano | findstr LISTENING | findstr ":80 :9998 :9999"   # three listeners
Invoke-WebRequest http://<pc-ip>/index.html -UseBasicParsing    # 200
Get-Process <interpreter>                                       # one process
```

## Logs (first place to look)

| file | what |
|---|---|
| `logs/server.task.out` | lifecycle, every HTTP request, `[rpc] TV physmap stub connected` |
| `logs/server.task.err` | tracebacks (should be empty) |
| `logs/beacons.log` | one line per app-payload beacon — the boot diagnostic |
| `logs/tv/tv_output_*.txt` | page `/save` dumps (`HARNESS_UP`, `WASM_LOADED`, `PAYLOAD_LOADED`, `RUNNING_AT`) |
| `logs/shell.log` | captured TV console output from the control channel |

`/logs/**` is 404 on the server, so logs are never served to the TV.
