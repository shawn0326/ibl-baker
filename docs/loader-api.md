# Loader API Notes

## Scope

The TypeScript loader is parser-only in v1.

Its responsibility is limited to:

- parsing the `.ibla` container
- validating basic format structure while parsing
- reconstructing texture topology from manifest metadata and deterministic ordering
- exposing chunk payloads as encoded bytes with derived metadata

It does not:

- decode PNG payloads
- decode RGBD into HDR float data
- prepare WebGL or WebGPU upload objects
- create engine-specific runtime textures

Those concerns are left to the application or renderer integration layer, which can choose a higher-performance path such as browser-native image decode, GPU-side decode, or custom runtime-specific pipelines.

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

## Public Types

```ts
export type FaceName = 'px' | 'nx' | 'py' | 'ny' | 'pz' | 'nz'

export type TextureTopology =
  | {
      kind: '2d'
      width: number
      height: number
      mipCount: number
      faceCount: 1
    }
  | {
      kind: 'cubemap'
      width: number
      height: number
      mipCount: number
      faceCount: 6
      faceOrder: readonly ['px', 'nx', 'py', 'ny', 'pz', 'nz']
    }

export interface ParsedIBLA {
  header: {
    version: number
    flags: number
  }
  manifest: {
    generator: string
    generatorVersion: string
    encoding: 'rgbd'
    container: 'png'
    pixelFormat: 'rgba8' | 'rgba16f' | 'rgba32f'
    colorSpace: 'linear'
    width: number
    height: number
    mipCount: number
    faceCount: 1 | 6
    build: {
      rotation: number
      samples: number
      quality: string
      encoding: string
    }
  }
  topology: TextureTopology
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
- reconstruct `byteOffset` from chunk-table `byteLength` prefix sums
- expose each chunk as encoded bytes plus derived topology metadata

`parseIBLA` should fail when:

- the header is invalid
- the manifest is missing required fields
- `faceCount` is not supported by the format
- the chunk table length is inconsistent with topology
- chunk payload ranges exceed the binary section

## Parser Output Contract

The parser output is intentionally still encoded.

That means:

- PNG chunks remain PNG bytes
- `encoding = rgbd` remains metadata, not a decode step
- no promise is made about returning upload-ready pixel buffers

Applications can build on top of `ParsedIBLA` to implement:

- PNG decode helpers
- RGBD-to-float conversion
- WebGL upload preparation
- WebGPU upload preparation
- engine-specific runtime adapters

## Defaults and Constraints

- v1 only supports `.ibla` parsing, not direct PNG/LUT handling
- v1 only supports `encoding = rgbd`
- v1 only supports `container = png`
- v1 chunk ordering is `mipLevel` ascending, then fixed cubemap face order when applicable
