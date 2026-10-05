# Private source sampling acceptance

These tools exercise production raw bake results without adding a public API,
runtime dependency, asset field, or CLI option. Run them from this repository;
they have no dependency on another checkout's scripts or results.

## Build and run

Freeze baseline commit `59af9cc` in a separate checkout/snapshot. Copy the exact
`crates/ibl_core/examples/source_sampling_export.rs` into that snapshot and build
both exporters with the same Rust toolchain and release settings:

```powershell
New-Item -ItemType Directory -Force target/source-sampling-baseline | Out-Null
git archive --format=tar --output=target/source-sampling-baseline.tar 59af9cc
tar -xf target/source-sampling-baseline.tar -C target/source-sampling-baseline
New-Item -ItemType Directory -Force target/source-sampling-baseline/crates/ibl_core/examples | Out-Null
Copy-Item crates/ibl_core/examples/source_sampling_export.rs target/source-sampling-baseline/crates/ibl_core/examples/
cargo build --locked --offline --release --manifest-path target/source-sampling-baseline/Cargo.toml --target-dir target/source-sampling-baseline-build -p ibl_cli
cargo build --locked --offline --release --manifest-path target/source-sampling-baseline/Cargo.toml --target-dir target/source-sampling-baseline-build -p ibl_core --example source_sampling_export
cargo build --locked --offline --release -p ibl_cli
cargo build --locked --offline --release -p ibl_core --example source_sampling_export
```

Use a fresh task-owned baseline directory. Install the repository's pnpm/Cargo
source dependencies first if offline builds are not yet provisioned. Record
`rustc -vV`, build flags and SHA-256 values of both binaries along with the exact
commands; do not rebuild either executable during paired measurements.

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

`--self-check` also exercises saved-generation integrity with tiny temporary
fixtures under `target/`, cleaned on exit: a valid record, missing schema/producer
identity, unsupported schema and invalid producer hash, cross-case producer
mismatch, an extra unrecorded mip, changed raw bytes and a missing recorded file.
It does not bake, build or leave Python caches or fixtures under `scripts/`.

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

The report also contains independent diagnostics for the generated analytic
signals. All six mip0 raw face files are compared bitwise between baseline and
candidate. The directional source is `L(d)=0.5+0.5*d`; its **normalized cosine**
convolution is exactly `0.5+n/3`. This is the normalized N=V GGX prefilter kernel
at roughness 1 and validates only this known continuous signal/kernel. It is
not an exact reference for full physical BRDF material rendering, and the
reported error also includes discretized source projection and output-grid
reconstruction. A small increase against this analytic reference is a real
deterministic change, even when a tone-mapped contact sheet looks unchanged.

The directional report additionally constructs ideal final-mip faces using exact
`0.5+d/3` values at texel centers, with each method's actual tail size and stored
orientation. It reconstructs these ideal faces at the same 4096 directions with
the same common sampler. This tail-only model isolates output-grid interpolation
without baking, source mips or FIS. The report compares its error to the closed
form and the actual output to the ideal tail. These RMSEs cannot be added or
subtracted to attribute the full production error: approximation errors may
cancel or compound.

Directional outputs at roughness 0.05 and 1 are fitted to constant/x/y/z RGB
coefficients; a positive dominant diagonal supports unchanged axis orientation
for this signal. Lamp peaks at roughness 0.05 are compared on a 31x31 local
angular grid, +/-4.5 degrees and a 0.3-degree step. The report preserves peak
locations and linear luminance ratios. Equal grid locations do not establish a
bound on sub-grid displacement.

Reanalysis verifies generation schema 1, canonical producer/source SHA-256
identities, input/size/sample identities, every output hash, and the exact
directory inventory excluding its root `generation.json`. Extra unrecorded raw
faces cannot enter analysis. Each method's producer hash must remain constant
across the selected matrix. Supplying an exporter argument in `--analyze-only`
also requires that binary's hash to match. `--analyze-only` does not need to rebuild exporters or
rebake; it verifies recorded producer hashes rather than requiring those old
executables to remain present. Changing this analysis script updates the report's
analysis-tool hash, but does not invalidate generation caches: those are keyed
by input, producer executable, size, samples and generation schema. A changed
exporter or input invalidates the corresponding bake cache during normal runs.

## Production-process performance

Build independent baseline and candidate release CLI binaries using the same
Rust toolchain and flags. Record the build commands, commit/source identity and
binary hashes: the benchmark's toolchain inventory describes the host at
measurement time, and cannot prove how prebuilt executables were compiled.

After the quality and performance runs have finished, the optional build recheck
records actual commands, logs, helper/source/config hashes and before/after
binary hashes:

```powershell
python scripts/source-sampling/build_provenance.py
```

It refuses an in-progress default benchmark. `target/source-sampling-checks/
build-provenance.json` identifies this as a post-measurement cache-preserving
recheck, not an original compilation log. It binds the rechecked producers to
saved measurements only when builds are up to date, sources and binary bytes
stay unchanged, and historical quality/benchmark hashes match. Initial builds
should still retain their own command logs; a recheck is not a replacement for
those historical records.

```powershell
python scripts/source-sampling/benchmark.py --baseline target/source-sampling-baseline-build/release/ibl-baker.exe --candidate target/release/ibl-baker.exe --pisa fixtures/inputs/pisa.hdr --qwantani target/ibl-comparison/inputs/qwantani_noon_puresky_1k.hdr --cube target/source-sampling-quality/inputs/six-face-lamps/512
```

The matrix covers specular 256/512 for Pisa, Qwantani and the rotated six-face
input, irradiance at source size 512 for Qwantani and the same cube, plus the
ungated odd-size 255 diagnostic. CLI rotation is **37 degrees**. All runs use
`high`, 1024 samples, both output formats, four Rayon threads, and the same local
disk. Each version has two warmups, followed by seven alternating paired rounds;
input/output caches are warm and each version overwrites its own output files.
Avoid concurrent builds/bakes and CPU or disk intensive work during measurement.

Windows starts each process suspended, assigns it to an otherwise empty Job,
then resumes and waits for exit. `PeakProcessMemoryUsed` is retained by the Job
after process exit, so short allocation peaks are included. This is OS-accounted
peak committed memory, not sampled working set, Python memory or total system
RAM. The timer includes process creation, Job assignment, loading, bake,
encoding, writes and CLI logging. The same launch overhead applies to both
versions; it is not subtracted from the user-visible end-to-end measurement.

`benchmark.json` includes every command and paired order, UTC times, processor,
OS and toolchain inventory, source/build-config snapshots, input and binary
hashes, per-run seconds and absolute committed bytes, median ratios and noise
diagnostics. End-of-run checks detect changed inputs, source or executables.
Each case independently requires time ratio <=1.05 and memory ratio <=1.10.
A deterministic 2000-resample paired bootstrap is a noise diagnostic, not proof
of independent samples. A threshold-straddling interval produces
`needs_15_rounds`; rerun affected IDs with `--rounds 15 --case CASE-ID` and the
same output directory. Verified unchanged provenance preserves the other cases.
If uncertainty remains, `acceptance_status` is `uncertain` and `passes` is false.
Nonstandard threads/warmups cannot satisfy the phase acceptance protocol.

## Diagnostic stage profiling

```powershell
python scripts/source-sampling/profile.py --input fixtures/inputs/pisa.hdr --size 512
python scripts/source-sampling/profile.py --input target/source-sampling-quality/inputs/six-face-lamps/512 --size 512 --rotation 37 --output target/source-sampling-stages-cube
```

This copies production sources into task-owned `target/` directories, inserts
temporary timing guards and builds private CLIs offline. Tracked code and
shipped logs remain unchanged. `stages.json` schema 2 stores results under
`cases.baseline` and `cases.candidate`, including original and instrumented
source hashes, build/run commands, executable/log hashes and toolchain inventory.

Timers separately report source image loading, projection, source mip building,
border-cache construction, filtering, PNG encoding and KTX2 encoding. Projection
excludes six-face input border preparation; `border_cache` includes those input
rings and all source-mip rings. Filtering includes its direction/kernel cache
preparation. Stages aggregate all invocations, including the separate bakes
performed by the current CLI's `both` path. Startup, outer validation/manifest
construction, output writes and logging overhead remain in the separately
recorded total process time. Timing guards add overhead; these single runs are
diagnostics and must not replace uninstrumented paired performance acceptance.
