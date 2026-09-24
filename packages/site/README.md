# @ibltools/site

`@ibltools/site` is the private browser application deployed to the project's GitHub Pages site.
It provides a local, drag-and-drop validation entry point for `.ibla` and `.ktx2` assets.
Files are processed in the browser and are not uploaded.

## Development

From the repository root:

```bash
pnpm install
pnpm run dev:site
```

Open <http://127.0.0.1:4175/> and drop an `.ibla` or `.ktx2` file.

Build and test the site with:

```bash
pnpm run test:site
```

The site does not load repository fixtures directly. KTX2 preview requires WebGPU with
`texture-compression-bc`; browsers without that capability can still parse the file and
display its metadata and mip layout.

## Contracts

This private application is not a published runtime package and does not define a new file
format or loader API. Refer to the format-specific sources of truth:

- [`@ibltools/ibla-loader`](../ibla-loader/README.md) for the `.ibla` parser API
- [`@ibltools/ktx2-loader`](../ktx2-loader/README.md) for the supported KTX2 parser profile
- [`ibl-baker` CLI README](../../crates/ibl_cli/README.md) for CLI output behavior
- [`.ibla` format specification](../../docs/format-spec.md) for the binary container contract
