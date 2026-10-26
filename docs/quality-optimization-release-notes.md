# Quality optimization migration notes

These changes are prepared for [Rust/CLI 0.3.0](releases/rust-cli-0.3.0.md) and
[@ibltools/cli 0.2.0](releases/npm-cli-0.2.0.md). The dated notes describe the
complete release since the prior published versions; this document focuses on
the optimization and Rust source migration. Publication follows the normal
[release process](release.md), independently of version preparation.

- The CLI accepts `--specular-min-size <auto|positive integer>`. `auto` remains a
  complete chain ending at one. Explicit larger minima rebake the retained levels
  over the entire perceptual roughness range. See the
  [CLI contract](../crates/ibl_cli/README.md#specular-levels).
- `--output-format both` shares one cubemap bake per asset across IBLA and KTX2
  encoding. Clipping reports remain independent. Successful earlier writes are
  retained if a later format fails.
- A CLI job reuses one decoded source across selected targets. Rust callers can
  use the additive opaque `LoadedEnvironment` API for the same reuse; existing
  signatures and options remain available. Base float cubemaps move into their
  mip chains and finished outputs instead of being deeply copied. Quality,
  payload bytes, target order and per-format warning behavior are preserved.
- Cubemap filtering prepares source LOD and neighboring mip indices/weights once
  per pass. The arithmetic, source footprint, sample sequence and accumulation
  order are unchanged; float regressions and paired production runs check exact
  output parity. No new API or quality parameter is required. See the
  [incremental performance acceptance](lod-performance.md).
- BC6H 1x1 faces use uniform input blocks instead of introducing black padding.
  Regenerated 1x1 KTX2 payloads may change; other levels, dimensions, clipping
  counts, block lengths and consumer APIs retain their existing contracts. The
  complete-chain follow-up keeps quadratic sampling after rejecting linear
  candidates with measured subgroup regressions.
- Rust gains opaque reusable `BakedCubemap` output from `bake_to_cubemap` and
  `bake_cubemap_to_cubemap`. Existing bake function signatures remain available.
- Complete Rust `BakeOptions` literals must add `specular_min_size: None`.
  `..Default::default()` users need no change. This is a source compatibility
  change even though CLI defaults and asset layouts are preserved.
- IBLA v1, KTX2 BC6H UFLOAT + zstd, BRDF PNG, and both parser-only loader APIs
  remain unchanged. Consumers use the asset's actual level count, upload every
  baked level, disable automatic mip generation and configure the accessible
  mip range. The linear roughness-to-LOD formula is unchanged.

There is no automatic migration or overwrite of existing assets. An explicit
minimum of one preserves the full-chain layout, not a promise of historical
pixel identity across all earlier releases. Larger minimum widths trade fewer
roughness interpolation knots for more directional resolution at the rough end;
they are opt-in and are not a general quality recommendation.
