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
- **Samsung / Tizen** are trademarks of Samsung Electronics. This project is
  unofficial, not affiliated with or endorsed by Samsung.

Everything else (task-list walk, cred patch, boot payload, deployment tooling,
documentation) is original work by the repository author.
