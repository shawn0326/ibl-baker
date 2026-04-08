# `.ibla` Format Specification

## Overview

`.ibla` is a renderer-agnostic texture container format for IBL asset payloads.
In v1, the main production path remains HDR IBL assets, while `srgb` and `linear`
encodings are included to keep the container contract consistent across related payload types.

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

The manifest is UTF-8 JSON without BOM.

Writers must emit manifest fields in deterministic order so the serialized output is stable.
Readers must treat JSON object field order as non-semantic.

Required fields:

- `generator`
- `generatorVersion`
- `encoding`
- `container`
- `width`
- `height`
- `mipCount`
- `faceCount`
- `build`

Required top-level field order in v1:

1. `generator`
2. `generatorVersion`
3. `encoding`
4. `container`
5. `width`
6. `height`
7. `mipCount`
8. `faceCount`
9. `build`

v1 fixed container:

- `container = "png"`

v1 supported encodings:

- `encoding = "rgbd-srgb"`
- `encoding = "srgb"`
- `encoding = "linear"`

Required `build` fields:

- `rotation`
- `samples`
- `quality`
- `sourceFormat`

Required `build` field order in v1:

1. `rotation`
2. `samples`
3. `quality`
4. `sourceFormat`

v1 supported `build.quality` values:

- `low`
- `medium`
- `high`

v1 supported `build.sourceFormat` values:

- `hdr`
- `exr`
- `png`
- `jpg`
- `jpeg`
- `unknown`

## Texture Topology

Version 1 describes texture topology with manifest fields instead of asset-purpose semantics.

- `faceCount = 1` means a 2D texture
- `faceCount = 6` means a cubemap
- when `faceCount = 6`, `width` and `height` must be equal and describe the mip 0 face size
- `mipCount` is the number of mip levels for one texture image sequence, not the total chunk count across all faces
- total chunk count is `mipCount` for 2D textures and `mipCount * 6` for cubemaps

For cubemaps:

- each chunk stores one face for one mip
- faces always use the fixed order `px, nx, py, ny, pz, nz`

For 2D textures:

- each chunk stores one 2D image for one mip
- there is no face axis in the logical texture topology

Per-chunk dimensions are derived, not stored explicitly in v1.

For 2D textures:

```text
chunkWidth = max(1, floor(width / 2^mipLevel))
chunkHeight = max(1, floor(height / 2^mipLevel))
```

For cubemaps:

```text
chunkWidth = chunkHeight = max(1, floor(width / 2^mipLevel))
```

Equivalently, v1 readers may use:

```text
dimensionAtMip(base, mipLevel) = max(1, base >> mipLevel)
```

## Encoding

`encoding` defines how chunk payload bytes must be interpreted after PNG decode.

Rules fixed in v1:

- runtime decoders must treat manifest metadata as the source of truth
- `build.sourceFormat` is provenance metadata and does not affect payload parsing
- additional encoding-specific parameters can be introduced later when the decode path needs them

Normative v1 encoding semantics:

- `rgbd-srgb`
  - the payload is an RGBA PNG image
  - RGB channels store RGBD-packed values after sRGB transfer
  - alpha stores the linear `D` term
  - decoding must recover linear HDR values from the sampled RGBA payload
- `srgb`
  - the payload is an ordinary PNG color image
  - payload RGB data must be interpreted as sRGB color data
- `linear`
  - the payload is an ordinary PNG image used as linear data
  - payload values must be interpreted without sRGB transfer

Reference packing contract for `rgbd-srgb`:

```glsl
vec4 encodeRgbdSrgb(vec3 linearColor) {
    float maxRgb = max(linearColor.r, max(linearColor.g, linearColor.b));
    float d = max(255.0 / maxRgb, 1.0);
    d = clamp(floor(d) / 255.0, 0.0, 1.0);

    vec3 rgbdLinear = linearColor * d;
    vec3 rgbdSrgb = LinearTosRGB(rgbdLinear);

    return vec4(clamp(rgbdSrgb, 0.0, 1.0), d);
}
```

What matters for v1 is the stored-data contract:

- RGB channels are written after sRGB transfer
- alpha stores the linear `D` term
- the encoded payload is then quantized into PNG bytes

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
- chunk-table-declared payload ranges must exactly cover the binary section with no undeclared trailing bytes
- `faceCount` must be `1` or `6`
- cubemaps always use the fixed face order `px, nx, py, ny, pz, nz`

## Deterministic Ordering

Writers must emit records in stable order:

1. Order chunks by ascending `mipLevel`, starting from `0`.
2. Within the same `mipLevel`, 2D textures emit their single chunk, while cubemaps emit faces in fixed `px, nx, py, ny, pz, nz` order.
