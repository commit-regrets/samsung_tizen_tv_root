# Control Center prototype

A static Tizen-friendly home screen. This is the first piece of the
`control-center/` layer; it is **not** installed on the TV and does not change
`home_appid` yet.

## Preview

From the repo root:

```powershell
$pysrv = Join-Path $env:LOCALAPPDATA "Python\pythoncore-3.14-64\pysrv.exe"
& $pysrv -m http.server 8080 --directory control-center\web
```

Then open on the TV browser:

```text
http://<PC-IP>:8080/
http://<PC-IP>:8080/?library=1
```

The second URL opens the **All Apps** overlay directly for preview.

Use the remote arrows to move and **OK** to activate a tile. The TV browser
receives those as normal browser keys; no remote daemon is needed for this
prototype.

## Apps and editing

The dock is driven by [`web/apps.json`](web/apps.json). Edit it, reload the
page, and the tiles change without a rebuild. Each entry is:

```json
{ "appId": "IkWsFHtOY9.Stremio", "label": "Stremio", "glyph": "S", "color": "#7c3aed", "icon": "icons/stremio.png" }
```

`icon` is optional; a missing or broken image falls back to the coloured glyph.
`"dock": false` keeps an app in the **All Apps** library without putting it in
the dock. An entry with `"action": "library"` is the **All Apps** button.

## Dynamic app list

The dock is the favourites list. **All Apps** opens a full-screen grid.

On the TV, when the page is packaged or loaded with `?installed=1`, the CC calls
`tizen.application.getAppsInfo()` and rebuilds **both** the library and the dock
from what is actually installed. That is the production path:

- labels come from the app's installed name;
- icons come from `iconPath`;
- install/uninstall is reflected the next time the CC loads;
- known favourites keep their curated order and labels.

The browser preview cannot call that API, so it uses `apps.json` and the
locally extracted icons.

## Icons

Real icons were extracted from the TV's installed apps into `web/icons/` for
YouTube, Netflix, Stremio, Spotify and Apps. Prime Video, Internet, Samsung TV
Plus and Settings have no suitable standalone icon file in their packages, so
they keep the glyph fallback.

The PNGs are **local-only and ignored by git** (they are app trademarks, not
redistributable). A packaged Tizen app should use the runtime `iconPath` from
`tizen.application.getAppsInfo()` instead of bundling them.

Installed on this TV today: YouTube, Netflix, Prime Video, Stremio, Spotify,
Internet, Samsung TV Plus, Apps and Settings. `Inputs` was removed from the
default dock; source switching is not solved yet, so it was only a placeholder.

When the page is packaged as a Tizen app (or opened with `?installed=1`), it
builds the library and dock from `tizen.application.getAppsInfo()`, so an
**uninstalled app disappears automatically** and a new install appears in
**All Apps**. The browser preview cannot reliably query installed apps; after
uninstalling something, remove it from `apps.json` so the preview matches the TV.

## What it is

- 1920×1080 layout, dark glass/dock styling inspired by CleanYourTV's
  Glass/Cinematic themes.
- Clock, date, favourites dock, focus ring, `←`/`→` navigation, `OK`.
- **All Apps** overlay with a five-column grid; `↑`/`↓`/`←`/`→`, `OK`, `Back`
  to close.
- The brand strip and the “Use ← →” hint from the first preview are removed.
- No external fonts, images, scripts or network requests.
- All app data is local; no analytics.

## Not wired yet

- Launching apps (`app_launcher` bridge).
- The CC as a registered Tizen app.
- Home `63` / Back `1` mapping (the `remote/` daemon).
- Boot persistence / `home_appid`.

## Next

1. Connect the launch bridge (page writes an app ID; a small daemon runs
   `app_launcher`).
2. Register the page as a Tizen app and launch it manually.
3. Map Home/Back to the CC with `remote/`.
4. Set `home_appid` to the CC, keeping `com.samsung.tv.csfs` as rollback.
