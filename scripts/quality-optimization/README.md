# Quality optimization study

These private tools keep candidate source-LOD offsets and sample-budget curves
out of the production API. Outputs are confined to `target/quality-optimization`.
The frozen optimization baseline is `8330953082f11ce9b0a7a0908b8ddfb3675deb4e`.
Historical release comparisons must be recorded separately.

## Reproduction on Windows

Use Python 3.12 with `requirements.txt`, the repository's pinned Rust toolchain,
Node, and the Cargo sources installed by `pnpm install --frozen-lockfile`. A
separate package directory can be passed with `--python-packages PATH`.

Before editing the baseline, build its release CLI and
`source_sampling_export` example and retain them under
`target/quality-optimization/baseline`. Preserve `git archive` and binary SHA-256
digests. Do not use a subsequently rebuilt executable as the frozen baseline.

```powershell
python scripts/quality-optimization/study.py prepare
python scripts/quality-optimization/study.py screen --sizes 128,256,512 --cases hemisphere-0,hemisphere-1,hemisphere-2
python scripts/quality-optimization/analyze.py --size 128
python scripts/quality-optimization/analyze.py --size 256
python scripts/quality-optimization/analyze.py --size 512
python scripts/quality-optimization/decision.py
python scripts/quality-optimization/acceptance.py parity
python scripts/quality-optimization/acceptance.py benchmark
python scripts/quality-optimization/views.py
python scripts/quality-optimization/encoding.py
python scripts/quality-optimization/history.py
```

`prepare` copies the current tracked Rust files into an isolated source snapshot,
then changes exactly three checked injection points there. It records source,
helper and executable hashes. Production files are not patched. Re-run it after
changing production code or `export.rs`; cached bakes invalidate on binary, input
or parameter changes, and verify every retained output's digest.

`screen` defaults to all cases. It generates 512-square EXR six-face constant,
directional, three rotated unit red/blue hemispheres, and wide/narrow Gaussian
lamps at a face center, edge and corner. Real cases use `fixtures/inputs/pisa.hdr`,
`fixtures/inputs/footprint_court.hdr`, and
`target/ibl-comparison/inputs/qwantani_noon_puresky_1k.hdr`. The last file is an
optional separately acquired Poly Haven asset; synthetic-only runs do not need
it. Inputs are hashed and their existing files are not overwritten. Delete only
the task-owned generated input directory if intentionally changing its definition.

The 18 medium-quality candidates isolate source LOD, r-squared/linear/maximum
sample budgets, 1024/2048/4096 requests and 1/4/8/16 tail widths, then combine the
smaller-footprint, linear-budget, 8/16-tail candidates. The mean-texel-solid-angle
LOD offset is `-0.5*log2(4*pi)`; the compromise adds one to that offset. Both are
applied before final clamping. Metadata lists each level's actual dimensions,
roughness and effective sample count; mip zero records zero convolution samples.
The source mip chain and UV box reduction are unchanged.

`analyze` uses 76 fixed directions (32 uniform; six axes, twelve edge midpoints
and eight corners; eighteen lamp-local probes). It evaluates 0.05 roughness steps
plus every candidate's adjacent-level midpoints. It records unencoded, decoded
RGBD, and decoded BC6H errors separately, including encoding-only error and
out-of-range pixel counts. Raw prefilter fields are reconstructed with the same
seamless bilinear/trilinear sampler. Clipping counts do not include BC6H padding.
This models decoding texels before filtering; filtering encoded RGBD first can
have additional runtime error and is not claimed to be equivalent.

Half-sphere reference integration uses exact azimuthal coverage and three f64
Gauss orders; r=1 has a closed form. Other cases reuse the bounded independent
CDF quadrature and local HDR source-UV checks in `scripts/mip-weighting/reference.py`.
Their reference target is explicitly continuous analytic or shared projected
mip zero, never the production prefiltered output. Failed convergence stays in
the metrics as unqualified, including any missing result. Each HDR probe has a
ten-second total reference/local-check budget. An unresolved item cannot pass a
gate. Run additional cases with `--cases constant,directional,pisa,...`; these
can be expensive. Analysis files replace the previous selection at that size,
so pass the complete desired case list when collecting a final report.

`decision` reports confirmed endpoint or subgroup failures and preserves
unqualified counts. It deliberately cannot approve a default: all adoption
criteria, including the full HDR and material review, must be verified before
changing production. A necessary failure suffices to reject early; it does not
make the omitted later gates pass. No aggregate improvement claim is inferred
from a surviving subset.

`parity` checks all three production output modes against the frozen CLI and
feeds NPOT/truncated assets to both real TypeScript parsers. `benchmark` uses
two warmups and seven alternating pairs per HDR, size and format with four Rayon
threads and all default output targets (including irradiance and LUT). Windows Job Objects measure elapsed process time and peak committed
memory. It records file sizes, binary/input hashes and machine metadata. Run it
without competing bake/build/reference jobs. A bootstrap interval crossing 2x
requires `--rounds 15`; a still-ambiguous result remains uncertain. Memory is
reported, not assigned an invented acceptance threshold. These process timings
must not be replaced by the exporter's filter-only timer.

`views` stores fixed-exposure reflection, metal and dielectric sheets plus linear
RGB arrays. Both candidates share the baseline LUT and diffuse bake; this is a
material comparison, not a physical-reference renderer. It also separates
direct rough-tail texel error from the reconstruction of an ideal analytic tail
grid and final sampled error. Those RMSE values are not additive. `encoding`
separately measures clipping loss and decoded compression/quantization loss for
the constant environment and all three HDRs. `history` verifies the local 0.2.3
release archive against `target/binaries/windows-x64.json` and compares decoded
mip-zero resampling against the optimization baseline; historical gains do not
count as improvements made by this work.
