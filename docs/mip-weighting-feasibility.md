# Solid-angle source-mip feasibility study

Date: 2026-10-05. Frozen baseline: `3fafed3598374e8be47922069576a558e224fcaf`.

## Decision

The bounded feasibility study is complete. Keep the production cube-UV box mip
policy. The private weighted candidate preserves the discrete solid-angle
integral, but the pilot does not establish the required repeatable quality gain.
It also contains qualified local regressions. Much of the real HDR reference
remains unresolved within the agreed integration budget.

This is a decision against adopting this isolated candidate on the available
evidence, not proof that all solid-angle filtering is inferior. Source projection,
FIS LOD, production kernels and sample budgets, output roughness/tail layout,
encoding, public interfaces and BRDF LUT were held fixed. No production source or
runtime dependency changes are included.

## Engineering and mathematical controls

Two independent release CLI executables and private probe exporters were built
from a Git archive of the frozen baseline with identical flags and helpers. Only
the candidate source-mip builder body differs. Its weights integrate spherical
rectangles intersecting the destination footprint, using
`atan2(u*v, sqrt(1+u*u+v*v))`. Weights and accumulation use f64, stored pixels use
f32, dimensions retain `max(1, floor(current/2))`, and seamless borders are rebuilt
for every layer. The executable used for compatibility is the uninstrumented CLI.

Six private Rust tests cover dimensions 1, 2, 3, 4, 5, 6, 7, 16, 32, 255 and 256:
positive weights, total solid angle `4*pi`, full coverage including odd trailing
rows/columns, constant and discrete-integral preservation, independently
integrated rectangle controls, all twelve edges/eight corners, fractional LOD,
constant filtering and fixed proposal counts. These properties validate the
candidate implementation, not its rendered quality.

In the eight size-256 pilot inputs, the candidate's maximum per-channel relative
change in `sum(L*Omega)` across all source levels was below `8.2e-8`. This sum
treats mip texels as piecewise constant cells. It does not establish conservation
of the continuously reconstructed source, a convolution, or a material render.

cmgen v1.77.2 constructs box-filtered source levels and seamless borders; its
four-texel helper uses an equal-weight average. Its FIS implementation explicitly
associates the `K=4` LOD bias with box filtering. These are useful engineering
controls, without establishing the authors' reasons for not choosing weighted
mips. See the pinned [cmgen mip construction](https://github.com/google/filament/blob/v1.77.2/tools/cmgen/src/cmgen.cpp#L707-L722),
[box downsample call](https://github.com/google/filament/blob/v1.77.2/libs/ibl/src/CubemapUtils.cpp#L73-L82),
[four-texel mean](https://github.com/google/filament/blob/v1.77.2/libs/ibl/src/Cubemap.cpp#L191-L201)
and [FIS implementation](https://github.com/google/filament/blob/v1.77.2/libs/ibl/src/CubemapIBL.cpp#L230-L249).
No new cmgen bake is claimed by this study.

## Pilot and independent reference

The pilot uses constant and affine direction fields, a direction field rotated
37 degrees, separate 1.2-degree Gaussian lamps at face center/edge/corner, Pisa
and Qwantani. Each case uses 117 fixed directions: 64 uniform, 26 axes/edges/corners
and 27 lamp-neighborhood probes. GGX roughnesses are 0.05, 0.2, 0.5, 0.7 and 1;
Lambert is evaluated separately. Both 256 and 1024 proposal budgets are used.
Actual f32 directions, roughness bits and accepted GGX light counts are recorded.
These proposal counts do not describe the CLI's adaptive per-output-mip budget.

All paired mip0 data and query identities are bitwise identical. The primary
target is the immutable shared mip0 reconstructed with seamless bilinear
sampling. Independent NumPy f64 integration evaluates the normalized N=V GGX
prefilter and normalized Lambert convolution without source mips, FIS or
production Hammersley samples. This is not a complete physical BRDF renderer.
The separate continuous affine-field diagnostic includes projection error.

The reference uses four Gauss-Legendre/periodic-azimuth levels, 32x64 through
256x512, with two azimuth phases. Both final successive changes and phase
agreement must meet a relative `1e-4` diagnostic tolerance. At up to eight
sensitive directions per HDR, independent adaptive source cube-UV integration
checks the union of selected bright/high-gradient support and its interpolation
halo. It does not certify every other HDR feature. A shared 60-second item limit,
depth six and 100,000-node local limit prevent unbounded retries; the pilot has a
30-minute reference budget. Limits and disagreement remain uncertain.

The 48 primary reference files contain 5,616 probe queries and used 609.79 seconds
of reference computation. This duration is a research-tool diagnostic, not a
production performance measurement. Primary convergence alone is insufficient
when a required HDR local check is unresolved. Examples of primary convergence:

| Input | GGX .05 | GGX .2 | GGX .5 | GGX .7 | GGX 1 | Lambert |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Pisa | 37/117 | 2/117 | 0/117 | 0/117 | 0/117 | 0/117 |
| Qwantani | 99/117 | 53/117 | 43/117 | 39/117 | 39/117 | 39/117 |

Constant, direction and rotated-direction primary references converged at every
probe. The saved HDR subset metrics are diagnostics; they must not be presented
as whole-image errors or as a qualified gain after discarding difficult probes.

## Quality gate and retained regressions

The analyzer verifies inputs, snapshots, binaries, raw inventories, kernels,
directions and reference hashes, then recomputes metrics over every fixed probe.
It reports each group and its reference-defined brightest five percent; an
additional all-probe scope can reveal regressions but cannot supply gain witnesses.
The empirical reference spread is the maximum of phase differences, the final
two phase-wise level changes, normalizer diagnostics and required local
differences. Its group RMS is `E`; the paired RMSE-difference envelope is `2*E`.
These diagnostics are not rigorous error bounds.

Expansion requires at least a five-percent relative RMSE reduction exceeding
five times that difference envelope at two roughnesses under both budgets, in
at least two nonconstant cases including an HDR. Any qualified nonconstant row
whose regression exceeds five envelopes blocks expansion, even at one budget.
Missing or uncertain required reference scopes also prevent a positive decision.

The final classification is `evidence_insufficient`, with expansion disabled.
Of 5,616 reference queries, 3,420 qualify and 2,196 remain unresolved. There are
768 metric rows: 312 qualified and 456 unqualified. Eleven individual rows meet
the gain threshold, but no case supplies the required repeated gain. Fifteen
qualified stable retreat rows block expansion; all 176 observed diagnostic
retreat rows remain recorded. These counts include overlapping groups/regions.
The complete row-level results,
including unqualified diagnostic regressions and their reasons, are retained in
`target/mip-weighting/pilot/analysis.json`, `analysis.md` and `metrics.csv`.
Overlapping groups and bright regions are not independent scene observations.
The unresolved HDR integrals are a limitation of this bounded study; they are
neither evidence of improvement nor evidence that the candidate is wrong.

A supplemental continuous Gaussian control makes a useful tradeoff independently
visible. At the face-center normal `(1,0,0)`, a segmented one-dimensional angular
integral uses orders 32/64/128 around analytically known lamp/kernel scales. Its
maximum successive RGB component change is `1.14e-13`, and closed-form normalizer
relative error is at most `1.06e-15`. Constant, rotation, narrow/wide limits and
roughness-one GGX/Lambert equivalence checks pass. The control includes common
source projection/reconstruction and finite production sampling; it is separate
from the shared-mip0 gate and does not certify general material rendering.

| Kernel | Roughness | Proposals | Box RGB RMS error | Weighted RGB RMS error | Weighted/box |
| --- | ---: | ---: | ---: | ---: | ---: |
| GGX | .2 | 256 | 6.12918359 | 5.97222815 | .974392 |
| GGX | .2 | 1024 | 1.16648440 | 1.21085514 | 1.038038 |
| GGX | .5 | 1024 | .06934106 | .02419680 | .348953 |
| GGX | .7 | 1024 | .08867573 | .03699111 | .417150 |
| GGX | 1 | 1024 | .10644096 | .03830957 | .359914 |
| Lambert | 1 | 1024 | .02879623 | .00214603 | .074525 |

At roughness .2/1024, relative RGB RMSE rises from 2.672804% to 2.774472%, a
3.8038% relative increase in error. Higher-roughness central results improve
substantially. All twelve controls, component errors and convergence traces are
retained in `target/mip-weighting/analytic-lamp/report.json`. The result depends on
roughness and budget; it does not justify a general claim about all face-center
lights. Treating weighted cell averages as a drop-in improvement for the fixed
bilinear/FIS reconstruction is therefore unsupported by this experiment.

## Compatibility, validation and skipped stages

Four small native CLI cases (constant, clipped constant, rotated direction and
odd size three) run with both formats, specular, irradiance and LUT. Twelve bakes
cover current production, archived box and the private candidate. Production and
archived box output bytes, warning reports and normalized summaries agree.
Actual TypeScript consumers confirm equal dimensions, levels, ordered faces,
chunks and output pixel counts. All LUT bytes agree. The clipped case reports
2,046 specular and 96 irradiance IBLA pixels; borders are excluded. EXR writer
inputs are contiguous RGB arrays. An initial noncontiguous compatibility fixture
was corrected in the tool and its failed local generation retained; it was not
a production defect.

Local checks passed: production Cargo formatting, strict workspace Clippy, 101
Rust tests, source syntax/type checks, 34 loader/site tests with CI fixtures, and
five Windows CLI tests (two POSIX tests skipped). The box snapshot passed 60 core
tests, including the six private tests; the weighted snapshot passed those six.
The existing box UV-mean assertion is not applicable to a weighted chain. Both
private snapshots pass formatting and Clippy with the documented `dead_code`
exception for unreachable box helpers. Production Clippy has no such exception.
The independent reference passed 49 self-checks and mathematical review. The
analyzer passed 21 integrity/qualification self-checks, including incomplete
matrices, malformed local checks, zero denominators, numeric overflow, changed
hashes and unexpected output files. Independent review verified snapshot
isolation, saved Gaussian inputs, formulas and final qualification rules.

The gate stops expansion. Size-512 confirmation, new full cmgen/Footprint Court
and material images, and the production performance matrix were **not evaluated**.
No time or memory threshold is claimed from compatibility bakes or research-tool
memory. In particular, the phase-two performance pass does not qualify this
candidate. The original per-scene 1.05x time and 1.10x OS peak committed-memory
thresholds remain required if a future candidate merits expansion.

Existing output-tail/LOD differences documented in the
[phase-two report](source-sampling-acceptance.md) remain unresolved. The separate
`--samples < 8` underflow item also remains in TODO; this study did not modify it.

## Reproduction and evidence identity

Commands, dependency requirements, numerical scope and cache rules are in the
[private tool README](../scripts/mip-weighting/README.md). All generated inputs,
snapshots, raw floating-point data, build logs and native outputs stay under the
ignored `target/` tree. Pisa is read from the existing repository fixture;
Qwantani is read from the existing local input cache. No other worktree or CI HDR
download is required.

Prepared generation: `28967e50eca72eabaaf9`, Windows x86_64 MSVC,
Rust/Cargo 1.98.0, four Rayon threads. The manifests retain the exact build flags,
toolchain text, environment, complete source/output inventories and input hashes.

| Evidence | SHA-256 |
| --- | --- |
| Preparation manifest | `d86a4358d8983f4628a05a15b77f3ed4e80b9f0e05c8fc48dc61f7aed516b955` |
| Frozen Git archive | `b9a44a9e7a54d4d6f710a1cc2a87ff53f2563b2b0dae79ba008d6dc01e1f58cc` |
| Candidate-only patch | `e21a39112b4b7e6742f403884990f96605e12df1cf5c703f5e584fe973b5f82b` |
| Pilot screen manifest | `5753d65dc69243a0bc0fbf56e9d5d914d297cb304fd3e53b4880718b73f192a7` |
| Final pilot analysis | `a2727348dadb7ecc9d7f04a9131b1a8c62e27d0dc1617061271364b167ccd332` |
| Compatibility manifest | `252fd67cc2b309ca74c7b4aa656e4d86b68e7d91bbe87c7ec7cf7f19340d9176` |
| Continuous lamp report | `8f88efe0c7ad3aa344526c60302ac6955cbbdf0d2e7c703d9d51cce0284fdd26` |

The production policy stays box. Reopening this direction requires new
reproducible evidence and a separately scoped study of mip footprints and FIS
reconstruction, followed by the skipped quality and performance checks. Improved
discrete cell sums alone are not a reason to schedule adoption.
