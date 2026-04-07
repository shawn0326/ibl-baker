# ibl-baker

A renderer-agnostic IBL asset compiler that bakes HDR environments into portable `.ibla` texture payloads with a Rust core, CLI, a parser-only TypeScript loader, and a neutral browser validation app.

## Documentation

- [`crates/ibl_core/README.md`](crates/ibl_core/README.md)
- [`crates/ibl_cli/README.md`](crates/ibl_cli/README.md)
- [`packages/loader/README.md`](packages/loader/README.md)
- [`docs/format-spec.md`](docs/format-spec.md)

## Status

The repository is currently implementing the v1 pipeline across three layers:

- Rust baking, validation, and `.ibla` read/write
- a parser-only TypeScript loader in `packages/loader`
- a private browser-side validation app in `packages/e2e-loader`

## Scope

The v1 goal is a stable, portable asset format with a small number of explicitly scoped integration layers.
The main production path remains HDR IBL baking, while `srgb` and `linear`
encoding variants keep the container semantics consistent for related payload types.

Current priorities:

- keep the `.ibla` container stable
- keep CLI behavior aligned with `crates/ibl_cli/README.md`
- keep the TypeScript loader parser-only in v1
- keep the public JS surface limited to the parser package
- expand verification around real bake outputs, loader parsing, and neutral browser validation

## Workspace

The repository uses:

- a Cargo workspace at the repo root for Rust crates
- an npm workspace at the repo root for JavaScript packages

Common npm entry points from the repo root:

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
- alternative encodings and containers in the initial milestone
