# ibl-baker

A renderer-agnostic IBL asset compiler that primarily bakes HDR environments into portable `.ibla` texture payloads, with a Rust core, CLI, and future TypeScript tooling.

## Status

The repository is currently in the initialization phase.

The first milestone is to establish:

- a stable `.ibla` asset boundary
- a Rust workspace with `ibl_core` and `ibl_cli`
- a minimal command flow for multi-output baking and `.ibla` validation

## Scope

Phase one focuses on a stable, portable asset format instead of engine-specific runtime integration.
The main v1 production path is still HDR IBL baking, while `srgb` and `linear`
encoding variants exist to keep the container and CLI semantics consistent for related payload types.

Current priorities:

- define the `.ibla` container structure
- stabilize the single-file texture topology model around `mipCount` and `faceCount`
- simplify the v1 manifest around `encoding` and provenance metadata
- establish the core Rust API surface
- wire the CLI to the core library
- add validation and output workflows

Out of scope for now:

- browser-side baking
- engine adapters
- WebAssembly bindings
- alternative encodings and containers in the initial milestone
