# Publishing this repository

This tree is **research code that owns the TV it runs on**. Before making a copy
public, run the gate and reset the history — the working tree and the git
history fail different checks.

## 1. Gate the tree

```sh
python tools/test_all.py                      # every offline layer, incl. docs gates
python tools/sanitize_for_public.py --check   # tree is clean of known + tok= tokens
python tools/embed_physrpc.py --check         # page == blob
python tools/build_physrpc.py --check-embedded # blob == physrpc.S
python tools/update_state.py --check          # AGENTS state row == artifacts
```

`--check` covers the known identifiers, the LAN/Wi-Fi/VPN prefixes, device
identity, and any `tok=<8 hex>` / `"beacon_token": "<8 hex>"` value. A fresh
deploy rotates the beacon token; if the docs are updated with the new value,
`--check` fails until it is placeholdered (or `tools/sanitize_for_public.py`
copy mode rewrites it). `tok=deadbeef` is the documented forged-token example
and is allowed.

## 2. Reset the history — this is the actual blocker

An earlier tree was deliberately published clean, but the **commit history**
still contains the real TV/PC addresses, per-deploy tokens, the machine path and
a few commit messages with those values (`git log -S '<TV_IP>'`). A
public push of `main` would publish all of it.

Safest: publish a fresh single commit and keep the private history local.

```sh
# on a clean, gated tree, with the private main still local
git checkout --orphan public
git add -A
git commit -m "Initial public release"
# create an EMPTY repo at the public remote, then:
git push -f origin public:main
```

Do not push the private `main` branch to the public remote. If the commit
history is wanted publicly, it must be rewritten with `git filter-repo`
(replace-text for blobs **and** a message callback for commit messages, then
re-run every gate) and force-pushed to a new repo; that is more work and is
easy to get wrong.

Remove the local public branch afterwards if it is no longer needed:

```sh
git checkout main
git branch -D public
```

## 3. What is intentionally in the tree

- **`server/payload.dll`** — the served artifact; reproducible from
  `payload/Program.cs` (hash/size in the AGENTS state row).
- **`tools/physrpc_shellcode.bin`** — the assembled stub, committed so the page
  can be re-embedded without keystone/capstone.
- **Compiled address fallbacks** — TEST-NET placeholders (`192.0.2.1`); the page
  patches IP and port at runtime and aborts when served by hostname.
- **Per-deploy credentials** — never. They are written on the TV by
  `deploy.sh` and must not appear in docs, state or history.

## 4. What is intentionally not

`server/logs/`, `payload/out/`, `.zcode/`, `docs/codreview.md`, `*.pem`, `*.key`
and editor/OS junk are ignored (`.gitignore` is the source of truth). Check
`git status --short` is empty and `git ls-files | grep -E 'logs/|\.zcode|codreview'`
prints nothing before publishing.

## 5. Legal / attribution

`LICENSE` is MIT for the original work. The browser RCE chain and the V4L2
physmap technique derive from public research; the upstream project shipped no
LICENSE, so those files are **not** relicensed by the MIT file — see
`NOTICE.md` before redistributing, and keep the attribution.

## 6. Safety

The channel is a LAN root backdoor by design (`SECURITY.md`). Do not ship
`rootchan.allow` contents, do not publish while the TV is reachable from an
untrusted network, and rotate the beacon token before a release if the old one
was ever in a public tree.
