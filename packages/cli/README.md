# @ibltools/cli

Install the prebuilt Rust `ibl-baker` CLI through npm. Node.js 24 or newer is required; Rust is not required.

```sh
npx @ibltools/cli --version
npm install --save-dev @ibltools/cli
npx ibl-baker bake environment.hdr --out-dir ./out --output-format both
npm install --global @ibltools/cli
ibl-baker --help
```

The command is `ibl-baker`. Arguments, working directory, environment, standard streams and normal exit codes are forwarded to the native executable. `--version` reports the **Rust CLI version**, independently of the npm distribution version (inspect it with `npm ls @ibltools/cli`). No JavaScript runtime API is exported.

## Platforms

| Node platform / architecture | Package | Validation baseline |
| --- | --- | --- |
| win32 / x64 | @ibltools/cli-win32-x64 | Windows GitHub-hosted runner |
| darwin / arm64 | @ibltools/cli-darwin-arm64 | macOS 14 |
| linux / x64, glibc | @ibltools/cli-linux-x64-gnu | Ubuntu 24.04, including libstdc++6 |

Older Linux distributions, Alpine/musl, Linux arm64, Intel macOS and Windows arm64 are not supported in this release. Selection follows Node's architecture; x64 Node under Rosetta does not select the arm64 package. Linux binaries dynamically link system libraries, including libstdc++; the package does not bundle them.

Platform packages are exact-version optional dependencies. Keep optional dependencies enabled. Installation does not download binaries from GitHub, compile code, or run lifecycle scripts; `--ignore-scripts` is supported. If a platform package is missing, reinstall with `npm install --include=optional`. Copying node_modules between operating systems is unsupported.

Ctrl+C stops the running bake. Unix SIGINT/SIGTERM are forwarded; Windows cancellation returns a nonzero status and does not promise POSIX signal semantics. Force-killing the launcher is outside this cancellation contract.

For baking options and formats, see the [native CLI documentation](https://github.com/shawn0326/ibl-baker/blob/master/crates/ibl_cli/README.md).

## Development and release

This workspace package is private. Release scripts stage a public entry package and three platform packages under `target`, injecting exact optional dependencies and binary-version metadata. Publish reviewed archives through the repository release workflow, not directly from this directory. See the [release guide](https://github.com/shawn0326/ibl-baker/blob/master/docs/release.md).
