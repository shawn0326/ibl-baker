# ibl-baker

A renderer-agnostic IBL asset compiler that bakes HDR environments into GPU-ready and portable texture assets, with a Rust core, CLI, and TypeScript loaders.

The CLI produces two output formats:

- **`.ktx2`** — GPU-ready cubemaps with BC6H compression and zstd supercompression, for direct engine and Web consumption.
- **`.ibla`** — a portable, renderer-agnostic archive with PNG-encoded payloads, for archival and offline workflows.

BRDF LUT is always emitted as a standalone `.png`.

## Documentation

| Document | Description |
| --- | --- |
| [`crates/ibl_cli/README.md`](crates/ibl_cli/README.md) | CLI usage, options, and output format details |
| [`docs/format-spec.md`](docs/format-spec.md) | `.ibla` binary format specification |
| [`crates/ibl_core/README.md`](crates/ibl_core/README.md) | Rust core library scope |
| [`crates/ktx2_writer/README.md`](crates/ktx2_writer/README.md) | Write-only KTX2 serializer scope |
| [`packages/ibla-loader/README.md`](packages/ibla-loader/README.md) | TypeScript `.ibla` parser API |
| [`packages/ktx2-loader/README.md`](packages/ktx2-loader/README.md) | Narrow TypeScript parser API for `ibl-baker` KTX2 cubemaps |

## Status

The repository implements the bake pipeline across three layers:

- **Rust core** — baking, validation, `.ibla` read/write, and KTX2 export
- **CLI** — `ibl-baker bake` with `--output-format <ibla|ktx2|both>`, plus `validate`
- **TypeScript loaders** — parser-only `.ibla` reader (`@ibltools/ibla-loader`) and narrow KTX2 IBL reader (`@ibltools/ktx2-loader`)
- **Browser validation** — private drag-and-drop `packages/ibla-viewer` and `packages/ktx2-viewer` apps

## Scope

Current priorities:

- keep the `.ibla` container stable and well-specified
- keep KTX2 output aligned with the BC6H + zstd pipeline
- keep CLI behavior aligned with [`crates/ibl_cli/README.md`](crates/ibl_cli/README.md)
- keep the TypeScript loaders parser-only and scoped to their format contracts
- expand verification around bake outputs, loader parsing, and browser validation

## Workspace

The repository uses a Cargo workspace and an npm workspace at the repo root.

Common npm entry points:

```bash
npm install
npm run fixtures:refresh
npm run test:js
npm run test:ibla-viewer
npm run test:ktx2-viewer
npm run dev:ibla-viewer
npm run dev:ktx2-viewer
```

Manual KTX2 validation runs through `packages/ktx2-viewer`.
After starting `npm run dev:ktx2-viewer`, open `http://127.0.0.1:4174/` and drop a `.ktx2` file.
The hosted GitHub Pages entry is `https://shawn0326.github.io/ibl-baker/ktx2-viewer/`.
The viewer does not load repository fixtures directly.

Manual IBLA validation runs through `packages/ibla-viewer`.
After starting `npm run dev:ibla-viewer`, open `http://127.0.0.1:4175/` and drop an `.ibla` file.
The hosted GitHub Pages entry is `https://shawn0326.github.io/ibl-baker/ibla-viewer/`.
The viewer uses the same linear to Reinhard to gamma display path as the KTX2 viewer.

Out of scope for now:

- browser-side baking
- engine-specific runtime adapters
- WebAssembly bindings
