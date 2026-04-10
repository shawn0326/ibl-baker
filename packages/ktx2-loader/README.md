# @ibltools/ktx2-loader

`@ibltools/ktx2-loader` is a narrow TypeScript loader for KTX2 assets produced by `ibl-baker`.

It is intentionally not a general-purpose KTX2 parser.
The supported profile is the current CLI output shape:

- KTX2 container
- `VK_FORMAT_BC6H_UFLOAT_BLOCK` (`vkFormat = 131`)
- zstd supercompression (`supercompressionScheme = 2`)
- non-array cubemap (`faceCount = 6`, `pixelDepth = 0`, `layerCount = 0`)
- one or more mip levels
- canonical face order: `px`, `nx`, `py`, `ny`, `pz`, `nz`
- `KTXorientation = rd`
- `KTXwriter` metadata beginning with `ibl-baker `

The KTX2 output profile is documented in the CLI README:
<https://github.com/shawn0326/ibl-baker/blob/main/crates/ibl_cli/README.md#ktx2-output>

## Installation

```bash
npm install @ibltools/ktx2-loader
```

## Usage

```ts
import { parseKTX2IBL } from "@ibltools/ktx2-loader";

const parsed = parseKTX2IBL(buffer);
console.log(parsed.header.pixelWidth, parsed.levels.length);
```

## Scope

This loader validates and exposes the IBL KTX2 container layout.

It does:

- validate the KTX2 header profile used by `ibl-baker`
- validate the BC6H UFLOAT data format descriptor
- parse `KTXorientation` and `KTXwriter` metadata
- expose each mip level's zstd-compressed bytes
- derive the expected BC6H face slices after zstd decompression

It does not:

- support arbitrary KTX2 files
- decompress zstd payloads
- decode BC6H blocks into pixels
- create WebGL, WebGPU, or engine-specific texture objects
- parse `.ibla` files

Consumers that need upload-ready BC6H data should zstd-decompress each level's `compressedBytes`.
After decompression, use the level's `faces` entries to split the raw BC6H bytes into the six cubemap faces.

## Public API

```ts
export function parseKTX2IBL(buffer: ArrayBuffer | Uint8Array): ParsedKTX2IBL
```

`parseKTX2IBL` is a fail-fast API.
It throws `KTX2IBLParseError` when the file is invalid or outside the supported IBL profile.

## Public Types

```ts
export type KTX2IBLFaceName = 'px' | 'nx' | 'py' | 'ny' | 'pz' | 'nz'

export type KTX2IBLParseErrorCode =
  | 'INVALID_HEADER'
  | 'UNSUPPORTED_FORMAT'
  | 'UNSUPPORTED_TOPOLOGY'
  | 'INVALID_INDEX'
  | 'INVALID_LEVEL_INDEX'
  | 'INVALID_DATA_FORMAT_DESCRIPTOR'
  | 'INVALID_KEY_VALUE_DATA'

export class KTX2IBLParseError extends Error {
  readonly code: KTX2IBLParseErrorCode
}

export interface ParsedKTX2IBL {
  header: {
    vkFormat: 131
    typeSize: 1
    pixelWidth: number
    pixelHeight: number
    pixelDepth: 0
    layerCount: 0
    faceCount: 6
    levelCount: number
    supercompressionScheme: 2
  }
  format: {
    vkFormatName: 'VK_FORMAT_BC6H_UFLOAT_BLOCK'
    supercompression: 'zstd'
    blockWidth: 4
    blockHeight: 4
    bytesPerBlock: 16
  }
  keyValues: Record<string, string>
  levels: ParsedKTX2IBLLevel[]
}

export interface ParsedKTX2IBLLevel {
  mipLevel: number
  width: number
  height: number
  byteOffset: number
  byteLength: number
  uncompressedByteLength: number
  compressedBytes: Uint8Array
  faces: ParsedKTX2IBLFace[]
}

export interface ParsedKTX2IBLFace {
  face: KTX2IBLFaceName
  width: number
  height: number
  uncompressedByteOffset: number
  uncompressedByteLength: number
}
```

## Level Semantics

KTX2 stores the level index in logical mip order.
For `ibl-baker` outputs, the level payloads are packed in the file from smallest mip to largest mip.
The parser preserves logical mip order in `levels`.

Each `ParsedKTX2IBLLevel` exposes:

- `compressedBytes`: the zstd-compressed level payload from the KTX2 file
- `uncompressedByteLength`: the expected raw BC6H level byte length after zstd decompression
- `faces`: six derived slices into the decompressed BC6H level payload

The face slice byte length is:

```text
ceil(width / 4) * ceil(height / 4) * 16
```

The level byte length is six times that value.
