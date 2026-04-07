# @ibltools/three-loader

`@ibltools/three-loader` is the browser-side three.js integration package for `.ibla` cubemap assets.

It builds on top of `@ibltools/loader` and keeps renderer-specific decode and texture construction out of the parser package.
The shared `.ibla` container contract is defined in the repository format specification:
<https://github.com/shawn0326/ibl-baker/blob/main/docs/format-spec.md>

## Installation

```bash
npm install @ibltools/three-loader three
```

## Scope

`@ibltools/three-loader` is the renderer-specific browser integration layer for `.ibla` assets in three.js.

In the current v1 scope it:

- accepts `.ibla` bytes
- parses them through `@ibltools/loader`
- only supports cubemap assets (`faceCount = 6`)
- decodes PNG payloads in the browser
- reconstructs browser-displayable cubemap faces
- returns concrete three.js runtime texture objects

It is intentionally not renderer-agnostic.

## Public API

```ts
export interface LoadIBLACubemapOptions {
  label?: string
}

export function loadIBLACubemap(
  buffer: ArrayBuffer | Uint8Array,
  options?: LoadIBLACubemapOptions,
): Promise<THREE.CubeTexture>

export function loadIBLAIrradianceCubemap(
  buffer: ArrayBuffer | Uint8Array,
  options?: LoadIBLACubemapOptions,
): Promise<THREE.CubeTexture>
```

Both APIs:

- parse `.ibla` through `@ibltools/loader`
- require `topology.kind = "cubemap"`
- reject non-cubemap assets with `ThreeIBLAError`
- preserve canonical face ordering `px, nx, py, ny, pz, nz`

## Current v1 behavior

The first cut is aimed at browser integration and visual validation.

- `rgbd-srgb` payloads are decoded from stored RGBD values before conversion into browser-displayable cubemap faces
- `srgb` payloads are treated as sRGB color data
- `linear` payloads are treated as linear data
- the package returns `THREE.CubeTexture`, not generic upload blobs

This package currently targets browser-side decode.
If a future phase adds a higher-fidelity three.js upload path, it should extend this README directly.

## Errors

```ts
export class ThreeIBLAError extends Error {}
```

`ThreeIBLAError` is used for renderer-integration failures such as:

- non-cubemap `.ibla` input
- browser PNG decode failures
- missing browser canvas APIs
