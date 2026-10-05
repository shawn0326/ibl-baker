# Private solid-angle mip feasibility experiment

This experiment asks whether replacing cube-UV box source mips with solid-angle
averages improves the existing filter. It **does not change production defaults**.
The shipped Rust source, CLI options, asset formats, sampling budgets, source
projection, FIS LOD, output mip layout and BRDF LUT remain unchanged.

The baseline is the phase-two merge `3fafed3598374e8be47922069576a558e224fcaf`.
The pinned cmgen v1.77.2 source uses box mips and a box-related FIS LOD bias;
its choice does not establish why a different mip policy was not adopted.

## Requirements and preparation

Use the repository's Rust toolchain and offline Cargo cache. Python requires the
same acceptance-only NumPy, OpenEXR and Pillow packages as the
[phase-two tools](../source-sampling/README.md). These are not runtime dependencies.
Supply the existing local Pisa and pinned Qwantani HDR inputs documented there.
No CI download of HDR data or cmgen is added.

Run from the repository root:

```powershell
python scripts/mip-weighting/prepare.py
```

`prepare.py` archives the frozen Git commit, creates content-addressed snapshots
under `target/mip-weighting/prepared/`, injects identical private Rust helpers and
an exporter, and replaces only the candidate source-mip builder body. It builds
two independent release CLI binaries and probe exporters with the same flags.
`target/mip-weighting/preparation.json` records the actual patch, source inventory,
helper and executable hashes, toolchain, build environment, commands and logs.
Reusing a cache verifies its complete inventory and all recorded hashes.

The box snapshot runs all core library tests. The candidate runs the six
`mip_weighting_` tests; the existing test asserting cube-UV mean preservation
belongs to the box policy and is not applicable to a weighted chain. Both private
Clippy runs use `-D warnings -A dead_code`, explicitly allowing the box helpers
that become unreachable in the candidate. Production Clippy remains strict.

Weights use the exact spherical rectangle primitive
`atan2(u*v, sqrt(1+u*u+v*v))`, intersect each destination footprint with source
cells, and are computed once per layer and reused across six faces. Accumulation
is f64; pixels remain f32. Dimensions retain `max(1, floor(current/2))` and the
existing seamless borders are rebuilt for each resulting level.

## Compatibility and bounded pilot

```powershell
cargo build --locked --offline --release -p ibl_cli
python scripts/mip-weighting/compatibility.py --python-packages target/ibl-comparison/python
python scripts/mip-weighting/screen.py --self-check --python-packages target/ibl-comparison/python
python scripts/mip-weighting/screen.py --python-packages target/ibl-comparison/python
python scripts/mip-weighting/analyze.py --self-check --python-packages target/ibl-comparison/python
python scripts/mip-weighting/analyze.py --python-packages target/ibl-comparison/python
python scripts/mip-weighting/analytic_lamp.py --python-packages target/ibl-comparison/python
```

Omit `--python-packages` when those packages are installed in the active Python.
Compatibility compares production and box CLI bytes, warning reports and output
summaries, then parses both experimental policies with the actual TypeScript
loaders. It checks output dimensions, mip levels, ordered faces, chunks, output
pixel counts and unchanged LUT bytes. EXR writer inputs are contiguous RGB arrays.

The pilot uses source size 256, constant and directional fields, a 37-degree
directional rotation, separate 1.2-degree Gaussian lights centered on a face,
edge and corner, Pisa and Qwantani. Queries use 64 uniform directions, 26
axis/edge/corner directions and 27 lamp-neighborhood directions; groups are
reported separately. Every GGX query uses exactly 256 or 1024 proposals at actual
roughness 0.05, 0.2, 0.5, 0.7 and 1; Lambert queries use the same two budgets.
Accepted GGX light counts are recorded. These fixed proposal counts are not a
claim about the CLI's adaptive per-output-mip sample counts.

Both policies must have identical mip0, actual f32 query directions and kernel
identities. The immutable shared mip0 is the primary integration target. The
continuous affine direction-field diagnostic separately includes projection
error; the two targets are never conflated.

`analytic_lamp.py` reads the saved face-center lamp case and adds a continuous
single-normal control. Its independent segmented one-dimensional angular
integral splits around known lamp/kernel scales and checks 32/64/128 orders and
a closed-form normalizer. It includes common projection/reconstruction and
finite proposal-budget error, does not replace the shared-mip0 reference or
change the expansion gate, and never launches a bake. Its complete twelve-row
comparison is saved in `target/mip-weighting/analytic-lamp/report.json`.

The independent f64 reference integrates normalized N=V GGX and normalized
Lambert kernels without source mips, FIS or production Hammersley samples. For
GGX, product Gauss-Legendre/periodic azimuth rules integrate half-vector CDF
`u` over `[0, 1/(1+alpha^2)]`, with `alpha=r^2`, weighting both numerator and
denominator by `NoL`. At r=1 the directional closed form is `0.5+normal/3`.
This validates the target prefilter, **not a complete physical BRDF renderer**.

The reference ladder is 32x64, 64x128, 128x256 and 256x512, with two azimuth phases.
Two successive changes and phase agreement must meet a relative 1e-4 diagnostic
tolerance. These changes are not rigorous error bounds. For at most eight
sensitive directions per HDR, an independent source cube-UV integral checks the
recorded bright/high-gradient support union plus interpolation halo. Local
agreement does not certify other HDR structures or the full convolution.

Reference computation has a 30-minute pilot budget. Each reference item,
including its local check, has a 60-second limit; local integration has at most
six subdivision levels and 100,000 nodes. Limits, unresolved peaks or disagreement
produce `uncertain`, never a positive adoption signal. Tool or producer drift
invalidates a run. Raw little-endian f32 results, generation inventories,
reference traces and full linear metrics remain under `target/mip-weighting/`.

## Conservative expansion gate

`analyze.py` verifies provenance before calculating the gate. At least two
nonconstant cases, including one HDR, must show a relative RMSE reduction of 5%
or more at two GGX roughnesses in the same case/group/region under both budgets.
Improvement must exceed five times the empirical RMSE-difference envelope, which
is twice the RMS of the per-probe reference spreads. This is a diagnostic, not
a strict error bound. Every required HDR local check must also agree.
Any qualified nonconstant regression exceeding five empirical difference
envelopes in a full, bright, or targeted group blocks expansion, even if it
appears at only one proposal budget. Both-budget repetition is reported separately;
all observed diagnostic regressions remain in the report. Missing cases or an
incomplete reference cannot pass. The numerical thresholds control experiment
scope; they are not universal perceptual thresholds.

If the gate fails, stop and retain box. Improving discrete `sum(L*solid_angle)`
alone is not a picture-quality benefit. Do not tune LOD, sampling budgets or
output tails to rescue this candidate.

Only a passing pilot proceeds to size-512 confirmation and the existing full
cmgen/material matrix, then production-process performance using the
[phase-two benchmark](../source-sampling/README.md#production-process-performance).
Use the prepared uninstrumented CLI binaries and snapshot paths. Every original
gated scene must meet 1.05x median time and 1.10x OS peak committed memory, with
two warmups and seven alternating paired rounds, or fifteen when uncertain.
Skipped stages are reported as not evaluated; a successful study still requires
a separate production-policy decision.

The English findings are recorded in
[the feasibility report](../../docs/mip-weighting-feasibility.md).
