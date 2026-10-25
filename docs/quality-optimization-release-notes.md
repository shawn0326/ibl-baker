# Quality optimization release notes (unreleased)

No release is published by this work. Package versions are unchanged. Select the
next release through the normal [release process](release.md); account for the
Rust source compatibility change below when choosing its version.

- The CLI accepts `--specular-min-size <auto|positive integer>`. `auto` remains a
  complete chain ending at one. Explicit larger minima rebake the retained levels
  over the entire perceptual roughness range. See the
  [CLI contract](../crates/ibl_cli/README.md#specular-levels).
- `--output-format both` shares one cubemap bake per asset across IBLA and KTX2
  encoding. Clipping reports remain independent. Successful earlier writes are
  retained if a later format fails.
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
