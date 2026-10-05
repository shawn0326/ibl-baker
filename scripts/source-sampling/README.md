# Private source sampling acceptance

These tools exercise production raw bake results without adding a public API,
runtime dependency, asset field, or CLI option. Run them from this repository;
they have no dependency on another checkout's scripts or results.

## Build and run

Freeze baseline commit `59af9cc` in a separate checkout/snapshot. Copy the exact
`crates/ibl_core/examples/source_sampling_export.rs` into that snapshot and build
both exporters with the same Rust toolchain and release settings:

```powershell
cargo build -p ibl_core --release --example source_sampling_export
```

The exporter takes `INPUT OUTPUT --size 256 --irradiance-size 32 --samples 1024`.
INPUT is a panorama, or a directory with six `px.exr`, `nx.exr`, `py.exr`,
`ny.exr`, `pz.exr`, `nz.exr` faces; `--rotation DEGREES` also works.
It exports little-endian interleaved RGB f32, actual dimensions and roughness,
and the production BRDF PNG. There is no clipping or texture encoding.
The timings in this helper include raw bake stages and exclude final encoding;
they are diagnostic and are not the production-process performance gate.

Install acceptance-only Python packages into a local target directory if needed:

```powershell
python -m pip install --target target/source-sampling-python -r scripts/source-sampling/requirements.txt
python scripts/source-sampling/quality.py --python-packages target/source-sampling-python --self-check
python scripts/source-sampling/quality.py --python-packages target/source-sampling-python --baseline-exporter target/source-sampling-baseline-build/release/examples/source_sampling_export.exe --candidate-exporter target/release/examples/source_sampling_export.exe
```

The default cmgen is `target/ibl-comparison/tools/filament-v1.77.2/bin/cmgen.exe`.
`--cmgen` can override its location; its SHA-256 must match the pinned Windows
v1.77.2 executable. Supply the official [v1.77.2 release](https://github.com/google/filament/releases/tag/v1.77.2)
binary and local inputs `fixtures/inputs/pisa.hdr`,
`fixtures/inputs/footprint_court.hdr`, and
`target/ibl-comparison/inputs/qwantani_noon_puresky_1k.hdr`. No automatic input or
binary downloads are performed. A fresh checkout can run analytic cases with
`--cases constant,directional,lamps` without the HDR fixtures.

Use `--cases pisa --sizes 256` for a subset, `--analyze-only` to reanalyze verified
saved bakes, or `--generate-inputs-only` to prepare analytic FLOAT EXRs and the
six-face lamps input for performance benchmarks. Default generated faces are in
`target/source-sampling-quality/inputs/six-face-lamps/{256,512}`.
Pass multiple `--python-packages` paths when using separately installed packages.

## Interpretation and outputs

`target/source-sampling-quality` contains tool/input/output identities and hashes,
commands and timings, `metrics.csv`, `report.json`, `report.md`, and reflection,
metal and dielectric sphere contact sheets. Each sheet uses one common exposure
and fixed material and the baseline's actual production BRDF PNG. Each method
supplies its own diffuse and specular result. Irradiance differences are also
separately reported on uniform sphere probes.
Metal F0 is `(0.95, 0.64, 0.54)`; dielectric F0 is `0.04` with base color `0.6`.
The common CPU sampler includes correct neighboring edges and three-face corners.

Actual cmgen is executed with `--no-mirror --format=psd --compression=32` to retain
full f32 values; cmgen EXR output uses HALF and can quantize or overflow HDR peaks.
Its original panorama convention is aligned by sampling direction `(z,y,x)`.
Current outputs use `LOD=r*(levels-1)` and cmgen uses
`LOD=r*(2-r)*(levels-1)`. cmgen's native minimum face size remains 16. Its actual
sampling budgets increase at later levels, so this is a mature engineering
baseline, not an equal-compute experiment or a physical ground truth renderer.

The five roughnesses are `0.05, 0.2, 0.5, 0.7, 1`. Both 4096 uniform sphere probes
and material pixels report all-direction and brightest-5%-reference errors.
Signed RGB linear HDR difference maps are saved as float32 `.npy` arrays, with
NaN outside the sphere; PNG previews share a documented logarithmic error scale.
All observed uniform-probe RMSE regressions above a small reporting floor are
retained in the report. Visual review and analytic correctness tests are still
required; a smaller difference from cmgen alone does not prove physical accuracy.
The report deliberately does not mark phase two complete or replace the separate
production-process performance acceptance.
