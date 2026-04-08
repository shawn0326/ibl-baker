# Release Process

This document covers the manual registry publish steps and the tag-driven GitHub Release flow for `ibl-baker` v1 packages.

## Versioning

For a new public release:

- update `[workspace.package].version` in the workspace `Cargo.toml`
- update `packages/loader/package.json`
- keep `packages/e2e-loader/package.json` aligned with the published loader version because it depends on `@ibltools/loader`

The initial public release uses `v0.1.0`.

## Preflight Checks

Run these commands from the repository root before publishing:

```bash
cargo test --workspace
cargo check --workspace
cargo publish -p ibl_core --dry-run --allow-dirty
cargo publish -p ibl_cli --dry-run --allow-dirty
npm test --workspaces
npm run check:ts
npm pack --dry-run -w @ibltools/loader
```

`cargo publish -p ibl_cli --dry-run --allow-dirty` depends on `ibl_core` already being available on crates.io for the target version.
If that version of `ibl_core` has not propagated yet, publish `ibl_core` first, wait for the index to update, then rerun the `ibl_cli` dry run.

Before the real publish, confirm:

- the crates.io token is configured locally
- the npm token is configured locally
- the target package names are still available or already owned by the release account

## Publish Order

Registry publishing stays manual.
Publish in this order:

```bash
cargo publish -p ibl_core
cargo publish -p ibl_cli
npm publish -w @ibltools/loader --access public
```

Wait until `ibl_core` is visible on crates.io before rerunning the `ibl_cli` dry run and publishing `ibl_cli`.

## Git Tag And Release

GitHub Release binaries are built automatically from tags matching `v*`.

Create and push the version tag after the registry publishes complete:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The release workflow builds `ibl-baker` for:

- Windows x64
- macOS arm64
- Linux x64

Expected asset names:

- `ibl-baker-v0.1.0-windows-x64.zip`
- `ibl-baker-v0.1.0-macos-arm64.tar.gz`
- `ibl-baker-v0.1.0-linux-x64.tar.gz`

The workflow creates or updates the GitHub Release for the tag and uploads those archives as release assets.

## Release Notes

Use the tag as the release title and keep the notes short.
Recommended structure:

```text
Highlights
- summarize the public CLI scope
- summarize the `.ibla` loader scope

Install
- cargo install ibl_cli
- download a prebuilt binary from the release assets

Packages
- crates.io: ibl_core, ibl_cli
- npm: @ibltools/loader
```

## Post-Release Verification

After the tag workflow completes, verify:

- the GitHub Release exists for the pushed tag
- all three binary archives are attached
- archive names match the documented convention
- the CLI README install instructions still match the released assets
- the published crate and npm package versions match the tag version
