# @ibltools/cli 0.1.0

Date: 2026-09-18

Initial npm distribution of the Rust ibl-baker CLI. The entry package selects exact-version optional platform packages for Windows x64, macOS arm64, and Linux x64/glibc (validated on Ubuntu 24.04). Node.js 24 or newer is required.

The distribution contains Rust CLI 0.2.2. Install with npm or invoke `npx @ibltools/cli --version`; the version command reports the Rust version. Installation requires no Rust toolchain, postinstall downloads, or compilation.

This release adds no JavaScript runtime API and does not change the IBLA or KTX2 formats. Keep optional dependencies enabled. See the CLI package README for system requirements and cancellation behavior.
