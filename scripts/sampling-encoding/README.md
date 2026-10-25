# Full-chain sampling and encoding experiments

The production baseline is `4398483`, after shared baking. These private tools
write only under `target/sampling-encoding`, reuse the earlier generated inputs
under `target/quality-optimization`, and introduce no production tuning interface.
Use Python 3.12 and the [previous requirements](../quality-optimization/requirements.txt),
the pinned Rust toolchain and pnpm-materialized Cargo sources. A separate Python
package directory is accepted with `--python-packages PATH`.
This local harness records Windows executables and Windows Job Object memory
accounting. It does not replace the project's Linux/macOS build and quality CI.

## Freeze and prepare

Build the baseline CLI from a clean archive of `4398483` with the same release
toolchain as the candidate. Retain its source archive and executable at
`target/sampling-encoding/baseline/source.tar` and `baseline/ibl-baker.exe`.
Do not copy a newly changed production binary into that directory. The measured
baseline hash and source commit are recorded in the acceptance report.

```powershell
python scripts/sampling-encoding/experiment.py prepare
python scripts/sampling-encoding/experiment.py generate --sizes 128,256,512 --policies quadratic,linear,sample-only,footprint-only --codecs basic-black,basic-edge,slow-edge
python scripts/sampling-encoding/analyze.py --size 128 --policies quadratic,linear,sample-only,footprint-only --codecs basic-black,basic-edge,slow-edge
python scripts/sampling-encoding/analyze.py --size 256 --cases hemisphere-0,hemisphere-1,hemisphere-2 --policies quadratic,linear,sample-only,footprint-only --codecs basic-black,basic-edge,slow-edge
python scripts/sampling-encoding/analyze.py --size 512 --cases hemisphere-0,hemisphere-1,hemisphere-2 --policies quadratic,linear,sample-only,footprint-only --codecs basic-black,basic-edge,slow-edge
```

`prepare` reads frozen files directly from Git, copies the private helper examples
and patches only its own snapshot. It records source/helper/executable hashes.
The four policies form a 2x2 experiment: quadratic or linear actual counts crossed
with quadratic or linear source-footprint counts. Both count paths use the same
quality caps, size boosts and request ceiling. The private footprint helper assumes
a complete natural chain, medium quality and 1024 samples; the isolated binaries
are not general-purpose replacement CLIs.

Actual and footprint counts are recorded per level. The old source LOD expression
is retained; the GGX call receives the independently selected footprint count.
Lambert filtering is not patched. Generation hashes identify input files, binary
and policy. Re-encoding hashes identify the saved floating generation and encoder.
Cache reuse verifies the recorded output hashes as well as the input identity.
Research runs are not production process benchmarks.

## Codec controls and decoded-RGB refinement

`CODECS` additionally includes very-slow search, a small-level-only policy,
8/32 endpoint-refinement iterations and fast-mode controls. These compare search
and padding independently. A codec experiment always starts with identical saved
floating levels and writes the same BC6H UFLOAT/zstd KTX2 profile.

```powershell
python scripts/sampling-encoding/refine.py --policies quadratic,linear
python scripts/sampling-encoding/analyze.py --policies quadratic,linear --codecs basic-black,basic-edge,linear-rgb-edge,portfolio-edge --tag portfolio
```

`refine` changes only BC6H indices, preserving modes, endpoints and the standard
one-/two-subset anchor constraints. Imagecodecs' explicit BC6HU decoder supplies
the candidate palettes. It verifies non-increasing valid-texel linear-RGB SSE for
each refined block. The portfolio also retains the original basic block as a
fallback. Only levels <=64 are refined; larger levels preserve the original basic
payload. Reconstructed cubemap/convolution errors are still evaluated independently:
a lower stored-texel SSE does not imply a better value at every runtime query.
The final KTX2 is checked with the existing decoder/parser profile. No decoder is
added to a public package.

The extra `linear-footprint-25/50/75` policies keep actual sampling linear and
interpolate the footprint count between the quadratic and linear controls. These
are fixed research candidates, not scene-dependent tuning or public parameters.

## Full-source HDR reference

Generate all four controls for `pisa,footprint,qwantani` at 128, then run:

```powershell
python scripts/sampling-encoding/experiment.py generate --cases pisa,footprint,qwantani --policies quadratic,linear,sample-only,footprint-only --codecs basic-black,basic-edge,slow-edge
python scripts/sampling-encoding/reference.py --self-check
python scripts/sampling-encoding/reference.py
python scripts/sampling-encoding/reference.py --repair
python scripts/sampling-encoding/reference.py --extend-tail
python scripts/sampling-encoding/reference.py --repair
python scripts/sampling-encoding/analyze.py --cases pisa,footprint,qwantani --policies quadratic,linear,sample-only,footprint-only --codecs basic-black,basic-edge,slow-edge
```

The f64 reference integrates every source-UV cell, including bright pixels, with
the exact cube Jacobian and an independent normalized convolution kernel. Cells
split at the shared mip-zero source's bilinear knots. Three distinct bright
regions add 27 local probes to the existing 76 directions. The reference target
is the shared projected mip-zero cubemap, not the original continuous HDR or a
full material renderer.

Orders 2/4/6, with higher local order near low-roughness kernel peaks, require two
successive RGB changes and the analytic unit-normalizer error to meet 1e-4. Repair
uses orders 4/6/8 on unresolved directions and stores the original diagnostics and
all replacement levels. Uncertain rows stay in the output. Scene means are
descriptive and include uncertain rows; only qualified rows can certify subgroup
regressions. The initial seven HDR roughnesses are extended with all 0.05-spaced
queries, midpoints and stored knots affected by partial-tail interpolation.
Every direction on all fifteen queried roughnesses converged after repair.
Scene means on this nonuniform query set do not measure a global-average gain.

`--tag NAME` preserves an additional analysis selection without overwriting the
main matrix. It is useful for codec portfolios or intermediate-footprint subsets.
Each analysis file describes its actual cases, policies and codecs. Do not infer
that an ungenerated size or untested roughness has passed.

## Production checks and timing

```powershell
python scripts/sampling-encoding/experiment.py generate --sizes 1,3,31,255 --cases constant,directional,pisa --policies quadratic --codecs basic-black,basic-edge
python scripts/sampling-encoding/tail.py
python scripts/sampling-encoding/analyze.py --cases constant,hemisphere-0,hemisphere-1,hemisphere-2,pisa,footprint,qwantani --policies quadratic --codecs basic-black,basic-edge,single-texel-edge --tag single-texel
python scripts/sampling-encoding/analyze.py --size 256 --cases hemisphere-0,hemisphere-1,hemisphere-2 --policies quadratic --codecs basic-black,single-texel-edge --tag single-texel
python scripts/sampling-encoding/analyze.py --size 512 --cases hemisphere-0,hemisphere-1,hemisphere-2 --policies quadratic --codecs basic-black,single-texel-edge --tag single-texel
python scripts/sampling-encoding/checks.py
python scripts/sampling-encoding/acceptance.py compatibility
python scripts/sampling-encoding/acceptance.py benchmark
python scripts/sampling-encoding/experiment.py prepare-timing
python scripts/sampling-encoding/acceptance.py linear-benchmark
python scripts/sampling-encoding/evidence.py --plot
```

`checks` verifies factorial count invariants, complete chains, budget bounds,
unchanged mip zero, frozen floating controls and unchanged aligned BC6H levels.
It records valid-texel encoding SSE and clipping separately, including tiny/NPOT
images. `tail` copies edge-padded blocks only at width 1 and baseline blocks at
every other width, without changing source floats. This isolates a uniform 1x1
repair after general edge padding fails the denser HDR reference. `compatibility`
invokes both actual TypeScript parsers and checks unchanged IBLA/LUT bytes,
non-1x1 level payloads and aligned truncated KTX2 output. The evidence collector
also checks the production blocks against this private quality-tested control.

Before `benchmark`, build the production CLI normally. The measurement uses
medium/1024, complete chains and all default targets. The uniform-1x1
repair gets all 27 scene/size/format cells; the rejected linear candidate gets
nine Qwantani cells for diagnostic timing. There are two warmups and seven
alternating rounds, four Rayon threads, and Windows Job Object memory accounting.
Do not run competing bakes, builds or reference jobs during timing. A 2x bootstrap
interval crossing requires fifteen rounds and remains uncertain if unresolved.

The rejected full-edge candidate's original timing file is retained as
`all-edge-benchmark.json`; its diagnostic CLI contains source-footprint hooks.
Those linear timings are instrumented diagnostics. `prepare-timing` creates a separate
static snapshot with just the linear curve and production edge repair, without
those hooks. `linear-benchmark` repeats the nine strong-sun cells for that static
binary. Never rebuild a timed executable while a benchmark is running. Optional
chart generation uses matplotlib; numerical checks do not require it. If matplotlib
is in a different Python environment, run `evidence.py --plot-only` there before
collecting numeric evidence in the data-analysis environment. Plot-only mode reads
completed JSON without importing OpenEXR or a BC6H decoder.

Artifact hashes, commands, elapsed times, peak process commit and file sizes stay
in the task output directory. The compact evidence report preserves verified
conclusions; large raw float/encoded assets and full reference traces remain local.
