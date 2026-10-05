# ibl-baker CLI

[![crates.io](https://img.shields.io/crates/v/ibl_cli?logo=rust)](https://crates.io/crates/ibl_cli)

`ibl-baker` is the command-line tool for baking HDR environments into IBL texture assets.

It supports two output formats:

- **`.ibla`** — a portable, renderer-agnostic archive with PNG-encoded payloads.
  Format specification: [`docs/format-spec.md`](../../docs/format-spec.md)
- **`.ktx2`** — a GPU-ready cubemap with BC6H compression and zstd supercompression.
  See [KTX2 Output](#ktx2-output) below.

BRDF LUT always outputs as standalone `.png` regardless of format choice.

## Installation

The npm distribution is prepared as `@ibltools/cli` (initial publication pending). After publication:

```bash
npx @ibltools/cli --version
npm install --save-dev @ibltools/cli
npx ibl-baker --help
```

See the [npm CLI README](../../packages/cli/README.md) for Node and platform requirements.


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

## Version

`ibl-baker --version` and `ibl-baker -V` print `ibl-baker <Rust package version>` and exit successfully. This native version is independent of the npm distribution version. Starting with npm distribution 0.1.1, the npm launcher adds the npm package name and version on the preceding line; direct native execution is unchanged.

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

### Source Filtering

Both output formats use seamless source cubemap filtering across face edges and
three-face corners. This also applies when resampling or rotating six-face inputs.
Source mip levels use a box filter covering the complete input face, including
the final row and column at odd dimensions. Their dimensions still halve with
integer division, down to one; the filter uses cube-face UV area rather than
spherical solid-angle weighting.

Internal sampling borders are not stored in the output files or included in
clipping reports. Baked pixels can differ from older versions while the existing
file formats, output topology, and roughness mapping remain compatible.

### `.ibla` Output

`.ibla` is a portable, renderer-agnostic archive format with PNG-encoded payloads.

The `--encoding` option controls how pixel data is stored:

- `rgbd-srgb` — HDR values packed into sRGB-transferred RGBA PNG with a recoverable RGB channel range of `[0, 255]`; the default for HDR/EXR inputs
- `srgb` — standard sRGB color PNG, with linear input RGB clamped to `[0, 1]`; the default for LDR inputs
- `linear` — linear-valued PNG for data payloads, with input RGB clamped to `[0, 1]`

The full binary format specification is defined in [`docs/format-spec.md`](../../docs/format-spec.md).

### KTX2 Output

KTX2 outputs are GPU-ready cubemaps using BC6H block compression with zstd supercompression.

- Vulkan format: `VK_FORMAT_BC6H_UFLOAT_BLOCK` (`vkFormat = 143`)
- Data format descriptor: Khronos BC6H UFLOAT with normalized sample range `[0, 1]`
- Compression: BC6H unsigned half-float, 4×4 blocks
- Supercompression: zstd per-level (scheme 2)
- Input: finite linear f32 RGB clamped to `[0, 65504]` before conversion to f16 → BC6H (the `--encoding` option has no effect)
- BC6H stores HDR and LDR values in the `[0, 65504]` range with lossy block compression
- Face order: +X, −X, +Y, −Y, +Z, −Z
- KV metadata: `KTXorientation=rd`, `KTXwriter=ibl-baker v{version}`

### Range Handling

Finite RGB values outside the output encoding's range are clamped automatically.
If any pixels are clamped, the CLI writes one warning to stderr after that output
file is written successfully. Each warning reports the output path and encoding,
clamped and total pixel counts, and the RGB range before clamping. A pixel is counted
once if any of its RGB channels is out of range. Counts cover all output faces and
mip levels, excluding internal source mips, alpha, and BC6H padding.

For example:

```text
Warning: out/specular.ktx2 (bc6h-ufloat): 5 of 126 pixels had RGB channels clamped to [0, 65504] (pre-clip RGB range: [0, 94124]).
```

Inputs whose baked output is within range produce no warning. With
`--output-format both`, each file is checked against its own encoding's range;
RGBD clipping does not imply BC6H clipping. Warnings leave the success output on
stdout and the exit code at `0`. BRDF LUT output does not produce an HDR warning.

NaN and positive or negative infinity are invalid RGB inputs and cause an error.
Clamping does not preserve out-of-range highlight energy. Assets retain their
existing container contracts; no radiance scaling or restoration metadata is added.

## `validate`

`validate` reads and inspects `.ibla` assets. It prints:

- format version, face count, chunk count
- width, height, mip count, encoding
- validation status (with issues listed if invalid)

Validation checks: header magic/version, manifest topology integrity, canonical face ordering, deterministic chunk slot reconstruction, payload byte ranges and overlap.
