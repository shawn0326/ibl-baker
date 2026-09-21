# Rust/CLI 0.2.3

Date: 2026-09-21

Correct KTX2 BC6H UFLOAT output to write the Vulkan format value `143`. Earlier versions incorrectly wrote `131`, which identifies BC1 RGB UNORM, even though the DFD and payload contained BC6H data. Consumers should regenerate KTX2 assets when practical or use `@ibltools/ktx2-loader` 0.3.0 for restricted legacy-file compatibility.

The Rust crates retain their coordinated versioning. Baking behavior and the IBLA v1 contract are unchanged.
