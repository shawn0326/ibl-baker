# ibl-baker

A renderer-agnostic IBL asset compiler that bakes HDR environments into GPU-ready and portable texture assets, with a Rust core, CLI, and TypeScript loaders.

The CLI produces two output formats:

- **`.ktx2`** — GPU-ready cubemaps with BC6H compression and zstd supercompression, for direct engine and Web consumption.
- **`.ibla`** — a portable, renderer-agnostic archive with PNG-encoded payloads, for archival and offline workflows.

BRDF LUT is always emitted as a standalone `.png`.

## Documentation

| Document | Description |
| --- | --- |
| [packages/cli/README.md](packages/cli/README.md) | npm CLI installation, platform support and versioning |
| [docs/release.md](docs/release.md) | CI, release preparation, OIDC publishing and recovery |
| [`crates/ibl_cli/README.md`](crates/ibl_cli/README.md) | CLI usage, options, and output format details |
| [`docs/format-spec.md`](docs/format-spec.md) | `.ibla` binary format specification |
| [`crates/ibl_core/README.md`](crates/ibl_core/README.md) | Rust core library scope |
| [`crates/ktx2_writer/README.md`](crates/ktx2_writer/README.md) | Write-only KTX2 serializer scope |
| [`packages/ibla-loader/README.md`](packages/ibla-loader/README.md) | TypeScript `.ibla` parser API |
| [`packages/ktx2-loader/README.md`](packages/ktx2-loader/README.md) | Narrow TypeScript parser API for `ibl-baker` KTX2 cubemaps |
| [`packages/site/README.md`](packages/site/README.md) | Private GitHub Pages browser validation app |

## Status

The repository implements the bake pipeline across three layers:

- **Rust core** — baking, validation, `.ibla` read/write, and KTX2 export
- **CLI** — `ibl-baker bake` with `--output-format <ibla|ktx2|both>`, plus `validate`
- **TypeScript loaders** — parser-only `.ibla` reader (`@ibltools/ibla-loader`) and narrow KTX2 IBL reader (`@ibltools/ktx2-loader`)
- **Browser validation** — private drag-and-drop `packages/site` app for `.ibla` and `.ktx2` assets

## Scope

Current priorities:

- keep the `.ibla` container stable and well-specified
- keep KTX2 output aligned with the BC6H + zstd pipeline
- keep CLI behavior aligned with [`crates/ibl_cli/README.md`](crates/ibl_cli/README.md)
- keep the TypeScript loaders parser-only and scoped to their format contracts
- expand verification around bake outputs, loader parsing, and browser validation

## Workspace

The repository uses a Cargo workspace and a pnpm workspace at the repo root.

Common pnpm entry points:

```bash
pnpm install
pnpm run fixtures:refresh
pnpm run test:workspace
pnpm run test:js
pnpm run test:site
pnpm run dev:site
```

`pnpm install` also materializes the Cargo workspace dependencies through pnpm's
experimental Cargo integration. `Cargo.lock` and `pnpm-lock.yaml` remain separate;
Cargo continues to own Rust metadata, builds, tests and crates.io publishing. Run
`pnpm install` before invoking Cargo commands in a fresh checkout.

Manual browser validation runs through `packages/site`.
After starting `pnpm run dev:site`, open `http://127.0.0.1:4175/` and drop an `.ibla` or `.ktx2` file.
The hosted GitHub Pages entry is `https://shawn0326.github.io/ibl-baker/`.
The site does not load repository fixtures directly. The legacy `/ibla-viewer/` and
`/ktx2-viewer/` Pages paths redirect to the unified entry.

Out of scope for now:

- browser-side baking
- engine-specific runtime adapters
- WebAssembly bindings
