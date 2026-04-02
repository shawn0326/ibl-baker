# `.ibla` Format Specification

## Overview

`.ibla` is a renderer-agnostic HDR texture container format.

One `.ibla` file represents exactly one texture payload set:

- one 2D texture with optional mip levels
- or one cubemap with optional mip levels

Version 1 stores data in four consecutive sections:

1. `Header`
2. `Manifest JSON`
3. `Chunk Table`
4. `Binary Chunks`

Each chunk record describes exactly one independently decodable image payload.

## Header

The header is always 16 bytes and uses little-endian encoding.

| Field | Type | Description |
| --- | --- | --- |
| `magic` | `[u8; 4]` | Must be `IBLA`. |
| `version` | `u16` | Format version. v1 uses `1`. |
| `flags` | `u16` | Reserved for future use. |
| `manifest_byte_length` | `u32` | Number of bytes in the UTF-8 manifest section. |
| `chunk_table_byte_length` | `u32` | Number of bytes in the binary chunk table section. |

## Manifest JSON

The manifest is UTF-8 JSON without BOM and uses deterministic field ordering.

Required fields:

- `generator`
- `generatorVersion`
- `encoding`
- `container`
- `pixelFormat`
- `colorSpace`
- `width`
- `height`
- `mipCount`
- `faceCount`
- `build`

v1 fixed values:

- `encoding = "rgbd"`
- `container = "png"`

v1 schema allows these pixel formats:

- `pixelFormat = "rgba8"`
- `pixelFormat = "rgba16f"`
- `pixelFormat = "rgba32f"`

## Texture Topology

Version 1 describes texture topology with manifest fields instead of asset-purpose semantics.

- `faceCount = 1` means a 2D texture
- `faceCount = 6` means a cubemap
- `mipCount` is the number of mip levels for one texture image sequence, not the total chunk count across all faces
- total chunk count is `mipCount` for 2D textures and `mipCount * 6` for cubemaps

For cubemaps:

- each chunk stores one face for one mip
- faces always use the fixed order `px, nx, py, ny, pz, nz`

For 2D textures:

- each chunk stores one 2D image for one mip
- there is no face axis in the logical texture topology

## Encoding

v1 uses `rgbd` as the only encoding strategy.

Rules fixed in v1:

- runtime decoders must treat manifest metadata as the source of truth
- future float reconstruction helpers must preserve the same metadata interpretation
- `container` and `pixelFormat` are separate concerns; future containers may carry the same logical pixel format
- `colorSpace = "linear"`
- additional encoding-specific parameters can be introduced later when the decode path needs them

Current implementation note:

- the placeholder writer currently emits `rgba8`
- future HDR/EXR-oriented writers should preserve higher precision and must not down-quantize to `rgba8` by default

## Chunk Table

The chunk table is a binary section.
The section stores only a repeated sequence of:

- `byte_length: u64`

The number of chunk-table entries is implicit:

- `entryCount = mipCount * faceCount`

Chunk identity is not stored explicitly.
Readers reconstruct each chunk's `mip` and `face` from manifest topology and deterministic ordering.

`byte_offset` is implicit and reconstructed as the prefix sum of preceding `byte_length` values.

## Binary Chunks

The binary section is the concatenation of all image payloads in deterministic chunk-table order.

v1 constraints:

- each record points to one payload
- each payload is independently decodable
- each payload uses the manifest-level `container`
- `faceCount` must be `1` or `6`
- cubemaps always use the fixed face order `px, nx, py, ny, pz, nz`

## Deterministic Ordering

Writers must emit records in stable order:

1. Order chunks by ascending `mipLevel`, starting from `0`.
2. Within the same `mipLevel`, 2D textures emit their single chunk, while cubemaps emit faces in fixed `px, nx, py, ny, pz, nz` order.
