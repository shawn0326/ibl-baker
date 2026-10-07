# ktx2_writer

[![crates.io](https://img.shields.io/crates/v/ktx2_writer?logo=rust)](https://crates.io/crates/ktx2_writer)

`ktx2_writer` is a small write-only KTX2 serializer used by the `ibl-baker` workspace.

It writes cubemap assets with:

- `VK_FORMAT_BC6H_UFLOAT_BLOCK` (`vkFormat = 143`)
- Khronos BC6H UFLOAT data format descriptor with normalized sample range `[0, 1]`
- zstd supercompression
- 6 cubemap faces in `+X, -X, +Y, -Y, +Z, -Z` order
- mip levels ordered largest first in the input API
- linear f32 RGB source pixels

The public entry point is `write_bc6h_cubemap_ktx2`, which accepts `CubemapLevel` values and returns a serialized KTX2 byte buffer.
Mip face sizes must follow `max(1, floor(previous_size / 2))`. Single-level,
truncated, and non-power-of-two chains are supported, but the chain must stop
at or before its first 1x1 level. The maximum level count is
`1 + floor(log2(base_size))`. Invalid dimensions, skipped or repeated sizes,
and excess levels return `Ktx2Error::InvalidInput` before compression.

Finite RGB components are clamped to `[0, 65504]` before half-float conversion and BC6H compression. Negative components become zero, and components above the half-float maximum become 65504. The upper limit is also available as `BC6H_UFLOAT_MAX`. NaN and positive or negative infinity return `Ktx2Error::InvalidInput`. The writer does not emit warnings; `ibl_core` and the CLI provide bake diagnostics.

## Scope

This crate only handles KTX2 writing for the current `ibl-baker` IBL output profile.

It does not provide:

- KTX2 parsing
- zstd decompression
- BC6H decoding
- GPU upload helpers
- runtime engine integration

Use `ibl_core` or the `ibl-baker` CLI for the full bake pipeline.
