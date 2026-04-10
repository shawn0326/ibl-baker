# ktx2_writer

`ktx2_writer` is a small write-only KTX2 serializer used by the `ibl-baker` workspace.

It writes cubemap assets with:

- `VK_FORMAT_BC6H_UFLOAT_BLOCK`
- zstd supercompression
- 6 cubemap faces in `+X, -X, +Y, -Y, +Z, -Z` order
- mip levels ordered largest first in the input API
- linear f32 RGB source pixels

The public entry point is `write_bc6h_cubemap_ktx2`, which accepts `CubemapLevel` values and returns a serialized KTX2 byte buffer.

## Scope

This crate only handles KTX2 writing for the current `ibl-baker` IBL output profile.

It does not provide:

- KTX2 parsing
- zstd decompression
- BC6H decoding
- GPU upload helpers
- runtime engine integration

Use `ibl_core` or the `ibl-baker` CLI for the full bake pipeline.
