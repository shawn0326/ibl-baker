# @ibltools/ktx2-loader 0.3.0

Date: 2026-09-21

Recognize the standard `VK_FORMAT_BC6H_UFLOAT_BLOCK` value `143` emitted by Rust/CLI 0.2.3 and later.

Historical `ibl-baker` KTX2 files with `vkFormat = 131` remain readable only for writer versions `v0.1.0` through `v0.2.2`, and only when their BC6H data format descriptor, writer metadata, cubemap topology, zstd scheme, and level layout match the supported profile. The parser preserves the original header value in `ParsedKTX2IBL.header.vkFormat`.
