# ibl-baker

A renderer-agnostic IBL asset compiler that bakes HDR environments into GPU-ready and portable texture assets, with a Rust core, CLI, and a parser-only TypeScript loader.

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
| [`packages/loader/README.md`](packages/loader/README.md) | TypeScript `.ibla` parser API |

## Status

The repository implements the bake pipeline across three layers:

- **Rust core** — baking, validation, `.ibla` read/write, and KTX2 export
- **CLI** — `ibl-baker bake` with `--output-format <ibla|ktx2|both>`, plus `validate`
- **TypeScript loader** — parser-only `.ibla` reader (`@ibltools/loader`)
- **Browser validation** — private `packages/e2e-loader` app for fixture inspection

## Scope

Current priorities:

- keep the `.ibla` container stable and well-specified
- keep KTX2 output aligned with the BC6H + zstd pipeline
- keep CLI behavior aligned with [`crates/ibl_cli/README.md`](crates/ibl_cli/README.md)
- keep the TypeScript loader parser-only
- expand verification around bake outputs, loader parsing, and browser validation

## Workspace

The repository uses a Cargo workspace and an npm workspace at the repo root.

Common npm entry points:

```bash
npm install
npm run fixtures:refresh
npm run test:js
npm run test:e2e-loader
npm run dev:e2e-loader
```

Manual browser validation runs through the local Vite service in `packages/e2e-loader`.
After starting `npm run dev:e2e-loader`, open:

- `http://127.0.0.1:4173/?fixture=royal_esplanade_1k&asset=specular`
- `http://127.0.0.1:4173/?fixture=grand_canyon_c&asset=irradiance`

Out of scope for now:

- browser-side baking
- engine-specific runtime adapters
- WebAssembly bindings
