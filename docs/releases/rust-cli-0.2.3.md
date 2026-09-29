# Rust/CLI 0.2.3

Date: 2026-09-29

Correct KTX2 BC6H UFLOAT output to write the Vulkan format value `143` and the standard Khronos data format descriptor with a normalized sample range of `[0, 1]`. Earlier versions incorrectly wrote `131`, which identifies BC1 RGB UNORM, and used a non-standard descriptor even though the payload contained BC6H data. Consumers should regenerate KTX2 assets when practical or use `@ibltools/ktx2-loader` 0.3.0 for restricted legacy-file compatibility.

The Rust crates retain their coordinated versioning. Baking behavior and the IBLA v1 contract are unchanged.
