# @ibltools/loader

`@ibltools/loader` is the parser-only TypeScript loader for `.ibla` assets.

This package exposes the public v1 parsing contract for applications and renderer-specific integrations.
The shared `.ibla` container contract is defined in the repository format specification:
<https://github.com/shawn0326/ibl-baker/blob/main/docs/format-spec.md>

## Installation

```bash
npm install @ibltools/loader
```

## Usage

```ts
import { parseIBLA } from "@ibltools/loader";

const parsed = parseIBLA(buffer);
console.log(parsed.manifest.faceCount, parsed.manifest.encoding);
```

## Scope

The TypeScript loader is parser-only in v1.

Its responsibility is limited to:

- parsing the `.ibla` container
- validating basic format structure while parsing
- exposing chunk payloads as encoded bytes with derived metadata

It does not:

- decode PNG payloads
- decode RGBD into HDR float data
- prepare WebGL or WebGPU upload objects
- create engine-specific runtime textures

Those concerns are left to the application or renderer integration layer.

For KTX2 assets produced by the CLI (`--output-format ktx2`), applications should use
ecosystem KTX2 parsers (e.g., `ktx-parse`) directly — this package does not handle `.ktx2` files.

## Core Model

One parsed `.ibla` file maps to one texture payload set.

- `faceCount = 1` means a 2D texture with `mipCount` images
- `faceCount = 6` means a cubemap with `mipCount * 6` images
- chunk identity is reconstructed from deterministic ordering, not stored explicitly in the file
- chunk payload bytes remain encoded according to manifest metadata

In the current CLI workflow, `.ibla` is used for specular and irradiance outputs.
BRDF LUT is emitted as a direct `.png` and does not go through the `.ibla` loader.

## Public API

```ts
export function parseIBLA(buffer: ArrayBuffer | Uint8Array): ParsedIBLA
```

`parseIBLA` is a fail-fast API.
In v1 it throws `IBLAParseError` when the container is invalid or unsupported.

## Public Types

```ts
export type FaceName = 'px' | 'nx' | 'py' | 'ny' | 'pz' | 'nz'

export type BakeQuality = 'low' | 'medium' | 'high'

export type IBLAParseErrorCode =
  | 'INVALID_HEADER'
  | 'UNSUPPORTED_VERSION'
  | 'INVALID_MANIFEST'
  | 'UNSUPPORTED_FACE_COUNT'
  | 'INVALID_CUBEMAP_DIMENSIONS'
  | 'INVALID_CHUNK_TABLE_LENGTH'
  | 'CHUNK_RANGE_OUT_OF_BOUNDS'

export class IBLAParseError extends Error {
  readonly code: IBLAParseErrorCode
}

export interface ParsedIBLA {
  header: {
    version: number
    flags: number
  }
  manifest: {
    generator: string
    generatorVersion: string
    encoding: 'rgbd-srgb' | 'srgb' | 'linear'
    container: 'png'
    width: number
    height: number
    mipCount: number
    faceCount: 1 | 6
    build: {
      rotation: number
      samples: number
      quality: BakeQuality
      sourceFormat: 'hdr' | 'exr' | 'png' | 'jpg' | 'jpeg' | 'unknown'
    }
  }
  chunks: ParsedChunk[]
}

export interface ParsedChunk {
  index: number
  mipLevel: number
  face: FaceName | null
  width: number
  height: number
  byteOffset: number
  byteLength: number
  encodedBytes: Uint8Array
}
```

## `parseIBLA(buffer)` Semantics

`parseIBLA` must:

- validate header magic and version
- read manifest metadata
- reconstruct chunk identity from `mipCount`, `faceCount`, and deterministic ordering
- derive each chunk's `width` and `height` from manifest `width`, `height`, and `mipLevel`
- reconstruct `byteOffset` from chunk-table `byteLength` prefix sums
- expose each chunk as encoded bytes plus derived chunk metadata

`parseIBLA` must throw `IBLAParseError` when:

- the header is invalid
- the manifest is missing required fields
- the manifest contains unsupported enum values
- `faceCount` is not supported by the format
- cubemap dimensions are invalid for the format
- the chunk table length is inconsistent with manifest-declared topology
- chunk payload ranges exceed or do not exactly cover the binary section

Recommended v1 error-code mapping:

- invalid header bytes or magic -> `INVALID_HEADER`
- unsupported format version -> `UNSUPPORTED_VERSION`
- malformed JSON, missing required fields, or unsupported manifest enums -> `INVALID_MANIFEST`
- unsupported `faceCount` -> `UNSUPPORTED_FACE_COUNT`
- invalid cubemap `width` / `height` relationship -> `INVALID_CUBEMAP_DIMENSIONS`
- inconsistent chunk-table byte length or entry count -> `INVALID_CHUNK_TABLE_LENGTH`
- payload byte ranges exceeding or not exactly covering the binary section -> `CHUNK_RANGE_OUT_OF_BOUNDS`

Dimension derivation in v1:

For 2D textures:

```text
chunkWidth = max(1, floor(width / 2^mipLevel))
chunkHeight = max(1, floor(height / 2^mipLevel))
```

For cubemaps:

```text
chunkWidth = chunkHeight = max(1, floor(width / 2^mipLevel))
```

Equivalently, readers may use:

```text
dimensionAtMip(base, mipLevel) = max(1, base >> mipLevel)
```

## Parser Output Contract

The parser output is intentionally still encoded.

That means:

- PNG chunks remain PNG bytes
- `manifest.encoding` remains metadata, not a decode step
- `build.sourceFormat` remains provenance metadata, not a parse input
- no promise is made about returning upload-ready pixel buffers

Applications can build on top of `ParsedIBLA` to implement:

- PNG decode helpers
- RGBD-to-float conversion
- WebGL upload preparation
- WebGPU upload preparation
- engine-specific runtime adapters

Those higher-level helpers can derive texture topology directly from manifest metadata:

- `faceCount = 1` means a 2D texture with `mipCount` images
- `faceCount = 6` means a cubemap with `mipCount * 6` images
- cubemap face order remains the fixed v1 sequence `px, nx, py, ny, pz, nz`

Reference decode code for `encoding = "rgbd-srgb"`:

```glsl
vec3 decodeRgbdSrgb(vec4 encodedSample) {
    vec3 linearRgb = sRGBToLinear(encodedSample.rgb);
    return linearRgb / encodedSample.a;
}
```

The exact helper name is not fixed.
What matters for v1 is the decode contract:

- apply sRGB-to-linear conversion to sampled RGB
- keep alpha as the linear `D` value
- reconstruct linear HDR values as `rgb / D`

If a runtime uploads the payload into an sRGB texture format and relies on hardware sRGB sampling, the explicit `sRGBToLinear(encodedSample.rgb)` step can be omitted because the sampled RGB values are already linearized.

Reference consumption contract for the other v1 encodings:

- `srgb`
  - after PNG decode, payload RGB data must be treated as sRGB color data
  - higher-level helpers may keep the decoded bytes in sRGB form or convert them to linear values depending on their output contract
- `linear`
  - after PNG decode, payload values must be treated as linear data
  - higher-level helpers must not apply sRGB-to-linear conversion implicitly

## Defaults and Constraints

- v1 only supports `.ibla` parsing, not direct PNG/LUT handling
- v1 only supports `encoding = rgbd-srgb | srgb | linear`
- v1 only supports `container = png`
- v1 only supports `build.quality = low | medium | high`
- v1 chunk ordering is `mipLevel` ascending, then fixed cubemap face order when applicable
