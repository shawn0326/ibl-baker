# Release Process

This document covers the manual registry publish steps and the tag-driven GitHub Release flow for `ibl-baker` v1 packages.

## Versioning

For a new public release:

- update `[workspace.package].version` in the workspace `Cargo.toml`
- update the workspace crate dependency versions in `crates/*/Cargo.toml`
- update public package versions in `packages/ibla-loader/package.json` and `packages/ktx2-loader/package.json`
- update private viewer package versions when keeping the full workspace on one release version

The current KTX2 and `.ibla` loader release uses `v0.2.0`.
The initial public release used `v0.1.0`.

## Preflight Checks

Run these commands from the repository root before publishing:

```bash
cargo test --workspace
cargo check --workspace
npm test --workspaces
npm run check:ts
npm pack --dry-run -w @ibltools/ibla-loader
npm pack --dry-run -w @ibltools/ktx2-loader
```

Before the real publish, confirm:

- the crates.io token is configured locally
- the npm token is configured locally
- the target package names are still available or already owned by the release account

For the npm packages, verify the package names before publishing:

```bash
npm view @ibltools/ibla-loader name
npm view @ibltools/ktx2-loader name
```

If a package does not exist yet, npm returns a not-found error. If it exists, confirm the release account owns or can publish to it.

## Publish Order

Registry publishing stays manual.
Publish in this order:

```bash
cargo publish -p ktx2_writer --dry-run --allow-dirty
cargo publish -p ktx2_writer

cargo publish -p ibl_core --dry-run --allow-dirty
cargo publish -p ibl_core

cargo publish -p ibl_cli --dry-run --allow-dirty
cargo publish -p ibl_cli

npm publish -w @ibltools/ibla-loader --access public
npm publish -w @ibltools/ktx2-loader --access public
```

Wait until `ktx2_writer` is visible on crates.io before rerunning the `ibl_core` dry run and publishing `ibl_core`.
Wait until `ibl_core` is visible on crates.io before rerunning the `ibl_cli` dry run and publishing `ibl_cli`.

After `@ibltools/ibla-loader` is published successfully, manually deprecate the old package name:

```bash
npm deprecate @ibltools/loader "Package renamed to @ibltools/ibla-loader. Please install @ibltools/ibla-loader instead."
```

## Git Tag And Release

GitHub Release binaries are built automatically from tags matching `v*`.

Create and push the version tag after the registry publishes complete:

```bash
git tag v0.2.0
git push origin v0.2.0
```

The release workflow builds `ibl-baker` for:

- Windows x64
- macOS arm64
- Linux x64

Expected asset names:

- `ibl-baker-v0.2.0-windows-x64.zip`
- `ibl-baker-v0.2.0-macos-arm64.tar.gz`
- `ibl-baker-v0.2.0-linux-x64.tar.gz`

The workflow creates or updates the GitHub Release for the tag and uploads those archives as release assets.

## Release Notes

Use the tag as the release title and keep the notes short.
Recommended structure:

```text
Highlights
- summarize the public CLI scope
- summarize the `.ibla` loader scope
- summarize the KTX2 loader scope

Install
- cargo install ibl_cli
- download a prebuilt binary from the release assets

Packages
- crates.io: ktx2_writer, ibl_core, ibl_cli
- npm: @ibltools/ibla-loader, @ibltools/ktx2-loader
```

## Post-Release Verification

After the tag workflow completes, verify:

- the GitHub Release exists for the pushed tag
- all three binary archives are attached
- archive names match the documented convention
- the CLI README install instructions still match the released assets
- the published crate and npm package versions match the tag version
- `npm view @ibltools/loader deprecated` shows the rename message
- `npm view @ibltools/ibla-loader version` shows the published version
- `npm view @ibltools/ktx2-loader version` shows the published version
