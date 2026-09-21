# @ibltools/cli 0.1.1

Date: 2026-09-21

- Show the npm distribution version before the actual native CLI version for --version and -V.
- Keep npm and Rust versions independent; this release embeds Rust CLI 0.2.3.
- Correct generated KTX2 BC6H UFLOAT files to use the standard Vulkan format value `143`.
- Direct native version output and other command forwarding remain unchanged.
