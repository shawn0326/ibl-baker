# ibl_core

`ibl_core` is the renderer-agnostic Rust core for the `ibl-baker` workspace.
It owns HDR/EXR input handling, bake pipeline execution, `.ibla` read/write, and validation logic.

## Scope

The crate is responsible for:

- source image loading for HDR, EXR, and supported LDR inputs
- latlong-to-cubemap conversion
- specular prefilter generation
- irradiance generation
- BRDF LUT generation
- mip chain generation
- `.ibla` container read/write and validation

It stays independent from renderer-specific runtime upload paths.

## Relationship To Other Packages

- `crates/ibl_cli` exposes the public command-line workflow on top of this crate
- `packages/loader` is the parser-only TypeScript reader for emitted `.ibla` files
- `packages/e2e-loader` is the private browser-side validation app used to inspect emitted fixtures

The shared `.ibla` container contract is defined in the repository format specification:
<https://github.com/shawn0326/ibl-baker/blob/main/docs/format-spec.md>
