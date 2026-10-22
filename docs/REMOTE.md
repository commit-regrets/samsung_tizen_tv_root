# Remote control and hotkey remapping

**Status: investigation only (2026-10-22). Nothing here has been implemented or
tested on the TV yet.** It records what was found while looking at whether the
remote's dedicated app buttons (Netflix / Prime Video / Samsung TV Plus /
Disney+) can be repointed to another app.

## 1. Input stack on this TV

| Device | Node | Notes |
|---|---|---|
| `Smart Control` (BT remote) | `/dev/input/event3` | `kbd` handler, `root:input 0660` |
| `sdp-mcirb` | `/dev/input/event0` | IR receiver |
| `wt61p807 rc device` | `/dev/input/event1` | IR receiver |
| `wt61p807 panel key device` | `/dev/input/event2` | panel buttons |
| `detent_key_device` | `/dev/input/event4` | virtual |

Relevant userland:

- `/usr/bin/remote-server` — remote protocol/event service.
- `com.samsung.tv.virtual-remote` — virtual remote app.
- `/usr/bin/key-manager` (running as `key-man+`, pid ~2265) — key/hotkey
  routing service, `libkey-manager-*`, `libds-tizen-keyrouter`.
- `/usr/bin/tvctx-manager` — loads app-context rules from
  `/etc/tvctx-manager/appctx-config.json` + `/etc/tvctx-manager/launcher`.

## 2. How an app button becomes an app launch

The app buttons arrive as the standard Linux *app launch* keys
**`XF86App1`, `XF86App2`, `XF86App3`** (plus `XF86App1Long`/`2Long`/`3Long` for
long presses).

The stock `com.samsung.tv.hotkey-service` package
(`/opt/usr/apps/com.samsung.tv.hotkey-service`) declares the routing in its
manifest:

```xml
<app-context-rule>
  <source selector="key">XF86App1</source>
  <target args="press:XF86App1" request="launch"
          selector="app">com.samsung.tv.hotkey-service</target>
</app-context-rule>
<!-- same for XF86App2, XF86App3, and the *Long variants -->
```

So `tvctx-manager` turns the key into "launch the hotkey service with
`press:XF86AppN`", and the service itself decides **which appid** that key
launches. That table lives in the managed assembly
`bin/com.samsung.tv.hotkey_service.dll` (a dotnet-inhouse app, same loader lane
as the root payload) or in its embedded resources — not in a user-visible
setting.

## 3. Ways to remap

### A. Patch the hotkey service mapping (recommended)

1. Identify the key: press the button while reading `event3`, map the keycode
   to `XF86App1/2/3`.
2. Pull `bin/com.samsung.tv.hotkey_service.dll` to the PC over the root
   channel (base64 or a file-write helper).
3. Decompile it (`ilspycmd`, ILSpy) and find the key → appid table.
4. Change the appid for that key (e.g. Disney+ → your app), rebuild the DLL.
5. Back up the stock file as `hotkey_orig.dll`, deploy the patched one, restart
   the service (or reboot) and test.
6. Only then touch the other buttons / long-press rules.

Why this is clean: it changes the mapping, not the key routing, so every other
button keeps working. The dotnet-inhouse launch path does not verify the IL
signature (the same property that makes the root payload work).

### B. Edit the manifest app-context rule

Point `XF86AppN` straight at the app you want instead of the hotkey service.
The package is signed (`author-signature.xml`); the edit may be ignored or
break the package. Not recommended.

### C. evdev grab daemon

A root process does `EVIOCGRAB` on `/dev/input/event3`, launches your app when
it sees the target key, and forwards every other event through `uinput`.

Most general, but the most fragile: if the daemon dies or mishandles events
while holding the grab, the remote stops working. Needs a watchdog and a
fail-open path. Prefer A.

## 4. Identifying the key

`evtest` is not installed. Options:

- `cat /dev/input/event3 | hexdump -C` while pressing the button (busybox
  `hexdump`/`od`), then decode `struct input_event`:
  `timeval(8) + type(2) + code(2) + value(4)` on 32-bit; `type == 1` (EV_KEY),
  `value == 1` (press).
- or a tiny reader in the payload/app lane if `hexdump` is missing.
- Match the resulting keycode against the `XF86App*` names used by
  `key-manager`/`tvctx-manager`.

Permission note: `/dev/input/event3` is `root:input 0660`; the root channel can
read it directly.

## 5. Risks and caveats

- The hotkey package is signed; an OTA will restore the stock service.
- Long-press (`*Long`) rules are separate — remap them too if used.
- Keep the stock DLL backup (`hotkey_orig.dll`) and test one button first.
- Do not grab the only remote input device without a pass-through: a bug there
  makes the remote unresponsive until reboot.
- This is a *mapping* change, not a security boundary: it needs root already.

## 6. Next steps

1. Capture the Disney+ keycode from `event3`.
2. Pull and decompile `com.samsung.tv.hotkey_service.dll`; locate the table.
3. Patch one key, deploy with a backup, restart, test.
4. Document the exact diff and add it to the toolkit if it proves stable.
