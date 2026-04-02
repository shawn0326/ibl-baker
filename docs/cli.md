# CLI Reference

## Commands

```bash
ibl-baker bake input.hdr --out-dir ./out
ibl-baker bake input.hdr --out-dir ./out --target specular
ibl-baker bake input.hdr --out-dir ./out --target irradiance --target lut
ibl-baker validate ./out/specular.ibla
```

## `bake`

Supported v1 options:

- `--out-dir`
- `--target`
- `--size`
- `--irradiance-size`
- `--encoding rgbd`
- `--rotation`
- `--samples`
- `--quality`

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

- `--size` controls specular cubemap face size and defaults to `512`
- `--irradiance-size` controls irradiance cubemap face size and defaults to `32`
- `--encoding rgbd` applies to `.ibla` outputs
- `--rotation`, `--samples`, and `--quality` apply to the bake run as a whole

Fixed v1 defaults:

- specular face size defaults to `512`
- irradiance face size defaults to `32`
- BRDF LUT output is always `256x256`
- these defaults are fixed in v1 and do not adapt to source image size

The current implementation writes deterministic placeholder outputs that already follow this production workflow.

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
- chunk payload identity uniqueness
- payload byte ranges and overlap
- cubemap-vs-2D face usage
