# Release History

This archive preserves dated rollout, bootstrap, rehearsal and production evidence.
Each section records the state at that time; later verification does not change earlier results.
See [Release Process](release.md) for current operations and recovery rules.

## Infrastructure rollout and rehearsals (2026-09-17)

- [Implementation PR #1](https://github.com/shawn0326/ibl-baker/pull/1) merged as e2bc2848e2ac9b1779947e37dcb7791812d8024e.
- [Implementation PR CI](https://github.com/shawn0326/ibl-baker/actions/runs/35194599409): passed.
- [Master CI and Pages deployment](https://github.com/shawn0326/ibl-baker/actions/runs/35195117843): passed.
- Master protection was read back after configuration: required PR, checks / Quality from GitHub Actions, strict status checks, administrator enforcement, no force pushes/deletion, zero required approving reviews.
- Local validation passed: 61 Rust tests, 22 loader tests, both viewer builds, TypeScript, 17 release/recovery tests, actionlint, Cargo dry-runs and archive consumers. Existing registry versions also passed exact-version consumer checks; no registry uploads were performed.

The [first all-group rehearsal](https://github.com/shawn0326/ibl-baker/actions/runs/35195133128)
passed all three platform builds and quality checks, then exposed npm 11.11 rejecting
occupied versions during native publish dry-run. The
[occupied-version rehearsal rule](release.md#rehearse) addresses that behavior;
production availability checks remain unchanged.

- [Rehearsal compatibility fix PR #2](https://github.com/shawn0326/ibl-baker/pull/2) merged as 559ed79d5a4e026e002ce4ed6a4c0abcab2b33d4.
- [Fix PR CI](https://github.com/shawn0326/ibl-baker/actions/runs/35195891602): passed, including 18 release/recovery tests.
- [Updated master CI and Pages](https://github.com/shawn0326/ibl-baker/actions/runs/35196398791): passed.
- Each loader also passed an independent archive-consumer check against temporary fixtures without selecting Rust.
- [Successful all-group rehearsal](https://github.com/shawn0326/ibl-baker/actions/runs/35196405209): passed on 559ed79d5a4e026e002ce4ed6a4c0abcab2b33d4. All five package archives, Windows x64/macOS arm64/Linux x64 binaries and external candidate consumers passed.
- Downloaded release-candidate artifact 10486711223 and independently verified every package/binary SHA-256 and release-note checksum. Toolchain evidence matches Node 24.19.0, npm 11.11.0 and Cargo 1.98.0.
- The three crates remain 0.2.1 and both loaders remain 0.2.0. All five occupied versions and missing new release notes are explicitly marked NOT publishable. The publish, verify and finalize jobs were skipped; no registry upload, tag or Release was created.
- Infrastructure acceptance was complete after this rehearsal. Actual OIDC publication, npm provenance after upload, registry consumers and Release finalization remained for the next production release. Real partial-failure recovery had simulated coverage only. See the [2026-09-29 production evidence](#production-release-2026-09-29) for subsequent verification.

## npm CLI bootstrap and rollout (2026-09-18)

The pending registry index visibility recorded during bootstrap was resolved by the
three-platform registry consumers in the [2026-09-29 production release](#production-release-2026-09-29).

### Bootstrap

Published the four public npm CLI packages at 0.1.0 using interactive npm
authentication as shawn0326. The three platform packages were published before
the entry package. Used the original CLI-only candidate from run 35302832171
(artifact 10530404545, source afeec88476693e61bb931681179e70f35ef15939).
Downloaded each registry tarball and verified its SHA-256 and SHA-512 integrity
against that candidate. All four latest tags resolve to 0.1.0.

Created GitHub Trusted Publishers for all four packages:

| Package | Configuration ID |
| --- | --- |
| @ibltools/cli-win32-x64 | dec7ffac-f993-4892-b9d5-cee85c8f5168 |
| @ibltools/cli-darwin-arm64 | 2803b85b-9cba-4e19-89a3-956ffbbdb966 |
| @ibltools/cli-linux-x64-gnu | 01b29980-cc49-41b1-95ee-33afa5c912fb |
| @ibltools/cli | 6152b015-dc86-4812-87e6-339fa5e57428 |

All configurations target shawn0326/ibl-baker, workflow publish.yml,
Environment release, with direct npm publish enabled. npm confirmed successful
creation and reported permissions for publish and stage publish. This records
configuration, not a successful OIDC publication.

The public package-index endpoints initially returned 404 even after the exact
version endpoints and tarballs became available. Normal registry installation
acceptance is pending; do not retry publication of these occupied versions.
A clean external Windows project installed the registry entry and Windows tarball
URLs with scripts disabled; --version returned ibl-baker 0.2.2 and --help passed.
A separate empty-directory npm exec by package name still returned index HTTP 404.
Local checksum receipts are in
target/npm-cli-rehearsal-35302832171/bootstrap-receipts.json.

No Git tag or GitHub Release was created for this interactive bootstrap.
The next new version must use the normal OIDC workflow, including provenance
and all three registry consumers; bootstrap does not waive those checks.

### Rehearsal validation

Local validation passed: 62 Rust tests, 23 release/recovery tests, 22 loader tests,
TypeScript, both viewer builds, Cargo/npm archive consumers, Windows CLI tarball
installation and real console Ctrl+C cancellation. Actionlint passed.

- [Implementation PR #4](https://github.com/shawn0326/ibl-baker/pull/4) merged as 20df67d83c5bd095dd070d1224fd4cb119d86efc.
- [Implementation CI](https://github.com/shawn0326/ibl-baker/actions/runs/35302032490) passed, including Linux CLI tarball consumers and Unix signals.
- [Initial npm CLI rehearsal](https://github.com/shawn0326/ibl-baker/actions/runs/35302372934) exposed a macOS test expectation using /var instead of its canonical /private/var path. The test now compares canonical paths; argument and cwd forwarding are unchanged.
- [macOS test correction PR #5](https://github.com/shawn0326/ibl-baker/pull/5) merged as afeec88476693e61bb931681179e70f35ef15939; [its CI](https://github.com/shawn0326/ibl-baker/actions/runs/35302573895) passed.
- [Master CI and Pages](https://github.com/shawn0326/ibl-baker/actions/runs/35302828106) passed.
- [npm CLI-only rehearsal](https://github.com/shawn0326/ibl-baker/actions/runs/35302832171) passed: four npm packages, three native builds and three independent archive consumers. Candidate artifact: 10530404545.
- [All-four-group rehearsal](https://github.com/shawn0326/ibl-baker/actions/runs/35302835316) passed: nine packages, three native builds, Cargo dry-runs, original loader/Cargo consumers and three CLI consumers. Candidate artifact: 10531081507.
- Both rehearsals used afeec88476693e61bb931681179e70f35ef15939. Downloaded both candidates and all six CLI reports; independently verified every package/native archive SHA-256, release-note hashes, CLI manifests, exact platform dependency versions and report identity. Each platform's npm executable was byte-identical to its corresponding native archive in that same run.
- The npm distribution is 0.1.0 and its embedded Rust CLI is 0.2.2. Linux symbol inspection found GLIBC_2.34 references and dynamic libstdc++; the supported and tested baseline remains Ubuntu 24.04.
- The CLI-only candidate had no occupied versions or missing notes. The combined rehearsal correctly marked both existing loader 0.2.0 versions and their missing release notes as NOT publishable; it did not bypass production availability checks.
- In both runs, publish, verify, cli-registry and finalize were skipped. No registry package, Git tag or GitHub Release was published.
- At rehearsal completion, initial ownership/publication of the four npm packages, Trusted Publishers, actual OIDC/provenance and registry consumers remained separate release work. See the bootstrap record above for subsequent progress. Real partial-publication recovery remains unverified; its ordering and checksum safeguards have simulated coverage.
No npm CLI package upload, tag or Release is part of this implementation rehearsal.

## Production release (2026-09-29)

- [Production Publish run 36571226684](https://github.com/shawn0326/ibl-baker/actions/runs/36571226684) completed successfully for source commit `e20bbace74117a34fd604b1f0537c476e7f05366`.
- Released three independent units: Rust/CLI `0.2.3`, `@ibltools/ktx2-loader` `0.3.0`, and the four-package npm CLI group `0.1.1`. The `.ibla` loader was not selected.
- Published crates.io packages: `ktx2_writer@0.2.3`, `ibl_core@0.2.3`, and `ibl_cli@0.2.3`. Published npm packages: `@ibltools/ktx2-loader@0.3.0`, `@ibltools/cli@0.1.1`, `@ibltools/cli-win32-x64@0.1.1`, `@ibltools/cli-darwin-arm64@0.1.1`, and `@ibltools/cli-linux-x64-gnu@0.1.1`.
- All eight registry receipts passed verification against the candidate SHA-256 values in `verified.json`. crates.io metadata records GitHub Trusted Publishing run `36571226684` and source SHA `e20bbace74117a34fd604b1f0537c476e7f05366` for each new crate version. npm registry metadata exposes SLSA provenance attestations for all five new npm versions; package integrity values match the candidate.
- Cargo and KTX2 loader registry consumers passed in the production verification job. npm CLI registry consumers passed on Linux x64, macOS arm64, and Windows x64. The production `verify`, `cli-registry`, and `finalize` jobs passed.
- Finalization created separate tags and GitHub Releases at the original source commit: [Rust/CLI `v0.2.3`](https://github.com/shawn0326/ibl-baker/releases/tag/v0.2.3), [KTX2 loader `npm/ktx2-loader/v0.3.0`](https://github.com/shawn0326/ibl-baker/releases/tag/npm/ktx2-loader/v0.3.0), and [npm CLI `npm/cli/v0.1.1`](https://github.com/shawn0326/ibl-baker/releases/tag/npm/cli/v0.1.1). Each Release contains its package archives and candidate/verification evidence; the Rust/CLI Release also contains all three platform binaries. The committed note headings are omitted from Release bodies to avoid duplicating Release titles.
- Successful OIDC publishing, post-upload registry integrity/provenance checks, all three platform registry consumers, and Release finalization are now verified. Real recovery after a partial production publication remains untested; recovery ordering and checksum safeguards still have simulated test coverage only.

## CI merge gate acceptance (2026-09-30)

- [Implementation PR #21](https://github.com/shawn0326/ibl-baker/pull/21) adds the fixed `CI Gate` check for the complete ordinary CI checks workflow. Pages remains separate.
- [Platform failure verification](https://github.com/shawn0326/ibl-baker/actions/runs/36726386330): Linux Quality and macOS Cargo succeeded, Windows Cargo failed, and `CI Gate` failed with `CHECKS_RESULT=failure`.
- [Skipped-upstream verification](https://github.com/shawn0326/ibl-baker/actions/runs/36727519598): the reusable checks workflow was deliberately skipped and `CI Gate` failed with `CHECKS_RESULT=skipped`.
- [Cancellation verification](https://github.com/shawn0326/ibl-baker/actions/runs/36727649197): cancellation stopped Linux Quality and Windows Cargo; `CI Gate` still ran and failed with `CHECKS_RESULT=cancelled`.
- Temporary failure and skip conditions were removed before the final PR content. These checks did not dispatch Publish or upload registry packages.
