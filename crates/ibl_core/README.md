# ibl_core

[![crates.io](https://img.shields.io/crates/v/ibl_core?logo=rust)](https://crates.io/crates/ibl_core)

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

## Source Cubemap Filtering

Cubemap input resampling and source mip lookups use seamless bilinear filtering.
Each source level caches oriented neighboring edge pixels and averages the three
incident face pixels at a corner. Trilinear lookups apply this reconstruction to
both source levels. The internal border cache is excluded from output images and
`BakeReport` pixel counts.

Source mip dimensions continue to halve with integer division, down to one.
Even dimensions retain the four-pixel equal-weight box filter. Odd dimensions
use the full destination footprint, weighted by overlap in cube-face UV space,
so the final source row and column contribute rather than being discarded.
This is a box reconstruction policy, not solid-angle-weighted spherical reduction.

These changes can alter baked pixels without changing face orientation,
roughness-to-mip mapping, output dimensions, encoding, or file contracts.

## Sampling Budgets

`BakeOptions::sample_count` is a requested budget. Zero uses one sample, recorded
as `1` in `.ibla` build metadata, and
positive requests below eight are preserved by specular, irradiance, and BRDF
LUT sampling. Specular's minimum adaptive budget never exceeds the available
budget for the mip.

Specular sampling otherwise keeps its roughness and mip-size adaptation, with
base quality caps of 256 (`Low`), 512 (`Medium`), and 1024 (`High`). Smaller mips
can boost the capped budget up to the requested count. Irradiance and BRDF LUT
sampling retain their own quality caps.

The [full-chain follow-up](../../docs/sampling-encoding-acceptance.md) isolates
actual sample count from the source-LOD footprint. Linear-budget candidates stay
experimental because of converged HDR and encoded subgroup regressions.
Production keeps the existing r-squared budget and coupled source footprint.

## Bake Reports And RGB Ranges

`bake_to_cubemap(path, options)` and
`bake_cubemap_to_cubemap(&face_paths, options)` return an opaque `BakedCubemap` for
specular or irradiance assets. It owns the unencoded linear levels without
exposing their internal pixel layout. Call `to_asset_with_report()` and/or
`to_ktx2_with_report()` on the same value to encode once per format. Neither
encoder changes the stored pixels; reports are computed independently against
each encoding's range. Drop each encoded output after writing it to avoid keeping
both encoded buffers alive. BRDF LUT continues to use the existing asset API.

```rust,no_run
use ibl_core::{bake_to_cubemap, write_asset, BakeOptions};
# fn main() -> Result<(), Box<dyn std::error::Error>> {
let baked = bake_to_cubemap("environment.hdr", BakeOptions::default())?;
{
    let (asset, report) = baked.to_asset_with_report()?;
    write_asset("specular.ibla", &asset)?;
    // Inspect report after a successful write.
    let _ = report;
}
let (bytes, report) = baked.to_ktx2_with_report()?;
std::fs::write("specular.ktx2", bytes)?;
let _ = report;
# Ok(())
# }
```

The report variants of the existing bake functions return `(output, BakeReport)`:

- `bake_to_asset_with_report` and `bake_cubemap_to_asset_with_report`
- `bake_to_ktx2_with_report` and `bake_cubemap_to_ktx2_with_report`

`BakeReport` contains `min_rgb` and `max_rgb` (`f32`), measured before encoding,
and `clipped_pixel_count` and `total_pixel_count` (`u64`). It covers only the final
output pixels across every face and mip level. A pixel counts as clipped once if
any RGB component is outside the encoding range. Source images, intermediate
source mip chains, alpha, and compression padding are excluded.

The existing bake functions keep their signatures and discard the report.
Reports are not serialized into `.ibla` or KTX2, and the library does not print warnings.
The CLI uses these reports to warn after successfully writing a clipped output.

PNG output retains its existing component limits: `[0, 255]` for `rgbd-srgb` and
`[0, 1]` for `srgb` or `linear`. KTX2 output clamps finite RGB components to
`[0, 65504]` before conversion to half floats and BC6H compression.
These limits can discard highlights or negative values; no recovery multiplier
is stored. Non-finite source or output RGB values (`NaN`, positive infinity, or
negative infinity) return `IblError::InvalidInput` instead of being encoded.
BRDF LUT reports use the linear range `[0, 1]`.

See the [CLI encoding and KTX2 output documentation](../ibl_cli/README.md) and
the [`.ibla` format specification](../../docs/format-spec.md) for output contracts.

## IBLA Mip Topology

`BakeOptions::specular_min_size: Option<u32>` controls the specular output's
minimum face width. `None` currently resolves to `1`; `Some(1)` also produces the
complete chain. Larger values keep the natural floor-halved levels whose width
is at least the minimum. All retained levels are rebaked over the complete linear
perceptual-roughness range. A base size greater than one must retain at least two
levels; otherwise the bake returns `IblError::InvalidInput`. Base size one allows
only `None` or `Some(1)` and has no roughness variation. `Some(0)` is invalid for
specular. This field has no effect on irradiance or LUT baking.

**Rust source migration:** complete `BakeOptions { ... }` literals must add
`specular_min_size: None`. Literals with `..Default::default()` and existing bake
function signatures remain supported. There is no container or loader API
migration. See [CLI Specular Levels](../ibl_cli/README.md#specular-levels) for
examples and consumer sampling requirements.

Reading, writing, and validation enforce the natural mip limit:
`1 <= mip_count <= 1 + floor(log2(max(width, height)))`. Complete and truncated
chains are supported, including non-power-of-two sizes and rectangular single-face
textures. Cubemap dimensions must remain square. A chain cannot continue past its
first `1x1` level.

When writing an in-memory asset, chunk identities and dimensions must match this
implicit topology. Invalid topology is rejected before serialization; offsets and
lengths are still normalized from the paired payloads. Reading derives dimensions
from metadata without decoding PNG payloads. Earlier versions did not reject extra
`1x1` tail levels; those malformed chains are now rejected consistently with the
TypeScript loader.

## Relationship To Other Packages

- `crates/ibl_cli` exposes the public command-line workflow on top of this crate.
  See [`crates/ibl_cli/README.md`](../ibl_cli/README.md) for CLI options and output format details.
- `crates/ktx2_writer` is the write-only KTX2 serializer used internally for KTX2 output.
  See [`crates/ktx2_writer/README.md`](../ktx2_writer/README.md) for its narrow serialization scope.
- `packages/ibla-loader` is the parser-only TypeScript reader for `.ibla` files.
- `packages/ktx2-loader` is the narrow TypeScript reader for `ibl-baker` KTX2 cubemap files.

The `.ibla` binary format is defined in [`docs/format-spec.md`](../../docs/format-spec.md).
