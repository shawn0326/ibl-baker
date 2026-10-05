# Source Sampling Phase Two Acceptance

This stage fixes artificial cubemap face boundaries and incomplete odd-size
source mip coverage. Correctness is established by deterministic analytic and
area-coverage tests. Actual cmgen v1.77.2 outputs provide an engineering
comparison; neither cmgen agreement nor the existing finite-sample Rust filter
is treated as general physical ground truth.

All analytic, scoped visual and individual-case performance gates pass. The
existing Linux Quality and Windows/macOS compilation CI also pass; the final
documentation/tool update is checked again on the PR before handoff.

## Implementation and scope

- `ae83f6c`: complete odd-size cube-UV box coverage with precomputed separable
  overlap weights and f64 accumulation. Even reductions retain the original
  four-pixel f32 operations and bitwise results. Sizes remain
  `max(1, floor(current / 2))`.
- `9790a25`: shared face geometry and seamless bilinear/trilinear source
  sampling. Each level caches only a `4N + 4` pixel ring per face; neighboring
  edges preserve orientation and corner entries average three incident faces.
  Six-face resampling prepares its input ring once. Interior samples read the
  original face pixels directly.

The caches are private, excluded from texture encoding and BakeReport pixel
counts. Projection conventions, latlong wrapping/clamping, FIS LOD, GGX sample
budgets, output roughness mapping, BRDF LUT, public APIs, CLI options and asset
contracts are unchanged. Source mip filtering remains ordinary UV box
filtering. Solid-angle weighting is a separate future stage.

The original faults are observable from their sampling/coverage definitions:
face-clamped bilinear footprints cease to agree across an artificial cube
edge, while `3 -> 1` previously selected only four of nine source pixels.
The new tests cover the neighboring-face limits and the complete independent
rectangle integral, rather than blessing another finite-sample bake as truth.

## Deterministic correctness

All 54 core tests pass, including these stage-specific gates:

| Property | Coverage | Required result |
| --- | --- | --- |
| Seam continuity | All 12 edges and 8 corners; sizes 1, 2, 3, 4, 16, 32, 256 | At 1e-6 directional perturbation, normalized color component difference <=1e-5 |
| Orientation | Independent face bases and neighbor table; centers, axes and reversed edges | Correct face, edge orientation and half-pixel centers |
| LOD | Integer, fractional and clamped values; both neighboring levels | Each level samples its own seamless borders before interpolation |
| Rotation | Independent direction field and exact quarter-turn pixel centers | Correct six-face resampling and yaw direction |
| Constant HDR | Direct sampling, source mips and complete GGX/Lambert bakes | <=2e-6 relative direct/mip error; <=2e-5 complete-filter error |
| Odd coverage | 3, 5, 6, 7, 255; boundary lights, independent rectangle integrals and whole chains | Last row/column included; constants and cube-UV area mean preserved |
| Even compatibility | Independent original f32 four-pixel reduction | Every component has identical f32 bits |
| Output compatibility | NPOT IBLA/KTX2 geometry, levels, face order, BC6H block lengths and reports | Original contracts and output-only counts preserved |

Coverage and mean preservation refer to UV area, not spherical radiometric
energy. Border copying is a finite-resolution reconstruction with residual
analytic interpolation error; continuity does not imply exact reconstruction
of every direction field. The preserved even f32 accumulation and existing
filter accumulator do not guarantee freedom from overflow for every finite
f32 input. Full-filter constant tests include HDR values up to 35000; the new
corner mean also separately tests very large finite direct-sampling values.

Actual CLI outputs for sizes 3, 5, 6, 7 and 255 were consumed by both current
TypeScript source loaders (20 files). The production PNG BRDF LUT is identical
between baseline and candidate in all quality cases, SHA-256
`a219da2586e6df8b01a9f91dba637641e866f16c7d8081c21b477326b0326084`.

## Quality experiment

The frozen baseline is `59af9cc5cacebb16b0f4243b85384a0f8d8651c8`.
Both Rust raw exporters were built with Rust 1.98.0 release settings using the
same exporter logic (the archived helper differs only in formatting). The
actual Windows cmgen v1.77.2 binary SHA-256 is
`4151702aa949a081809c3d775250c01dafb76d98ac9830882a7b610815a100e3`.
No comparison depends on scripts or data in another worktree.

The full matrix covers constant color, analytic direction color, edge/corner
lights, Pisa, Footprint Court and Qwantani at 256 and 512, with actual roughness
0.05, 0.2, 0.5, 0.7 and 1. Rust uses its actual linear roughness-to-LOD mapping;
cmgen uses its actual `r * (2 - r)` mapping and minimum 16-pixel face.
cmgen's no-mirror panorama convention is aligned by direction `(z, y, x)`.

Unencoded Rust RGB f32 and actual cmgen PSD32 retain unclipped floating-point
radiance. All methods use the same seamless reconstruction, directions, fixed
material, exposure and baseline production LUT. Each supplies its own actual
diffuse and specular results. Reflection, metal and dielectric contact sheets,
signed linear RGB `.npy` differences, common-scale preview maps, whole-domain
errors and top-5%-reference-luminance errors are retained. Uniform probes use
4096 directions; material views use a 128-pixel orthographic sphere at yaw 35.

The analytic gates pass and review of the requested views found no new hard
seams, direction flips or missing lights. This is a scoped visual assessment,
not a claim that all environments, viewpoints or sampling budgets are covered.
Low-roughness analytic lamps retain their peak positions on the tested
0.3-degree local grid, with peak luminance ratios 0.999999632-1.000001331;
this does not constrain sub-grid displacement. Their output mip zero remains
bitwise identical. Existing rough-tail and LOD differences from cmgen remain
visible.

### Retained regressions and interpretation

The uniform-probe report retains 39 increases in distance from cmgen above its
small reporting floor. These are real changes, not all random noise. The largest
increase is Qwantani 512 at r=0.7, whole-domain relative RMSE
10.074171% -> 10.330963% (+0.256792 percentage points). Qwantani's high-energy sun
and the coarser source levels amplify a small change to boundary reconstruction.
Its low-roughness sun remains present at the same location, while medium/high
roughness differences include smooth changes and finite-sample structure.

For the direction field, r=1 also slightly worsens against the independent
normalized cosine-convolution diagnostic `0.5 + d / 3`: 12.2802% -> 12.3335%
relative RMSE. The candidate-minus-baseline RMS is only 0.064% of the baseline.
The fitted diagonal directional coefficient changes from about 0.226293 to
0.225732, with no axis swap/sign flip. This is a small attenuation change after
the coarse source lookups become seamless. The ideal tail-only model stores
exact closed-form center colors and then uses the same reconstruction. Its
1x1 tail alone differs from the continuous field by 11.292188%, versus 0.084302%
for the ideal 16x16 tail. This isolates a substantial pre-existing output-grid
limitation in this signal; source/filter and grid errors cannot be attributed
by simply adding or subtracting these metrics. cmgen retains a 16x16 tail. This
constrained analytic diagnostic does not create a general physical-reference
renderer.

Footprint's r=1 bright-region difference also increases, and Pisa differences
contain amplified low-amplitude arcs, bands and sampling patterns. The reviewed
maps do not show new visible discontinuities at cube edges. The fix changes the
discrete source reconstruction, so its error against a different complete
pipeline need not decrease everywhere. These explainable small retreats are
accepted for this stage's seam/coverage goal and remain recorded for the next
quality stage; no claim of universal visual improvement is made.

The complete per-case regression list and metrics are preserved in the local
quality report and appended below. Solid-angle-weighted source mips and existing
rough-tail/LOD differences remain outside this change.

## Performance

Every gated case passes independently. Median time ratios range from 0.89224
to 0.93179, a 6.82%-10.78% improvement, and median peak-commit ratios range from
0.99711 to 1.00318. All paired noise intervals stay below the respective gates;
no 15-pair extension is required.

| Case | Baseline s | Candidate s | Time ratio | Baseline MiB | Candidate MiB | Memory ratio | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Pisa specular 256 | 4.0916 | 3.6862 | 0.90092 | 30.160 | 30.254 | 1.00311 | Pass |
| Pisa specular 512 | 15.7744 | 14.1555 | 0.89737 | 97.883 | 98.031 | 1.00152 | Pass |
| Qwantani specular 256 | 4.0214 | 3.5880 | 0.89224 | 30.289 | 30.246 | 0.99858 | Pass |
| Qwantani specular 512 | 15.4023 | 13.7488 | 0.89264 | 97.922 | 98.066 | 1.00148 | Pass |
| Rotated cube specular 256 | 3.9367 | 3.5486 | 0.90140 | 43.227 | 43.102 | 0.99711 | Pass |
| Rotated cube specular 512 | 15.3291 | 13.7674 | 0.89812 | 110.699 | 110.902 | 1.00183 | Pass |
| Qwantani irradiance source 512 | 0.7462 | 0.6953 | 0.93179 | 67.645 | 67.859 | 1.00318 | Pass |
| Rotated cube irradiance source 512 | 0.7598 | 0.6911 | 0.90960 | 80.652 | 80.832 | 1.00223 | Pass |

The separately recorded odd-size 255 case has 3.9835 -> 3.5813 seconds
(0.89903x) and 42.734 -> 42.766 MiB (1.00073x). It is an ungated diagnostic;
these end-to-end results combine the odd-coverage fix with seamless sampling,
so they do not isolate the area-weighting cost.

The machine is Windows 10 build 19045, Intel Core i9-10940X, Rust/Cargo 1.98.0
MSVC release, with `RAYON_NUM_THREADS=4` and local output disk. Independent
uninstrumented baseline and candidate CLI executables use the same toolchain
and optimization settings. All cases use high quality, 1024 samples and both
formats; the six-face case uses an actual 37-degree rotation. Each version has
two warmups followed by seven alternating paired measurements. Every gated
case must independently meet time <=1.05x and peak commit <=1.10x; a noisy
threshold needs 15 pairs and unresolved uncertainty cannot pass.

Peak committed bytes come from Windows Job Object `PeakProcessMemoryUsed`.
Processes start suspended, join an empty Job before resuming, and the OS retains
their peak after exit. This includes short allocation peaks and measures the
production process, not Python's multi-candidate analysis allocations. Timing
includes process launch, loading, filtering, encoding, disk writes and logs.

A separate single-run instrumented diagnostic for rotated six-face 512 records:

| Stage | Baseline seconds | Candidate seconds |
| --- | ---: | ---: |
| Source image load | 0.042662 | 0.042888 |
| Projection | 0.064351 | 0.057370 |
| Source mip construction | 0.017574 | 0.017115 |
| Border cache construction | 0 | 0.002209 |
| Filtering | 14.105148 | 12.380968 |
| PNG encoding | 0.252991 | 0.258521 |
| KTX2 encoding | 0.496481 | 0.514303 |
| Total instrumented process | 15.200173 | 13.495479 |

These stage sums include both independent bakes performed by the existing
`both` path. Projection excludes input border construction; the border row
includes input and source-mip rings. Startup, validation/manifest construction
and writes account for unlisted time. Timer overhead and a single run make this
a diagnosis only; it is not substituted for the paired gate.

The separate 255 diagnostic records source mip construction at
0.005848 -> 0.009038 seconds across both output bakes, approximately 3.19 ms
extra for complete odd coverage; border construction is 1.484 ms. This is a
single instrumented observation, not a statistical cost guarantee. It is
retained in `target/source-sampling-stages-odd/stages.json` alongside the
uninstrumented paired odd-size result above.

## Reproduction and evidence

[Private acceptance tools](../scripts/source-sampling/README.md) describe frozen
baseline builds, raw exports, actual cmgen execution, input requirements,
dependencies, production benchmarks and private source instrumentation.
Large inputs, binaries and generated evidence remain ignored under `target/`.
No HDR download is added to CI and no runtime dependency is introduced.

Local evidence directories:

- `target/source-sampling-quality`: input/tool/producer/output hashes, commands,
  raw floats, contact sheets, difference maps, metrics and full quality report.
- `target/source-sampling-performance/benchmark.json`: machine/build snapshots,
  every paired command/order, timestamps, seconds, absolute peak committed bytes
  and individual-case gate/noise decisions.
- `target/source-sampling-stages/stages.json`: private stage profiling with
  original/instrumented source, binary and log hashes.
- `target/source-sampling-compatibility`: NPOT CLI outputs consumed by loaders.
- `target/source-sampling-checks/summary.json`: local repository check logs.
- `target/source-sampling-checks/build-provenance.json`: actual post-measurement
  release build commands/logs, source/config/helper hashes and executable
  identities. All four CLI/exporter builds are up to date and their bytes
  remain identical to the measured producers. This is explicitly a later
  recheck; original first-compilation stdout was not retained. Both source
  toolchains specify Rust 1.98.0, release has default opt-level 3, and no custom
  release/Rust flags were set.

Measured CLI SHA-256:

| Producer | SHA-256 |
| --- | --- |
| Baseline | `cb8ee47701229e645b9af2554fcaadbda95b5b6a4d78d6dcdeb9145bb294106f` |
| Candidate | `141ecd99484c158f8c2cdd9035399342724f23406b3f29c8fcd7c66cdfe0f208` |

Quality input SHA-256:

| Input | SHA-256 |
| --- | --- |
| Constant | `a7f9b6a4d36766b361e8831f897e2862dfaa6a860057ba9306f14bf2a7502528` |
| Direction field | `da1524440b876de041a8c91e72c4478ed55f41bf8e43cdbdf6d5946f4e14f7ce` |
| Edge/corner lights | `6466d90a17fbce4f5363d27ab4ae3fc95020217cc2efdbd06af4591395c890b1` |
| Pisa | `0b3aa24296e6a24263385ea80cd41363596de02d6c5361ac2513aa8cfe0badc6` |
| Footprint Court | `fc9c23677c92e5268d2be2b7a381cd148afbcbefc7fe20083d350e27ca85fdff` |
| Qwantani | `7b51637c363377f25bcd1df8ab679127353de7f7ee0622b046f392e822e2ec76` |

Per-face six-face input hashes and all intermediate/output hashes are in the
JSON manifests. Reanalysis verifies the exact file inventory, schema and every
saved hash, requires consistent producer identities across cases, and checks
explicitly supplied exporter binaries. Its self-check rejects additional,
modified or missing payloads and invalid or inconsistent identities.

Local validation includes format, workspace Clippy, 101 Rust tests, Windows
workspace compilation, source/TypeScript checks, release static checks, 35
release tests, CLI tests, generated fixtures, 34 loader/site tests and actual
Rust/npm archive consumers. Two POSIX signal tests are skipped on Windows;
Windows Ctrl+C coverage passes. An initial archive smoke failed because of old
same-version Cargo metadata; identical checks pass with a fresh task-owned
cache. Both initial failure and successful recovery logs remain available.

The draft [PR #23](https://github.com/shawn0326/ibl-baker/pull/23) runs the existing
Windows/macOS compilation matrix and Linux Quality checks. The
[implementation CI run](https://github.com/shawn0326/ibl-baker/actions/runs/37250727848)
passes all three checks and CI Gate on `3169a28`. Final PR checks also cover the
documentation/tool refinement before handoff. No merge or release is performed.

## Full retained uniform-probe regression list

Every recorded increase below is preserved for inspection. A lower cmgen difference alone is not physical correctness.

- directional 256 r=0.2 all: 0.845829% -> 0.875026%.
- directional 256 r=0.2 brightest_5pct_reference: 0.934203% -> 0.953558%.
- directional 256 r=0.5 all: 1.751223% -> 1.788247%.
- directional 256 r=0.5 brightest_5pct_reference: 1.527781% -> 1.560984%.
- directional 256 r=0.7 brightest_5pct_reference: 1.645347% -> 1.655278%.
- directional 256 r=1 all: 12.287065% -> 12.339191%.
- directional 256 r=1 brightest_5pct_reference: 8.319128% -> 8.361989%.
- directional 512 r=0.2 all: 0.868971% -> 0.915984%.
- directional 512 r=0.2 brightest_5pct_reference: 0.895464% -> 0.921585%.
- directional 512 r=0.5 all: 1.379496% -> 1.417351%.
- directional 512 r=0.5 brightest_5pct_reference: 1.181935% -> 1.216178%.
- directional 512 r=0.7 all: 1.279108% -> 1.287677%.
- directional 512 r=0.7 brightest_5pct_reference: 1.192300% -> 1.204061%.
- directional 512 r=1 all: 12.257963% -> 12.310561%.
- directional 512 r=1 brightest_5pct_reference: 8.301484% -> 8.345696%.
- lamps 512 r=1 brightest_5pct_reference: 14.835324% -> 14.853173%.
- pisa 256 r=0.2 brightest_5pct_reference: 0.772890% -> 0.801067%.
- pisa 256 r=0.7 brightest_5pct_reference: 3.714089% -> 3.762182%.
- pisa 256 r=1 brightest_5pct_reference: 17.544645% -> 17.569509%.
- pisa 512 r=0.2 brightest_5pct_reference: 1.449609% -> 1.482651%.
- pisa 512 r=0.7 brightest_5pct_reference: 2.923569% -> 2.929827%.
- pisa 512 r=1 brightest_5pct_reference: 18.225426% -> 18.252206%.
- footprint 256 r=0.2 all: 2.365665% -> 2.378301%.
- footprint 256 r=0.2 brightest_5pct_reference: 1.066976% -> 1.069078%.
- footprint 256 r=0.5 all: 3.250217% -> 3.259624%.
- footprint 256 r=0.7 brightest_5pct_reference: 1.820242% -> 1.824727%.
- footprint 256 r=1 all: 14.653382% -> 14.777054%.
- footprint 256 r=1 brightest_5pct_reference: 8.440763% -> 8.659120%.
- footprint 512 r=0.2 all: 2.118128% -> 2.148976%.
- footprint 512 r=0.5 all: 2.713018% -> 2.716648%.
- footprint 512 r=1 all: 14.591065% -> 14.715784%.
- footprint 512 r=1 brightest_5pct_reference: 8.896190% -> 9.118168%.
- qwantani 256 r=0.5 all: 16.966788% -> 17.080249%.
- qwantani 256 r=0.5 brightest_5pct_reference: 16.716369% -> 16.926967%.
- qwantani 256 r=0.7 brightest_5pct_reference: 9.955320% -> 10.145285%.
- qwantani 512 r=0.5 all: 11.870816% -> 12.009677%.
- qwantani 512 r=0.5 brightest_5pct_reference: 10.830224% -> 11.049278%.
- qwantani 512 r=0.7 all: 10.074171% -> 10.330963%.
- qwantani 512 r=0.7 brightest_5pct_reference: 5.467344% -> 5.567687%.

