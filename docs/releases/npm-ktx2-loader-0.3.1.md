# @ibltools/ktx2-loader 0.3.1

Date: 2026-10-26

Reject level counts above the natural integer-halving cubemap chain limit,
including repeated 1x1 tail levels. These inputs now throw `KTX2IBLParseError`
with code `UNSUPPORTED_TOPOLOGY`. Legal complete and truncated chains and NPOT
container dimensions remain supported; GPU upload restrictions still depend on
the graphics API and device.

The parser-only `parseKTX2IBL` API and BC6H UFLOAT + zstd profile are unchanged.
Standard `vkFormat = 143` files from Rust/CLI 0.3.0 use the existing parser path.
Restricted compatibility for historical writer versions 0.1.0 through 0.2.2 is
unchanged. Returned payloads remain zero-copy views; zstd decompression, BC6H
support and GPU upload remain consumer responsibilities.

Install with `npm install @ibltools/ktx2-loader@0.3.1`. Use
`header.levelCount` and the returned level dimensions, upload every supplied
level and disable automatic mip generation. No application code change is
needed for valid baker outputs. Repair or regenerate custom assets exceeding
the natural chain. Node.js 24 or later remains the Node runtime requirement.
