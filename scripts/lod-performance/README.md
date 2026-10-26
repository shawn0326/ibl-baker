# Source-LOD precomputation acceptance

This study starts at `a306d63`, after decoded-input reuse and base-buffer ownership
transfers. It does not reuse the earlier baseline's performance allowance.
The harness writes only under `target/lod-performance` and reuses the
[pipeline performance tooling](../pipeline-performance/README.md).

```powershell
# Before changing production sources, retain the previously accepted binary:
python scripts/lod-performance/study.py freeze
cargo build --locked --offline --release -p ibl_cli
python scripts/lod-performance/study.py pilot
# Continue only if the byte-identical pilot has a useful measured gain:
python scripts/lod-performance/study.py compatibility
python scripts/lod-performance/study.py benchmark
python scripts/lod-performance/study.py benchmark-confirm
python scripts/lod-performance/study.py prepare-profile
python scripts/lod-performance/study.py profile
python scripts/lod-performance/study.py prepare-profile-candidate
python scripts/lod-performance/study.py profile-candidate
python scripts/lod-performance/collect.py --plot
```

`freeze` checks the prior accepted binary/source fingerprints before copying the
executable. Production tests also compare raw float results with a frozen scalar
path for GGX/Lambert, low/empty kernels, singleton/NPOT sources, edges and corners.
The pilot measures specular-only and irradiance-only KTX2 on Pisa at 512, with
two warmups and seven alternating rounds. The production matrix then covers
HDR, 2K JPEG and six-face JPEG inputs, all targets, and IBLA/KTX2/both separately.
Every paired run must preserve file hashes and lengths.

Phase diagnostics use one representative Pisa environment to measure filtering
and unchanged pipeline stages. They use the same isolated allocator/native-memory
sampling as the earlier study and are not used to certify production speed.
Source loading is already shared in both baseline and candidate. The only new
working storage is an O(sample-count), per-pass prepared kernel; no per-pixel
allocation, persistent cache, quality setting or public parameter is added.

Run builds and profiles separately from uninstrumented timing. Two warmups and
seven paired rounds are used for acceptance; only uncertain cells receive one
fifteen-round confirmation. Retain the original measurements. Never rebuild a
measured executable during the matrix. Windows Job Object peaks are private
process commit, not resident physical RAM. Phase heap counters exclude native
allocations and allocator overhead; sampled phase process memory can miss short
peaks. Other platforms still require fresh build/test CI.
