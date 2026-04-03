# CLI Reference

## Commands

```bash
ibl-baker bake input-image --out-dir ./out
ibl-baker bake input-image --out-dir ./out --target specular
ibl-baker bake input-image --out-dir ./out --target irradiance --target lut
ibl-baker validate ./out/specular.ibla
```

## `bake`

Supported v1 options:

- `--out-dir`
- `--target`
- `--size <auto|n>`
- `--irradiance-size`
- `--encoding <auto|rgbd-srgb|srgb|linear>`
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

- `--size` controls specular cubemap face size and defaults to `auto`
- `--irradiance-size` controls irradiance cubemap face size and defaults to `32`
- `--encoding` applies to `.ibla` outputs and defaults to `auto`
- `--rotation`, `--samples`, and `--quality` apply to the bake run as a whole
- `--quality` accepts `low`, `medium`, or `high` and defaults to `medium`
- examples in this document use `input-image` as a generic placeholder; `--encoding auto` currently accepts HDR, EXR, PNG, and JPEG-family inputs

Fixed v1 defaults:

- `--size auto` chooses a specular size from `256 | 512 | 1024 | 2048 | 4096`
- `--size auto` uses the source image long edge and picks the largest bucket that does not exceed it
- if the source image is smaller than `256`, `--size auto` still resolves to `256`
- if the source image size cannot currently be detected, `--size auto` falls back to `512`
- irradiance face size defaults to `32`
- `--encoding auto` resolves to `rgbd-srgb` for `.hdr` and `.exr` inputs
- `--encoding auto` resolves to `srgb` for `.png`, `.jpg`, `.jpeg`, and unknown inputs
- `linear` remains available as an explicit manual choice and is not selected by `auto`
- BRDF LUT output is always `256x256`
- `--irradiance-size` remains an explicit numeric override and is not changed by `--size auto`

Encoding reference:

- `rgbd-srgb` is the default HDR-oriented export path
- `srgb` is the default LDR color-image export path for non-HDR inputs under `--encoding auto`
- `linear` remains available as an explicit manual choice for linear data payloads

The exact file-level encoding semantics are defined in `docs/format-spec.md`.

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
