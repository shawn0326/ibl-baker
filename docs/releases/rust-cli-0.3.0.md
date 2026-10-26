# Rust/CLI 0.3.0

Date: 2026-10-26

The coordinated `ktx2_writer`, `ibl_core` and `ibl_cli` release improves cubemap
filtering and bake efficiency while preserving IBLA v1 and BC6H UFLOAT + zstd
KTX2. It includes the changes since Rust/CLI 0.2.3.

- Add `--specular-min-size <auto|positive integer>`. `auto` resolves to one and
  retains the complete chain. Explicit larger minima freshly bake the retained
  levels across the full perceptual roughness range, using natural integer
  halving and at least two levels when the base size exceeds one.
- Add opaque `BakedCubemap` and `LoadedEnvironment` APIs for independent format
  encoding and decoded-input reuse. Existing convenience functions remain.
- Share a cubemap bake between IBLA and KTX2 for `--output-format both`, decode
  the input once across selected targets, and transfer base float buffers rather
  than copying them. Prepare source LOD and mip interpolation data once per pass.
  Per-format clipping reports and partial-success behavior remain independent.
- Sample cubemap source mips seamlessly across face edges and corners. Cover the
  complete source footprint at odd dimensions. Retain box source mips, the
  quadratic sample budget and the existing source-footprint formula.
- Preserve positive sample requests below eight; zero uses one sample. Reject
  mip chains exceeding the natural limit and invalid level dimensions.
- Clamp finite out-of-range output RGB and report affected pixels. CLI warnings
  are written to stderr only after successful output writes; successful jobs
  still exit zero. Reject non-finite source RGB before filtering.
- Fill 1x1 BC6H blocks uniformly with their valid texel, avoiding artificial
  black padding. Other partial-block padding is unchanged.

## Migration

Complete Rust `BakeOptions` literals must add `specular_min_size: None`.
Literals using `..Default::default()` need no change. This source compatibility
change is why the coordinated Rust group advances to 0.3.0.

Consumers use the actual supplied mip count, upload every baked level, disable
automatic mip generation, and sample with
`LOD = clamp(perceptualRoughness, 0, 1) * (mipCount - 1)`. A single level uses
LOD zero. Cropping an existing chain does not reproduce a shorter rebaked chain.
The original minimum-size argument is not stored; actual level counts and
dimensions describe runtime queries. Keep build arguments separately for
reproduction.

Legal existing assets remain readable. Regenerated pixels can differ because of
source filtering, odd-size coverage, range handling and the 1x1 BC6H fix. There
is no mandatory asset rewrite. Loader APIs, face order, encoding choices,
roughness mapping and standalone BRDF PNG output are unchanged.

Install with `cargo install ibl_cli --version 0.3.0 --locked`, or use the native
Windows x64, macOS arm64 and Linux x64 archives attached to this release. See the
[runtime contract](https://github.com/shawn0326/ibl-baker/blob/v0.3.0/docs/runtime-contract.md) and
[migration details](https://github.com/shawn0326/ibl-baker/blob/v0.3.0/docs/quality-optimization-release-notes.md). Performance
reports are scoped to their measured inputs, sizes, thread counts and platforms.
