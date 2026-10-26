# Pipeline performance study

The frozen baseline is `125ea90`. This Windows-only harness keeps production
profiling hooks and allocator changes out of the public crates. It writes under
`target/pipeline-performance`; use the pinned toolchain and pnpm-materialized
Cargo sources. No public CLI switch, quality setting or dependency is added.

```powershell
python scripts/pipeline-performance/study.py prepare-baseline
python scripts/pipeline-performance/study.py prepare-profile
python scripts/pipeline-performance/study.py profile
# After implementing the production candidate:
python scripts/pipeline-performance/study.py prepare-profile-candidate
python scripts/pipeline-performance/study.py profile-candidate
cargo build --locked --offline --release -p ibl_cli
python scripts/pipeline-performance/study.py compatibility
python scripts/pipeline-performance/study.py benchmark
python scripts/pipeline-performance/study.py benchmark-confirm
python scripts/pipeline-performance/collect.py --plot
```

`prepare-baseline` reads the frozen commit directly from Git. The candidate
snapshot reads the current tracked production sources. Private profile snapshots
add a std-only instrumentation crate, a tracking Rust global allocator and Windows
process-memory queries. Their modified lockfiles stay in the isolated snapshots.
The public workspace lockfile and dependencies are unchanged. Native builds and
profile snapshots retain source and executable hashes.

Phase runs use Pisa HDR, a 2K JPEG and a six-face JPEG environment, medium/default
1024 samples, a complete chain, all targets, `both`, and four Rayon threads. One
warmup precedes three measured trials. Every instrumented result must match all
five frozen production outputs byte for byte. Stages include loading, projection,
source mip/border preparation, each filter, PNG/IBLA assembly, KTX2 RGB packing,
BC6H/zstd and output serialization/writes. Parent times include their children;
do not add nested times twice.

`heap_peak` is an absolute high-water mark of requested-live Rust allocations,
including retained inputs and other live data. It is not incremental allocation
attributed exclusively to that phase, nor resident physical RAM. C allocations,
allocator arena overhead and transient old/new buffers inside realloc are not
covered. `commit_peak` samples native process private commit at scope boundaries
and from a background thread requesting a 1 ms sleep; OS scheduling can miss
short peaks. Samples include boundary probes. Neither phase memory value is
additive across stages.

Allocator tracking, native sampling, logging and changed cleanup lifetimes can
perturb phase times. Use them to locate work and lifetime costs, not to certify
production speed. `benchmark` uses separate uninstrumented executables and the
existing Windows Job Object harness, which retains actual peak process commit
after exit. It measures IBLA/KTX2/both independently with two warmups and seven
alternating paired rounds. Do not build, bake or run profile jobs concurrently
with these timing runs, and never replace an executable during measurement.
Time/memory bootstrap intervals and the reused 5%/10% noise diagnostics are
reported; useful improvement and output parity remain the decision criteria.
`benchmark-confirm` repeats only initially uncertain cells with fifteen rounds,
retaining the original seven-round data. It does not rebuild the executables.
The optional chart uses matplotlib; profiling and numeric collection use only
the Python standard library.

`compatibility` checks tiny/NPOT/truncated/rotated outputs, irradiance larger than
the specular source, low sample budgets and single-target selections. Real loader
implementations parse the complete cubemap output pairs. The normal Rust suite
also checks clipping reports and partial write failures.

Raw logs, per-run phases and artifacts stay local. The acceptance report records
compact evidence and limitations. Linux/macOS builds still need their own CI;
local Windows instrumentation is not a portability certificate.
