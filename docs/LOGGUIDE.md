# Log guide — every beacon and tool error, what it means, what to do

Audience: the next agent or human reading a log cold. Everything here is also
encoded in `tools/beacons.py` (machine-readable decoding of the beacon log);
this file is the reference it points to. History and *why* live in
`CHANGELOG.md` / `docs/OPEN-ISSUES.md`; this file only says what a line means
**now** and what to do about it.

## Where logs live

| Path | What |
|---|---|
| `server/logs/beacons.log` | one line per `DSHROOT …` beacon — **start here** |
| `share/root_boot.txt` (on the TV) | the same beacons, written locally by the payload (survives when the PC is unreachable) |
| `server/logs/shell.log(.1)` | rolling TV shell/console capture (8 MB rotation) |
| `server/logs/server.out/.err` | the port-80 server |
| `server/logs/tv/` | exploit-page POST `/save` dumps (newest 100) |

Fast path: `python tools/beacons.py` (add `--last 1`, or `--json` for
machines). It groups the log into boots, names each attempt's outcome, and
prints the hints below.

## How to read a boot in 30 seconds

1. `tail -5 server/logs/beacons.log` — a fresh `ROOTCHAN 31337 uid=0` means
   rooted and serving; **stop here**.
2. No fresh lines after a boot → the app never started (boot row gone / DLL
   broken / TV in standby — the remote power button is standby, not a boot)
   **or** the PC was unreachable (server on :80 must run as `pysrv.exe`,
   never `python.exe` — the firewall blocks the latter).
3. Fresh lines without `SUCCESS-R00T`/`ROOTCHAN` → run
   `python tools/beacons.py --last 1` and read the verdict + findings.
4. Cross-check with the TV-side marker (needs the browser lane or a shell):
   `cat /opt/usr/home/owner/share/root_boot.txt` — it has lines the PC never
   received if the server was down.

## Beacon dictionary

On the PC, lines are `<timestamp> DSHROOT tok=<hex> t=<n>s <payload line>`:
`tok=` (v41) is the deploy-rendered beacon token, and `t=` is TV kernel
uptime, which resets on a cold boot (that reset is how boots are delimited).
The on-TV marker keeps the `t=<n>s <payload line>` shape (no token).

### Lifecycle

| Line | Meaning | Action |
|---|---|---|
| `start uid=5001 pid=<p>` | AUL launched the app; fresh process | normal |
| `start uid=5001` (**no `pid=`**) | **test/forged noise**, not a launch: `Main()` always logs `pid=`, and the offline gateway tests used to write this shape with a fake `t=1s`. `beacons.py` drops it (and reports how many it ignored) so it cannot become a ghost boot. | ignore; real start lines carry `pid=` |
| `attempt=<n> (fast mode|long retry mode)` | attempt counter (`/tmp/.dsh_try`, resets at boot); 1–4 fast, 5+ long | normal |
| `kernel=<pa> init_task=<va>` | kernel image and `init_task` located | normal |
| `cand n=<k> offs=<hex,…>` | task-list offset candidates (one line since v39; used to be k separate `cand off=` lines) | normal (several) |
| `open <node> errno=<e> (absent), trying <next>` | the node does not exist here (ENOENT/ENODEV); v39.1 moves to the next | normal on a model with a different node numbering |
| `open <node> errno=<e> (busy, retrying this node)` | video40 is held by another opener; the payload **stays** on it | normal during a deploy (browser stub) — do NOT expect a node switch: only video40 serves the payload's reads |
| `open <node> still errno=<e> after <n>s` | the same wait, once per 30 s | a long hold; the payload keeps trying for the whole 120 s budget |
| `device <node> fd=<n>` | the node that actually opened | normal |
| `reopen <node> fd=<n>` | second open of the boot (after the base scan); `fd=-1` = still held | `-1`: the payload now exits early for a fresh process instead of burning rounds |
| `fast-exit attempt=<n>` | process exiting so AUL relaunches (fresh mmap = allocation re-roll) | normal, by design since v9 |
| `SUCCESS-R00T …` | cred patched, `uid=0` proven | done |
| `device closed` | the node is free for the browser path | normal after SUCCESS, and on every early exit since v39 |
| `ROOTCHAN 31337 uid=0 bind=<ip>` | command channel serving | done; `bind=0.0.0.0` = offline fallback (see BIND-FALLBACK) |
| `exception <Type>: <msg>` | CLR crash | read the type; browser lane (`tv_rootwatch.py`) still works |

### Hunt (finding the landmark)

| Line | Meaning | Action |
|---|---|---|
| `retry in <n>s` | pre-round wait (fast `{0,0,5000,5000}`, long longer) | normal |
| `round=<n> pre=<k>` | hunt round; `k` known old PHYRFORK tasks | normal |
| `tail: <comm,…>` | task-tail comm dump; `per/0` names are normal, even on success | normal |
| `child=<va> self=<va> pu=<uid\|unread>` | landmark child latched; `self=00000000` is normal (stale comm/pointer line) | normal |
| `fail no new PHYRFORK seen=<n> skip-orphan=<n> pu=<x>` | the new landmark never appeared | see `docs/OPEN-ISSUES.md` fifth pass; usually recovers next attempt |
| `fail round <n>` | attempt ended unrooted | expected on attempt 1 (below); attempt 2+ failing repeatedly → run beacons.py, check findings |

### Patch paths (in the order they run)

| Line | Meaning | Action |
|---|---|---|
| `self cred=<va> real=<va>` / `self-patch uid=<n>` | patched our own task's cred | `uid=0` = rooted |
| `direct-parent+<off>=<va> cred=<va>` | child→real_parent→cred read 5001 | the working path on nearly every boot |
| `direct-patch uid=0` | root confirmed after that patch | done |
| `direct-patch-fail …` | write did not stick (stale/cached) | scan fallback follows; watch `cred-scan` |
| `parent=<va> cred=<va>` / `parent-patch uid=<n>` | comm-scan path (slow lane) | fine if it ends in `uid=0` |
| `high-alloc parent=<va> cred=<w> real=<w> junk=<0\|1> fast-exit` | **v33 gate**: parent task or cred at/above `0xE0000000` — unreadable, wait cannot help | **normal, not an error**: the video40 read path returns garbage there even though `zoneinfo` puts `high_memory` at VA `0xF0400000` (the node's DMA window is the suspect — `docs/OPEN-ISSUES.md` item 2); a fresh process re-rolls the allocation into the readable range; expect the next attempt to root |
| `high-scan C=… P=… pp=… cp=… pc= hits= at= cred= cuid= cov= ms= verdict=…` | **v38 read-only probe** answering *why* the high half is unreadable (tasks are not page-aligned: `at=` is the TASK address, found by the comm pattern at any offset — NUL verified across the page edge — and validated against the children list linking `&child->sibling`, task+0x2F8 ↔ child+0x300, DWARF-confirmed) | `verdict=linear` (`pc=1`: the comm read at the translated parent address itself) → video40 returned wrong bytes for a frame it can address (read-path failure); `verdict=elsewhere` → the `va-0xA0000000` translation is the bug, and `cuid=5001` on `at=` would mean a locate-and-patch read path is possible; `cred-elsewhere` → an owner-ids cred was found in the sweep (the child's own fork-copy cred is excluded); it is **not** evidence about the high half, because `at=`/`cred=` are PHYSICAL while `C=`/`P=` are virtual — a linear hit on parent `0xe2df7300` reads `P=e2df7300 at=42df7300`, and `cuid=5001` on `verdict=linear` simply means the frame was readable; `comm-only`/`miss`/`cred-miss` → inconclusive, read `cov=`, the range ACTUALLY read (a miss is not evidence of absence) |
| `cred-scan ROOT\|miss patched=<n> total=<n>` | v28 content scan near the child's cred (budget 8/process) | `ROOT` = rooted via scan; `miss` = ran, ours still stale |
| `cred-scan skip anchor=<va> cuid=<u>` | scan gate closed (child cred page itself stale) | expected in the stale window |
| `direct-probe pr=<n> po=<off> …` | fifth-pass diagnostic on the stale path (silent on success). `cred=00000000` + `cuid=5001` = the v27 stale-own-pointer signature; `plain=`/`head=`/`map=`/`pva=` split pointer-stale from content-stale | informational; see `docs/OPEN-ISSUES.md` fifth pass for the decoder ring |

### Channel and housekeeping

| Line | Meaning | Action |
|---|---|---|
| `chan bind <ip> failed (…), using any` | no route to the PC at start; wildcard fallback | expected offline boots; allowlist still filters — keep the set off untrusted networks |
| `chan rebind <ip>` | TV address moved; listener followed | normal |
| `chan deny <ip>` | peer not in `rootchan.allow` (fails closed) | if it was you: update `share/rootchan.allow` |
| `chan fail <msg> (retrying in 5s)` | listener error; v39 retries instead of giving up | read msg; a transient bind heals without a reboot (the payload keeps trying) |
| `[timeout: killed after 120s]` (in a reply) | a runaway command was killed; channel survived | by design (the v12 pipe fix; v39 raised the cap from 15 s to cover deploy/uninstall) |
| `[output truncated at 1048576 bytes of <n>]` | `Run()` capped the reply (v39) | redirect big output to a file on the TV, or read it in slices |
| `autoupdate [system] … = Int32: 0` | auto-update re-asserted off | normal; anything else → set it by hand (AGENTS.md §1) |
| `physmap window at <va> slots=2048x8000` | alias-correct window reserved | normal |
| `physmap window unavailable / off: …`, `physmap fixed map failed …` | window fallback/teardown | stale reads likelier; a later AUL launch re-rolls the mapping |
| `fail open node after 120s=<-1> errno=<e>` | every physmap node was held for the whole retry | a browser stub or wedged process owns them; wait ~2 min or power-cycle; check `/dev/video*` |
| `fail no kernel image / no init_task / no task offsets` | memory scan found nothing this attempt | usually early-boot chaos, later attempt recovers; persistent on new firmware = re-measure constants (`docs/PORTABILITY.md`) |

## Boot shapes (what healthy and sick look like)

Healthy cold boot since v33 (the documented v37 boot):

```
start uid=5001 pid=…            attempt=1 (fast mode)
child=… self=00000000 pu=…      direct-probe … (maybe)
high-alloc parent=e… fast-exit  ← attempt 1: allocation lottery, BY DESIGN
start uid=5001 pid=…            attempt=2 (fast mode)
child=… pu=5001                 direct-parent+2f0=… cred=…
direct-patch uid=0              SUCCESS-R00T …
device closed                   ROOTCHAN 31337 uid=0 bind=<tv-ip>
```

Whole boot ≈ 35–40 s from power-on. Attempt-1 `SUCCESS` is a bonus, never a
requirement (trap 16). A `high-scan` line before `fast-exit` is the v38 probe
and changes nothing else.

Sick shapes: `fail open video40` (device held), `chan bind … failed` at every
boot (TV has no LAN when the channel starts — routing came up late), repeated
`fail round` on attempts 2–4 (run `beacons.py`; findings name the branch),
`exception` (CLR crash — browser lane still available).

No beacons at all after a boot: app never launched (boot row in
`.appsvc.db` gone, DLL broken, AUL did not fire) **or** the PC server was
down/wrong interpreter. The TV-side `root_boot.txt` marker splits that case.

## Tool errors

| Tool / message | Meaning | Next step |
|---|---|---|
| `root_shell: cannot connect … timed out / unreachable` | nobody answered; TV off/standby, payload down, **or this PC is off the TV's LAN / VPN eats the route** | the 3 hints printed with the error (beacons → LAN/VPN → video40); **never ping** — a VPN tunnel answers ICMP errors and Windows ping reports 0% loss (AGENTS.md trap 17) |
| `root_shell: … connection refused` | host answered, port closed: not rooted this boot, wrong host, or the app died | `python tools/beacons.py --last 1`; confirm the IP before deploying (deploy.sh's md5 gate is the backstop) |
| `root_shell: 31337 answered but never sent __END__` | foreign service on the port, or the channel died mid-reply | retry once; then beacons.log; the peer is dropped after 30 s silence |
| `run_root.py: command is N B; the stub limit is 508 B` | command too long for the stub's cmdbuf (v39 needs room for the NUL) | fetch a script: `run_root.py "curl -s http://<pc>/deploy.sh | sh" 45` |
| `run_root.py: [run] no status …` | stub died before answering (op 7 is effectively single-use) | `physmap.reset_stub()` (RSET) → reload `index.html` → re-root → retry |
| `kernel_root.py: skip … (not a cred)` | stale/foreign cred pointer on the walk | reload the page and re-root (fresh stub) |
| `kernel_root.py: ids = (0,0,…)` | cred already patched (root) or bogus | `id` via `run_root.py` to tell which |
| gateway: cached hello / nothing answers after a page load | wedged stub pairing | `python -c "import physmap; print(physmap.reset_stub())"`, then reload the page |
| server: `/logs/…` returns 404 | by design — logs are never served | read them on the PC |
| server: HTTP 413 on `/save` | POST body over the 1 MB cap | client bug; nothing on the TV |
| server console: `[pair] token announced (<hex>)` | the page announced its per-load stub pairing token (v40) | normal before every page load |
| server console: `[rpc] stub token mismatch (<a> != <b>) - ... refused` | a stub presented a different token than announced; usually a stale page | reload `index.html` so the stub carries the announced token |
| server console: `refused <ip>: unknown beacon token <hex>` | a forged (or stale-deploy) beacon was refused admission | expected for foreign peers; if it is your TV, redeploy so `rootchan.token` matches |
| server console: `<ip> sent no token - logged but NOT admitted` | a token-less beacon (legacy payload, or the payload cannot read `rootchan.token`) | logged to `beacons.log` anyway; check the token file's mode/label on the TV |

## Proof files (TV side)

| File | Meaning |
|---|---|
| `share/root_boot.txt` | every beacon this payload ever emitted, local copy |
| `share/root_proof.txt`, `/opt/usr/system/dsh_root_proof.txt` | written on SUCCESS with uid/pid/kernel/init_task |
| `share/rootchan.host`, `share/rootchan.allow`, `share/rootchan.token` | beacon target; allowlist (missing = fail closed); the v41 beacon token (chmod 644 — 0600 is unreadable by the uid-5001 payload) |
| `rootchan.token` mismatch symptoms | beacons arrive but the server console prints `refused ... unknown beacon token` or `sent no token - NOT admitted`: the payload cannot read the token file (check mode/label), or the server was restarted after a newer deploy render (the last two renders stay valid) |
