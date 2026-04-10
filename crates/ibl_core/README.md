# ibl_core

`ibl_core` is the renderer-agnostic Rust core for the `ibl-baker` workspace.
It owns HDR/EXR input handling, bake pipeline execution, output encoding, and validation logic.

## Scope

The crate is responsible for:

- environment source loading for latlong HDR/EXR/LDR inputs and 6-face cubemap sets
- latlong-to-cubemap conversion and cubemap-to-cubemap resampling
- specular prefilter generation
- irradiance generation
- BRDF LUT generation
- mip chain generation
- `.ibla` container read/write and validation
- KTX2 cubemap export (BC6H + zstd, via the `ktx2_writer` crate)

It stays independent from renderer-specific runtime upload paths.

## Relationship To Other Packages

- `crates/ibl_cli` exposes the public command-line workflow on top of this crate.
  See [`crates/ibl_cli/README.md`](../ibl_cli/README.md) for CLI options and output format details.
- `crates/ktx2_writer` is the write-only KTX2 serializer used internally for KTX2 output.
- `packages/loader` is the parser-only TypeScript reader for `.ibla` files.
- `packages/ktx2-loader` is the narrow TypeScript reader for `ibl-baker` KTX2 cubemap files.

The `.ibla` binary format is defined in [`docs/format-spec.md`](../../docs/format-spec.md).
