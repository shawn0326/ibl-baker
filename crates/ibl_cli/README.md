# ibl-baker CLI

`ibl-baker` is the command-line interface for baking HDR environments into portable `.ibla` assets and validating the results.

The shared `.ibla` container contract is defined in the repository format specification:
<https://github.com/shawn0326/ibl-baker/blob/main/docs/format-spec.md>

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
ibl-baker bake ./environment.hdr --out-dir ./out --target specular
ibl-baker validate ./out/specular.ibla
```

## Commands

```bash
ibl-baker bake input-path --out-dir ./out
ibl-baker bake input-path --out-dir ./out --target specular
ibl-baker bake ./fixtures/inputs/pisa --out-dir ./out --target irradiance
ibl-baker bake ./fixtures/inputs/Bridge2 --out-dir ./out --faces posx.jpg,negx.jpg,posy.jpg,negy.jpg,posz.jpg,negz.jpg
ibl-baker validate ./out/specular.ibla
```

## `bake`

Supported v1 options:

- `--out-dir`
- `--target`
- `--size <auto|n>`
- `--irradiance-size`
- `--encoding <auto|rgbd-srgb|srgb|linear>`
- `--faces <px,nx,py,ny,pz,nz>`
- `--rotation`
- `--samples`
- `--quality <low|medium|high>`

Default v1 bake workflow:

- without `--target`, `bake` emits the full output set
- repeated `--target` filters outputs to a subset
- output filenames are fixed in v1:
- `specular.ibla`
- `irradiance.ibla`
- `brdf-lut.png`

Format/output mapping:

- `specular` writes `.ibla`
- `irradiance` writes `.ibla`
- `lut` writes `.png`

Shared tuning semantics:

- `input-path` accepts either a single latlong image file or a directory containing 6 cubemap faces
- `--size` controls specular cubemap face size and defaults to `auto`
- `--irradiance-size` controls irradiance cubemap face size and defaults to `32`
- `--encoding` applies to `.ibla` outputs and defaults to `auto`
- `--faces` is only valid for directory inputs and uses the fixed face order `px, nx, py, ny, pz, nz`
- `--rotation`, `--samples`, and `--quality` apply to the bake run as a whole
- `--quality` accepts `low`, `medium`, or `high` and defaults to `medium`
- `--encoding auto` currently accepts HDR, EXR, PNG, and JPEG-family inputs

Fixed v1 defaults:

- `--size auto` chooses a specular size from `128 | 256 | 512 | 1024 | 2048 | 4096`
- file inputs estimate an equivalent cubemap face size from source dimensions as `min(width / 4, height / 2)`
- directory inputs use the cubemap face size directly before bucket selection
- `--size auto` picks the largest supported bucket that does not exceed the estimated or detected face size
- if the source image is smaller than `128`, `--size auto` still resolves to `128`
- if the source image size cannot currently be detected, `--size auto` falls back to `512`
- irradiance face size defaults to `32`
- `--encoding auto` resolves to `rgbd-srgb` for `.hdr` and `.exr` inputs
- `--encoding auto` resolves to `srgb` for `.png`, `.jpg`, `.jpeg`, and unknown inputs
- `linear` remains available as an explicit manual choice and is not selected by `auto`
- BRDF LUT output is always `256x256`
- `--irradiance-size` remains an explicit numeric override and is not changed by `--size auto`

Directory cubemap auto-detection:

- v1 auto-detection only supports `px, nx, py, ny, pz, nz`
- v1 also supports `posx, negx, posy, negy, posz, negz`
- auto-detection succeeds only when exactly one full 6-face preset matches
- if auto-detection fails or is ambiguous, pass `--faces <px,nx,py,ny,pz,nz>` with file names relative to the input directory
- directory cubemap inputs must use one shared source format family, identical square dimensions, and all 6 faces must be present

Encoding reference:

- `rgbd-srgb` is the default HDR-oriented export path
- `srgb` is the default LDR color-image export path for non-HDR inputs under `--encoding auto`
- `linear` remains available as an explicit manual choice for linear data payloads

The exact file-level encoding semantics are defined in the repository format specification:
<https://github.com/shawn0326/ibl-baker/blob/main/docs/format-spec.md>

## `validate`

`validate` is the public read/inspect command for `.ibla` assets.

It always prints:

- format version
- face count
- chunk count
- width
- height
- mip count
- encoding
- validation status

If the asset is invalid, it appends validation issues after the summary.

Validation checks include:

- header magic and version
- manifest topology integrity
- canonical face ordering for cubemaps
- deterministic chunk slot reconstruction
- payload byte ranges and overlap
- cubemap-vs-2D face usage
