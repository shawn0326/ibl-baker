# ibl-baker CLI

`ibl-baker` is the command-line tool for baking HDR environments into IBL texture assets.

It supports two output formats:

- **`.ibla`** — a portable, renderer-agnostic archive with PNG-encoded payloads.
  Format specification: [`docs/format-spec.md`](../../docs/format-spec.md)
- **`.ktx2`** — a GPU-ready cubemap with BC6H compression and zstd supercompression.
  See [KTX2 Output](#ktx2-output) below.

BRDF LUT always outputs as standalone `.png` regardless of format choice.

## Installation

Install the crate from crates.io:

```bash
cargo install ibl_cli
ibl-baker --help
```

The crate name is `ibl_cli`, and the installed executable name is `ibl-baker`.
This installation path requires a Rust toolchain.

Prebuilt binaries for Windows x64, macOS arm64, and Linux x64 are also attached to GitHub Releases.
That path does not require installing Rust.

## Quick Start

```bash
# .ibla output (default)
ibl-baker bake ./environment.hdr --out-dir ./out

# KTX2 output (BC6H + zstd)
ibl-baker bake ./environment.hdr --out-dir ./out --output-format ktx2

# Both formats in one run
ibl-baker bake ./environment.hdr --out-dir ./out --output-format both

# Validate an .ibla asset
ibl-baker validate ./out/specular.ibla
```

## Commands

```bash
ibl-baker bake input-path --out-dir ./out
ibl-baker bake input-path --out-dir ./out --target specular
ibl-baker bake ./fixtures/inputs/pisa.hdr --out-dir ./out --target irradiance
ibl-baker bake ./fixtures/inputs/Bridge2 --out-dir ./out --faces posx.jpg,negx.jpg,posy.jpg,negy.jpg,posz.jpg,negz.jpg
ibl-baker validate ./out/specular.ibla
```

## `bake`

### Options

| Option | Values | Default | Description |
| --- | --- | --- | --- |
| `--out-dir` | path | *(required)* | Output directory |
| `--target` | `specular`, `irradiance`, `lut` | all | Repeatable; filters output set |
| `--output-format` | `ibla`, `ktx2`, `both` | `ibla` | Output container format |
| `--size` | `auto` or integer | `auto` | Specular cubemap face size; also the source cubemap size for irradiance filtering |
| `--irradiance-size` | integer | `32` | Final irradiance cubemap face size |
| `--encoding` | `auto`, `rgbd-srgb`, `srgb`, `linear` | `auto` | `.ibla` payload encoding (ignored for KTX2) |
| `--faces` | comma-separated filenames | *(auto-detect)* | Face order for directory inputs |
| `--rotation` | float | `0` | Y-axis rotation in radians |
| `--samples` | integer | `1024` | Requested sample count for convolution |
| `--quality` | `low`, `medium`, `high` | `medium` | Bake quality preset |

### Output Files

| `--output-format` | specular | irradiance | lut |
| --- | --- | --- | --- |
| `ibla` (default) | `specular.ibla` | `irradiance.ibla` | `brdf-lut.png` |
| `ktx2` | `specular.ktx2` | `irradiance.ktx2` | `brdf-lut.png` |
| `both` | both `.ibla` + `.ktx2` | both `.ibla` + `.ktx2` | `brdf-lut.png` |

BRDF LUT always outputs as `.png` regardless of `--output-format`.

### Input

- `input-path` accepts a single latlong image file (`.hdr`, `.exr`, `.png`, `.jpg`) or a directory containing 6 cubemap faces.
- `--faces` is only valid for directory inputs and uses the fixed face order `px, nx, py, ny, pz, nz`.
- Directory inputs auto-detect face files matching `px/nx/...` or `posx/negx/...` naming. If ambiguous, pass `--faces` explicitly.
- All 6 faces must share the same format family and identical square dimensions.

### Defaults

- `--size auto` selects from `128 | 256 | 512 | 1024 | 2048 | 4096`
  - file inputs: estimates face size as `min(width / 4, height / 2)`
  - directory inputs: uses detected face size directly
  - selects the largest bucket not exceeding the estimated size; minimum `128`, fallback `512`
- `--encoding auto` resolves to `rgbd-srgb` for `.hdr`/`.exr` and `srgb` for `.png`/`.jpg`/`.jpeg`
- `linear` is only selected via explicit `--encoding linear`
- BRDF LUT output is always `256×256`
- `--irradiance-size` controls only the final irradiance cubemap face size; `--size` controls the internal source cubemap resolution used by irradiance filtering
- Irradiance sampling is capped by quality: `low` = 256, `medium` = 1024, `high` = 2048; explicit lower `--samples` values are preserved

### `.ibla` Output

`.ibla` is a portable, renderer-agnostic archive format with PNG-encoded payloads.

The `--encoding` option controls how pixel data is stored:

- `rgbd-srgb` — HDR values packed into sRGB-transferred RGBA PNG; the default for HDR/EXR inputs
- `srgb` — standard sRGB color PNG; the default for LDR inputs
- `linear` — linear-valued PNG for data payloads

The full binary format specification is defined in [`docs/format-spec.md`](../../docs/format-spec.md).

### KTX2 Output

KTX2 outputs are GPU-ready cubemaps using BC6H block compression with zstd supercompression.

- Vulkan format: `VK_FORMAT_BC6H_UFLOAT_BLOCK` (format 131)
- Compression: BC6H unsigned half-float, 4×4 blocks
- Supercompression: zstd per-level (scheme 2)
- Input: linear f32 pixels converted to f16 → BC6H (the `--encoding` option has no effect)
- BC6H `[0, 65504]` range cleanly represents both HDR and LDR sources
- Face order: +X, −X, +Y, −Y, +Z, −Z
- KV metadata: `KTXorientation=rd`, `KTXwriter=ibl-baker v{version}`

## `validate`

`validate` reads and inspects `.ibla` assets. It prints:

- format version, face count, chunk count
- width, height, mip count, encoding
- validation status (with issues listed if invalid)

Validation checks: header magic/version, manifest topology integrity, canonical face ordering, deterministic chunk slot reconstruction, payload byte ranges and overlap.
