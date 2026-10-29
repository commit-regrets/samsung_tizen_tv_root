# Third-party notices

Parts of this toolkit are derived from or build on public work:

- **Browser RCE chain** (`server/payloads/browser_payload.js`,
  `server/lib/wasm_builder.js`, `server/index.html`): derived from the public
  `samsung-smarttv-tizen-9-chromium-120-v8-rce` project by hdbreaker
  (CVE-2024-2887 WasmGC chain for Tizen 9 / Chromium 120). The upstream
  repository did not ship a LICENSE file at the time of writing; these files
  are included for reproducibility and remain the work of their authors.
  Attribute and link to the upstream project if you redistribute them.
- **V4L2 physmap technique**: the `/dev/video40` mapping primitive and the
  `physrpc` stub layout build on the same research.
- **Debloat package classification** (`debloat/third_party/vetro/`):
  `app-catalog.js` and `app-facts.js` are vendored from Vetro 0.2.3, MIT,
  copyright (c) 2026 Vetro contributors — full text in
  [`debloat/third_party/vetro/LICENSE`](debloat/third_party/vetro/LICENSE).
  `app-facts.js` is generated data derived from a firmware package dump;
  `debloat/models/qnx1d/` is this project's own classification of the
  QNX1D registry.
- **Samsung / Tizen** are trademarks of Samsung Electronics. This project is
  unofficial, not affiliated with or endorsed by Samsung.

Everything else (task-list walk, cred patch, boot payload, deployment tooling,
debloat lists and scripts, documentation) is original work by the repository
author.

## License scope

The MIT license in `LICENSE` covers the original work only. It does **not**
relicense the third-party files listed above; the browser chain remains under
whatever terms its authors provide (upstream had no LICENSE file at the time of
writing) and the Vetro files remain MIT. If you redistribute this repository,
keep this notice and the upstream attributions intact.
