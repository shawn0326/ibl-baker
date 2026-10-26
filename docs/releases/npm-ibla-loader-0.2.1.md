# @ibltools/ibla-loader 0.2.1

Date: 2026-10-26

Reject manifest mip counts above the natural integer-halving chain limit,
including repeated 1x1 tail levels. These inputs now throw `IBLAParseError` with
code `INVALID_MANIFEST`. Legal complete and truncated chains, NPOT dimensions and
rectangular single-face textures remain supported.

The parser-only `parseIBLA` API and IBLA v1 layout are unchanged. Payloads remain
zero-copy views of the supplied buffer. Use `manifest.mipCount` and the returned
chunk dimensions; no new field is needed for an explicitly shortened bake.
Upload all supplied levels, disable automatic mip generation and retain the
linear roughness-to-LOD contract for specular assets.

Install with `npm install @ibltools/ibla-loader@0.2.1`. No application code change
is needed for valid baker outputs. Repair or regenerate custom assets that
append levels beyond the natural chain. Node.js 24 or later remains the declared
Node runtime requirement; PNG/RGBD decode and GPU upload remain consumer work.
