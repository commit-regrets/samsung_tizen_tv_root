# Kernel analysis — three artifacts, and which to trust

Three kernel artifacts exist in this workflow; keep them apart everywhere
below. All dumps are local-only (git-ignored; Samsung-proprietary binaries);
the scripts that produce them are tracked and model-generic.

1. **OTA extraction** — from the downloaded firmware package (e.g.
   `ghidra/Image_5.4.249.bin`, the Dec 29 2025 build). Static reference.
2. **Partition dump** — the flashed kernel partition via
   `tools/dump_kernel_chunked.py` (e.g. `ghidra/Image_flash_partition.bin`).
   The pristine bytes as flashed; same build the TV boots, plus padding.
3. **RAM dump** — the running kernel via `tools/dump_kernel_ram.py` (e.g.
   `ghidra/Image_TV_running_full.bin`). Authoritative for any offset the
   payload uses.

## 1. Before rooting — the OTA package

Download your model's firmware image from Samsung
([`REFERENCE-MATERIALS.md`](REFERENCE-MATERIALS.md) lists where) and extract
the kernel from it:

1. unpack the update image (the downloaded zip's layout: a `uImage`, a
   device-tree blob, rootfs images, ... — exact names vary per model)
2. strip the 64-byte u-boot header off the `uImage` to get the raw ARM kernel
   `Image`:

   ```
   dd if=uImage of=Image.bin bs=64 skip=1
   ```

This is a static reference build — good for reading the code (`.text`,
`.rodata`, the `__ksymtab` export tables — this kernel has **no kallsyms**,
see §3), but **not guaranteed to match what the TV runs**:

- Samsung ships newer OTA builds than whatever package you happened to
  download. Compare the `Linux version ... #1 SMP PREEMPT <date>` banner
  (findable with a strings search in the `Image`) against
  `cat /proc/version` on the TV — build host and timestamp differ between
  builds even at the same kernel version.
- The measured example in this project: the OTA package carried a
  Dec 29 2025 build (`abuild@A0609LHG`) while the TV ran a Feb 18 2026 build
  (`abuild@A1305DKG`) — same `5.4.249`, different binary.

## 2. After rooting — the build the TV actually executes

Two read-only extractors, both regenerate-able on demand:

### Partition dump — `tools/dump_kernel_chunked.py`

Procedure (not yet run-to-completion with a recorded md5 on this unit — the
acceptance gate below is what makes a run trustworthy): find the kernel
partition from `/sys/block/mmcblk0/mmcblk0p*/uevent` (this unit's expected
layout: `mmcblk0p5`, A/B-mirrored in `p6`), then pull it over the 31337 root
channel in 384 KiB chunks (the payload caps a single reply at ~1 MiB, so
384 KiB raw ≈ 512 KiB base64 fits). The script skips the first 1 MiB of the
partition (assumed signed header) and dumps a fixed 12 MiB window
(24,576 sectors), verifying each chunk's length and the whole region against
the TV's own md5 read of the same range — `MATCH` renames
`<out>.partial` into place; `MISMATCH` exits non-zero. That TV-side md5
comparison is the only acceptance signal a partition dump has.

Mind the artifact sizes: the window is always 12 MiB — the kernel Image
itself is smaller (the OTA extraction used for the symbol work,
`ghidra/Image_5.4.249.bin`, is 10,257,408 bytes = `0x9C8400`), so a
partition dump carries trailing padding past the image end. It is a
DIFFERENT artifact from the OTA extraction: same flashed build, different
size and provenance.

### RAM — `tools/dump_kernel_ram.py`

Reads the kernel out of physical memory (`0x20008000`, length `0xA20000` =
entry through `.bss` end) through the physmap RPC. Requires the browser stub
to be alive — run `python tools/physmap.py verify` first; if the TV was in
standby the page must be reopened (the gateway logs `waiting for TV` forever
otherwise, and reads block on page 1).

All reads stay below `0x46000000` (reads past that wedge the stub — the
video40/physmap read-band note in `AGENTS.md` §2 and trap 5 in §8; trap 9 in
§8 is the unrelated `/mnt/systemrw` brick risk). The wrapper is read-only;
nothing on the TV is written.

Result: the kernel **as executed**, including boot-time patching.

## Trust the RAM dump, not the OTA extraction, for shellcode offsets

Measured on this unit, comparing **in VA space**: the OTA extraction
(`Image_5.4.249.bin`, Dec 29 2025 build) against the RAM dump
(`Image_TV_running_full.bin`, Feb 18 2026 build). Both files start at the
kernel entry, so file offset = VA − `0xC0008000` for each. Earlier revisions
of this section compared raw file offsets from mismatched dump bases and
reported phantom ~1 MiB "shifts"; and an older `init_task.cred` line
compared a cred VALUE (`0xc095ce04`) against an ADDRESS (`0xc0957180`) —
both numbers are RAM-truth, for two different symbols.
The real per-section deltas, OTA extraction → RAM (commit_creds and
init_task from the two `__ksymtab` tables, §3; the init-cred object address
from `init_task.cred` read in each image):

- `.text`: essentially unchanged (commit_creds `0xc0050c14` → `0xc0050b5c`,
  −0xB8)
- `.rodata`: +0x10000 (version banner `0xc0768098` → `0xc0778098`)
- `.data`: init_task `0xc0945180` → `0xC0957180` = +0x12000 — exactly
  `DATA_SHIFT` in `kernel_root.py` / `physmap.py`. But the shift is NOT
  uniform across `.data`: the init-cred object moved `0xc094ae44` →
  `0xc095ce04` = +0x11FC0 (−0x40 vs DATA_SHIFT). Individual symbols drift
  by small build-specific amounts inside the section, so only per-symbol
  measurement (here: from the RAM ksymtab / init_task) is authoritative —
  `DATA_SHIFT` is the init_task anchor, not a section-wide constant.

These are build differences (the OTA extraction ships the Dec 29 2025
build; the TV ran the Feb 18 2026 build), not a boot relocation.

Constants for the physmap/cred-patch stages must therefore be measured from
RAM (the physmap stub's own `verify`/`analyze_init_task` output, or a RAM
dump loaded into a static analyser at base `0xC0008000`). The OTA
extraction remains the reference for reading code. Stage-by-stage
constants: [`EXPLOIT.md`](EXPLOIT.md).

## 3. Kernel symbols for Ghidra — `__ksymtab`, not kallsyms

**No kallsyms.** A full-image search for both layouts (absolute
`kallsyms_addresses` and base-relative `kallsyms_offsets` + `relative_base`,
plus the `token_table`/`token_index` signature) found nothing real on either
build — only trivial 0..255 u16 tables. (This is why the pid-hash/IDR
locators in AGENTS.md are blocked.) Symbol names live in the **module export
table** instead:

- entries are 12 bytes: `{u32 value (absolute kernel VA), u32 name_ptr,
  u32 namespace_ptr}` — the 5.4 `struct kernel_symbol`; 0 in the third word
  means NO namespace. CRCs are NOT in this table: with `CONFIG_MODVERSIONS`
  they live in a separate `__kcrctab` array, and the all-zero third words
  here say nothing about MODVERSIONS being on or off. Every one of the
  9,118 entries on this build has namespace 0 (verified), so a
  `(VA, VA, 0)` scan is complete here — but on a build with namespaced
  exports that filter would silently skip them: accept a third word that
  decodes to a short identifier string as well.
- symbol values may point into `.bss` BEYOND the file end (max here
  `0xc0ac3ef4` vs file end `0xC0A28000`) — do not tighten scan bounds to
  the image size, or `.bss`-resident exports get dropped.
- multiple contiguous arrays (`__ksymtab` + `__ksymtab_gpl`), each
  **name-sorted** (one unsorted pair expected at the array boundary);
  `name_ptr` points into `__ksymtab_strings` with tail-shared strings
- parse: scan for `(VA, VA, 0)` triples at stride 12, group runs ≥ 50
  entries, decode each name from `name_ptr` − image base; validate by
  uniqueness (kernel exports are unique), sortedness, and a known-symbol
  anchor (`init_task` must equal the physmap-verified address)

Recovered: **9,118 exports** from the RAM dump, **9,114** from the OTA
extraction — zero name conflicts — including the whole credential family
(`commit_creds`, `prepare_kernel_cred`, `prepare_creds`, `override_creds`,
`revert_creds`) and `init_task`. `init_cred` is **not** an export (no such
string in either image): its address is the value of `init_task.cred`
(`0xc095ce04` RAM / `0xc094ae44` OTA extraction), read from the task struct,
not from a symbol table.

Parsed vs applied: an earlier flash pass parsed only 8,328 symbols (a
stricter scan's undercount, later conflated with the applied-label count) and
the first Ghidra program carried that set; the corrected 9,114-symbol table is
what the current `Image_5.4.249_v8.bin` program carries. When quoting a count,
say which.

### The accepted RAM dump (authoritative, 2026-11-04)

`ghidra/Image_TV_running_full.bin` — 10,616,832 bytes (0xA20000), md5
`5c2b28b42283e8b6fb7a82cadc3cba63`, physical `0x20008000..0x20A28000`
(VA `0xC0008000..0xC0A28000`), captured with `tools/dump_kernel_ram.py`
(read-only; every read below `0x46000000`; nothing on the TV written).
The md5 pins THIS capture; a re-dump will not match it (runtime regions —
allocations, jiffies, logs — vary between boots) and that is fine: the gates
below, not the md5, decide whether a capture is usable. Acceptance gates,
all mandatory before use:

1. exact size (`0xA20000`)
2. first 8 bytes `ee4400eb 00900fe1` (kernel entry signature)
3. ksymtab `init_task == 0xC0957180` (the physmap-verified live value)
4. runtime markers present: `comm` at init_task+0x400 reads `swapper/0`
   (a dump showing the static `swapper` is NOT from the booted kernel)

An earlier pair of captures (the "trimmed" and 12 MB files) FAILED the
spirit of these checks and was deleted on 2026-11-04: neither starts at the
kernel entry (both begin mid-code at VA `0xC0107FC0` of some earlier capture),
neither matches the verified capture (the trimmed file agrees on ~11.6% of
overlapping bytes and shows the static `swapper` comm), and their provenance
could not be established. They are re-capturable at any time via
`tools/dump_kernel_chunked.py` (flash) or `tools/dump_kernel_ram.py` (RAM) —
if you find similar stray files, do not analyse them; re-dump with the gates.

Ghidra program-name note: the raw dump is `Image_TV_running_full.bin`, but
`/import_file` names the program after the file **basename**, so the applied
workflow wraps the dump in a minimal ELF named `Image_TV_full.bin` — the
Ghidra program is `Image_TV_full.bin` while the on-disk dump keeps its full
name.

### Ghidra workflow (MCPTest project, ghidra-mcp fork on 127.0.0.1:8089)

- The import endpoint keys the program name off the file **basename** and
  ignores load-address parameters, so wrap the dump in a minimal ELF32
  (one `PT_LOAD`, `p_vaddr = 0xC0008000`) and `GET
  /import_file?file_path=...` — Ghidra's ELF loader then lands the content at
  the true VAs. `POST /import_file` is broken (always "file_path is
  required").
- Auto-analysis runs at import/open; `/run_analysis` is a **no-op** (14 ms).
- Apply symbols over the REST API: `/rename_function`
  (`{"program":..., "function_address":"0x...", "new_name":...}`) per
  address, falling back to bulk `/create_labels` for data symbols; with more
  than one program open, **every** call needs the `program` field.
  `/rename_functions` has no bulk form — ~27 min per 9.1k symbols.
  `/run_script_inline` exists but is disabled unless the Ghidra process env
  has `GHIDRA_MCP_ALLOW_SCRIPTS=1`; everything here was done REST-only.
- Verify by name (`/get_functions {"program":..., "name":"commit_creds"}`),
  prove data labels by re-submitting them (idempotent `labels_skipped=1`),
  then `POST /save_program {"program":...}` — unsaved symbol work dies with
  the process.
- Language variant: the ELF-wrapper import lands `ARM:LE:32:v8`; a raw-binary
  import (the first GUI import of the OTA file) may land `v5t`, which
  mis-decodes `movw`/`movt` and Thumb-2. Keep every program on the same
  variant — the OTA-extraction program was re-imported as
  `Image_5.4.249_v8.bin` for exactly that reason; the old v5t import was
  deleted from the project on 2026-11-04, leaving `Image_TV_full.bin` (RAM)
  and `Image_5.4.249_v8.bin` (OTA extraction).

Result on this unit: in `Image_TV_full.bin` (RAM), `commit_creds`
0xc0050b5c (788 B), `prepare_kernel_cred` 0xc0050e70 (524 B) and `init_task`
0xC0957180 resolve by name; an `init_cred` label was added by hand at
`0xc095ce04` (the value of `init_task.cred` — not an export, so it never
comes from the symbol table). The OTA-extraction program
`Image_5.4.249_v8.bin` carries all 9,114 exports as labels.
For the next model/firmware: dump → gates 1-4 → ksymtab parse → import →
apply; the only hardware step is the dump.
