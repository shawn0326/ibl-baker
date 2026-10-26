# @ibltools/cli 0.2.0

Date: 2026-10-26

This four-package npm distribution embeds Rust CLI 0.3.0 and includes its new
`--specular-min-size` option, shared multi-format baking, source-filtering fixes,
low-sample handling, range warnings and bake time/memory improvements. The
entry package and all three native platform packages use version 0.2.0 with
exact-version optional dependencies.

Install with `npm install @ibltools/cli@0.2.0`, or run
`npx @ibltools/cli@0.2.0 --help`. Keep optional dependencies enabled. Node.js 24
or later is still required; installation needs no Rust toolchain or postinstall
download, and supports `--ignore-scripts`.

`ibl-baker --version` and `-V` report both versions:

```text
@ibltools/cli 0.2.0
ibl-baker 0.3.0
```

The default remains a complete specular mip chain. Existing CLI invocations and
parser-only loader APIs remain available. Consumers must use the actual supplied
mip count and upload every baked level without generating replacement mips.
Explicit shorter chains are freshly rebaked over the full roughness range.
Successful jobs may now report clipped RGB values on stderr while retaining exit
code zero. Regenerated pixels may differ from the earlier native version;
existing assets are not automatically rewritten.

See the [Rust/CLI 0.3.0 notes](https://github.com/shawn0326/ibl-baker/releases/tag/v0.3.0)
for the complete native changes and the
[runtime contract](https://github.com/shawn0326/ibl-baker/blob/v0.3.0/docs/runtime-contract.md)
for texture consumption.
