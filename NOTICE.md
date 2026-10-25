# Notices and provenance

* `hnswaudit/` is independent code written for this repository. It was written from (a) the public source of
  `chroma-core/hnswlib` (rev `e6db8c2`, `hnswalg.h`) and `nmslib/hnswlib` (rev `ca42672`), read to derive the on-disk layout and the
  search/traversal rules, and (b) the author's private design notes, which are not part of this repository (the resulting argument is written out in
  `SOUNDNESS.md`). No source text was copied. Those upstream projects are Apache-2.0; `chroma-core/chroma` is Apache-2.0; `amikos-tech/chromadb-ops` (read for comparison
  only, never run or copied) is MIT.
* **Code:** the original software (`hnswaudit/*.py`, `repro/`, `tests/`) is MIT licensed, see `LICENSE`.
* **Artifacts:** the synthetic snapshots in `snapshots/` and the raw engine outputs and sample report data in `evidence/` are not covered by the
  MIT licence; they are included for reproducible review.
* `snapshots/*` are Chroma 1.5.9 persistent stores created locally by the author's probe scripts from seeded random vectors (no third-party data). They are
  unmodified copies (sha256 recorded in `snapshots/*.src.sha256`). `evidence/engine/` holds the raw Chroma engine outputs; `evidence/ENGINE-PROBE.md` summarises them.
* `chroma.sqlite3` inside snapshots is read only with `mode=ro&immutable=1`, and only ever on copies. Never audit a live store.
* The Chroma issue (#7758), PRs (#7845, #7768, hnswlib #50) and nmslib issue (#522) are referenced as public context only; nothing was posted
  to any of them.

* The two unmodified TeX Gyre Heros Regular/Bold OpenType files distributed under hnswaudit/fonts/ are copyright the TeX Gyre authors and licensed under the GUST Font License (full text in hnswaudit/fonts/GUST-FONT-LICENSE.txt). They are embedded into generated, standalone offline HTML reports. The fonts keep their own terms, distinct from the MIT licence of the code: the GUST Font License, version 1.0 of 22 June 2009 (`hnswaudit/fonts/GUST-FONT-LICENSE.txt`), which grants distribution under the LaTeX Project Public License 1.3c or later (`hnswaudit/fonts/LPPL-1.3c.txt`). The fonts are distributed unmodified under their original names, with the copyright notice embedded in them (2006, 2009, B. Jackowski and J.M. Nowacki on behalf of the TeX users groups).
