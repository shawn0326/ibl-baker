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

## Bake Reports And RGB Ranges

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
