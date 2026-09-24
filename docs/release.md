# Release Process

This is the operational guide for CI, release preparation, publishing and recovery.
Ordinary commits and pull requests never publish packages. The workflow does not
change versions or refresh local fixtures.

## Release units and versions

| Input | Contents | Version source | GitHub tag |
| --- | --- | --- | --- |
| rust_cli | ktx2_writer, ibl_core, ibl_cli and three CLI binaries | Cargo workspace version | vVERSION |
| npm_ibla_loader | @ibltools/ibla-loader | Its package.json | npm/ibla-loader/vVERSION |
| npm_ktx2_loader | @ibltools/ktx2-loader | Its package.json | npm/ktx2-loader/vVERSION |
| npm_cli | @ibltools/cli and three platform packages | CLI workspace package.json | npm/cli/vVERSION |

Rust crates remain one coordinated group, ordered as ktx2_writer, ibl_core,
ibl_cli. Their internal dependency versions must match the workspace version.
The npm loaders have independent versions. Viewer packages are private and are
never published; update their loader dependency references when bumping loaders
so development continues to use the workspace packages.

Only change versions for consumer-facing changes. CI, website and release
infrastructure changes do not require a package release. Update the relevant
manifests, Cargo.lock and the JavaScript lockfile in a release PR. The workflow never
chooses a version or bumps it for you.

## One-time configuration

Configure a GitHub Trusted Publisher separately on each published package:

| Field | Value |
| --- | --- |
| Owner | shawn0326 |
| Repository | ibl-baker |
| Workflow filename | publish.yml |
| Environment | release |

On npm, enable **Allow npm publish**. This workflow uses direct publishing after
GitHub approval, not npm staged publishing. Stable versions immediately enter
latest; prerelease versions enter next. There is no automatic later promotion.

The GitHub release Environment requires review by shawn0326, allows self-review,
disallows administrator bypass, and only accepts the master branch. Keep it
separate from github-pages. No long-lived npm/Cargo token or PAT is needed in
repository secrets. Cargo obtains a temporary token immediately before upload.

Trusted Publisher configurations for the original three crates and two loaders
have been reported complete by the maintainer. The four new CLI packages still
require the bootstrap steps below.
The release Environment has been checked through the API. A dry-run cannot prove
registry authorization or provenance: mark those verified only after a real release.
For a new package, establish its ownership/initial publication before depending
on package-specific trusted publishing. After successful OIDC publishing, revoke
obsolete publish tokens and restrict traditional npm token publishing.

## Daily CI and local checks

Pushes to master, pull requests, and manually dispatched CI run the same quality
checks used by Publish. Only successful master CI deploys the two viewers to Pages.
master requires a PR and the checks / Quality status check, including for
administrators. Another person's PR approval is not required. Force pushes and
branch deletion are forbidden.

Toolchains are Node 24.19.0, pnpm 12.5.1, npm 11.11.0 and Rust/Cargo 1.98.0.
The repository pins Rust/Cargo through `rust-toolchain.toml`; commands run from
the checkout therefore use the release toolchain automatically. Commands run
outside the checkout, such as registry consumers, should set `RUSTUP_TOOLCHAIN`
explicitly when they must use the same toolchain.
pnpm manages the JavaScript workspace and npm 11.11.0 is resolved directly by the
release scripts for npm packing, publishing and consumer checks. Actions are pinned
to reviewed commit SHAs. Release builds do not restore PR caches.

pnpm 12.5.1 also installs the Cargo workspace dependencies through its experimental
Cargo integration. `pnpm install` materializes `.pnpm/crates/crates-io` and a generated
`.cargo/config.toml`; both paths are ignored and must not be committed. `Cargo.lock`
and `pnpm-lock.yaml` remain independent. Cargo still owns metadata, compilation,
tests and crates.io publishing, and a fresh checkout must run pnpm install before
running Cargo commands.
Cargo publish checks run from outside the workspace with an explicit manifest and
registry. This bypasses the generated source replacement for registry-facing package
verification while leaving normal workspace builds on the pnpm-managed offline source.
Ordinary CI jobs restore the pnpm content store and metadata cache with a key that covers
both lockfiles and all workspace manifests. The key is also isolated by the pnpm, Rust,
runner operating system and runner architecture versions. A changed manifest can restore
an older same-platform cache, but the frozen install and offline checks still validate it.
Pull requests never save that cache; only successful master pushes do. Publish checks and
all later release jobs keep caches disabled and materialize their dependencies independently.
Ordinary CI also runs lightweight Windows x64 and macOS arm64 jobs that repeat the frozen
install, generated-source validation and offline Cargo check. The Ubuntu Quality job runs
the full offline Rust tests and all existing project checks.

~~~sh
pnpm install --frozen-lockfile
pnpm run check:pnpm-cargo
pnpm install --frozen-lockfile --offline
cargo +1.98.0 metadata --locked --offline --format-version 1
cargo +1.98.0 check --locked --workspace --offline
cargo +1.98.0 test --locked --workspace --offline
pnpm run check:ts
node scripts/release/run.mjs static
node --test scripts/release/tests/*.test.mjs
cargo +1.98.0 build --release --locked -p ibl_cli
pnpm run ci:fixtures
~~~

The frozen install is the lockfile consistency check and also materializes the pnpm-managed Cargo
source. `pnpm run check:pnpm-cargo` verifies that source before the offline Cargo checks. The
generated source is a build-time dependency location, not a vendored project source.
`node scripts/release/run.mjs static` validates
publication metadata and Cargo.lock without depending on a JavaScript lockfile
format. The generated CI samples live under target/ci-fixtures, never fixtures/outputs.
The latter is ignored by Git and is not present in a clean clone. Set
IBL_FIXTURE_DIR to the absolute target/ci-fixtures path for loader tests and
release consumers. With that environment set, run:

~~~sh
pnpm run test:workspace
node scripts/release/smoke.mjs
pnpm run test:cli
node scripts/release/cli-smoke.mjs
~~~

`pnpm run test:workspace` runs the loader and viewer workspace tests through pnpm's
dependency-aware task scheduler. Loader tests can run concurrently, while each viewer
waits for its workspace loader test. The individual commands remain useful when a single
package needs to be inspected.

The repository toolchain pin is propagated to release-script Cargo subprocesses,
including commands whose working directory is outside the checkout. No manual
`RUSTUP_TOOLCHAIN` setting is needed for release scripts. Set it explicitly only
for standalone commands run outside the checkout. In PowerShell, set other
environment variables using `$env:IBL_FIXTURE_DIR = (Resolve-Path target/ci-fixtures).Path`.

The existing smoke tests package the Rust crates and two loaders, perform Cargo's native multi-package
dry-run, and install archives outside the workspace. The release dependency graph is derived from
Cargo metadata, public workspace manifests and generated CLI manifests; the candidate records the
resulting stable topological order. This is a release graph for the repository's current publishable
artifacts, not a general replacement for Cargo or pnpm dependency resolution. Cargo path dependencies,
public npm workspace dependencies and generated CLI platform dependencies are release-gated; unsupported
or ambiguous publication relationships must fail closed rather than be inferred.
Local smoke checks allow
uncommitted changes; production candidate preparation requires a clean checkout.
Candidate-only Cargo consumer patches point exclusively at extracted, checked
archives. They supplement the native Cargo dry-run and are never used for registry
verification. Registry consumers use exact published versions without local patches.

## Release notes

Before a production run, commit one English note per selected release unit:

- docs/releases/rust-cli-VERSION.md
- docs/releases/npm-ibla-loader-VERSION.md
- docs/releases/npm-ktx2-loader-VERSION.md

Use a heading of "# Rust/CLI VERSION", "# @ibltools/ibla-loader VERSION" or
"# @ibltools/ktx2-loader VERSION", followed by "Date: YYYY-MM-DD". Describe actual
changes, compatibility implications and relevant installation instructions.
These committed notes become the GitHub Release body. Do not invent historical
release notes or mark unreleased packages as published.

Keep this guide synchronized whenever workflows, toolchains, inputs, checks or
recovery rules change. README links here; TODO.md remains the execution checklist.

## Rehearse

1. Merge the implementation or release PR after CI passes.
2. Open Actions → Publish → Run workflow; select master.
3. Select one or more of the four release units and leave dry_run enabled.
4. Inspect the run summary and release-candidate artifact.

The dispatch fixes the commit SHA and package selection. The workflow repeats
quality checks, prepares npm and Cargo archives, and builds Windows x64, macOS
arm64 and Linux x64 binaries when Rust/CLI or npm CLI is selected. Every binary runs a small
both bake and output checks on its own platform.

The candidate includes versions, channels, dependency information, notes,
toolchains, file lists, archive checksums and consumer evidence. Baked Rust output
is parsed by the selected npm archives, or exact current registry readers when
they are not selected. Loader-only consumers use disposable CI fixtures.

Rehearsals accept already-published versions and missing release notes, but label
them **NOT publishable** in the summary. Missing notes use an explicitly marked
rehearsal placeholder. This permits infrastructure acceptance without version
bumps. It is not permission to replace a registry version. For an occupied npm version,
preflight uses packing and external consumers: npm 11.11 rejects that version even
with publish --dry-run. New-version candidates still run native npm publish --dry-run;
its failures are never ignored.

Dry-runs never enter the release approval Environment, request publishing
credentials, upload registry packages, or create Git tags/Releases.

## Publish and verify

Start a new Publish run with the desired selection and dry_run off. A prior
dry-run cannot be promoted into a publishing run. New production runs require
unoccupied versions and valid release notes, and reject npm channel downgrades.

Wait for the candidate and all selected binary builds. Review the exact commit,
package versions, channels, notes, checksums and consumer results before approving
the release Environment. Only the publishing job has OIDC permission. The final
GitHub Release job separately receives repository write permission.

Cargo candidate preparation uses a native multi-package dry-run, and its final
archive hashes must match the approved candidate. Production Cargo uploads use
the release dependency graph one crate at a time. Each crate is checked against
its candidate archive, uploaded, and polled until its crates.io checksum receipt
is confirmed before the next dependent crate is started. npm uploads approved
.tgz files with lifecycle scripts disabled using the same graph. Independent
nodes use a stable package identity order; the CLI entry always follows all of
its platform packages.

Verification downloads registry archives and checks SHA-256, npm channels and
provenance metadata. Clean consumers install exact versions, execute the CLI
and parse outputs. This checks packaging/format interoperability, not visual
rendering quality or GPU decode.

After verification, create tags at the original commit and attach archives,
manifest.json and verified.json to draft Releases before publishing them.
Rust/CLI retains these asset names:

- ibl-baker-vVERSION-windows-x64.zip
- ibl-baker-vVERSION-macos-arm64.tar.gz
- ibl-baker-vVERSION-linux-x64.tar.gz

Stable Rust/CLI releases are marked latest. Component npm releases are not the
repository-wide latest; prerelease versions are marked prerelease. The old
push-tag release trigger is replaced by an internal reusable binary workflow.

## Failures and recovery

Registries cannot publish selected packages atomically. Some versions may become
visible before the full run completes.

- Use **Re-run failed jobs** on the original run after a partial failure.
- A full rerun restores the original candidate; it never replaces it with new
  archives. Rebuilt binary jobs are not substituted into that candidate.
- A version is skipped only when its registry checksum matches the candidate.
  Conflicts and yanked crates stop recovery.
- Dependency publication is registry-gated: a dependent package is not prepared
  or uploaded until every selected dependency has a matching immutable receipt.
- After an upload timeout/error, query registry acceptance before retrying.
  Missing versions are polled for up to ten minutes; authentication, network,
  rate-limit, server and checksum errors fail instead of meaning "available".
- Missing/expired original candidates block automatic recovery. If preparation
  failed before any candidate/upload, investigate and start a fresh run.
- If verification or Release creation fails after publication, rerun failed jobs.
  Completed Releases with all expected archive and evidence assets are checked and left unchanged.
  Missing evidence assets are re-uploaded; checksum conflicts fail instead of being overwritten.
  Tags are never moved.
- Fix npm dist-tag issues interactively with npm authentication; OIDC does not
  authorize arbitrary dist-tag maintenance.
- Correct faulty published contents by releasing a new version. Use npm
  deprecation or Cargo yank separately when appropriate.

Artifacts and evidence are retained for 90 days. The final job uses the verification
artifact's ID so retries can reuse evidence from an earlier attempt.

For manual emergencies, work from the recorded clean commit and original artifacts,
repeat checks and inspect registry state first. Use interactive npm login/2FA or a
scoped crates.io token locally; do not add permanent tokens to CI. Never force an
occupied version through or weaken candidate checks to make a retry pass.

The old @ibltools/loader rename is a separate maintainer operation. Inspect
"npm view @ibltools/loader deprecated"; if still needed, explicitly run:

~~~sh
npm deprecate @ibltools/loader "Package renamed to @ibltools/ibla-loader. Please install @ibltools/ibla-loader instead."
~~~

No workflow performs that deprecation automatically.


## npm CLI distribution

The npm_cli selection releases four packages as one group: @ibltools/cli and
@ibltools/cli-win32-x64, @ibltools/cli-darwin-arm64, @ibltools/cli-linux-x64-gnu.
They share one npm version and exact optional dependency references. Their version
is independent of the Rust group. Starting with npm 0.1.1, --version and -V report
both the npm distribution version and the actual native Rust CLI version. Direct
native execution still reports only the Rust version.
The candidate records both versions, the source SHA, archive hashes and native
binary hashes. Native changes still require the appropriate Rust version update.

The source CLI workspace is private and has no platform dependencies. Public
manifests and payload packages are generated in target/npm-cli-stage. Do not
publish from packages/cli or add generated platform directories to the pnpm workspace.
Every package contains its license and README; the Linux package declares glibc.
Linux uses the existing Ubuntu 24.04 build and runtime baseline, including
libstdc++6. The candidate includes linux-runtime.json with ldd and symbol evidence.

Selecting rust_cli or npm_cli builds the same three native binaries once.
When both are selected, their binary hashes must agree. The CLI's npm packages
are assembled into the immutable candidate before the three consumer jobs run.
Each job installs that exact entry and its native platform tarball outside the
workspace, with scripts disabled, checks local/global command shims and executes
a small both bake plus parser validation. Platform tarballs are explicitly supplied
before publication; registry consumers install only the exact entry version and
let npm resolve optional dependencies. A fresh npm exec then tests npx-style use.

The publishing job depends on all selected candidate consumers. CLI platforms
are uploaded and confirmed before the entry package. Evidence files bind their
mode, platform, source SHA, run ID and all four archive hashes. Publication and
finalization reject missing or mismatched evidence. Reruns consume the original
candidate, including when binary jobs rebuild. A partial CLI upload follows the
same checksum-based recovery rules as the other npm packages.

After publication, three registry consumers run alongside registry integrity,
channel and provenance checks. Release finalization requires both sets of checks.
The npm CLI Release uses npm/cli/vVERSION and docs/releases/npm-cli-VERSION.md
with heading "# @ibltools/cli VERSION". It attaches four npm archives and evidence,
and is never the repository-wide latest Release.

Daily Quality runs `pnpm run test:cli` and `node scripts/release/cli-smoke.mjs` after building
the native CLI. Full candidate and registry consumers run on the three release
platforms. Local CLI smoke needs a release binary but not a clean checkout.
It packs the current workspace loaders so unpublished coordinated loader changes
are tested from local archives instead of being resolved from the registry.
The current release policy conservatively requires `npm_ktx2_loader` whenever `rust_cli` or
`npm_cli` is selected, so the writer and parser versions remain synchronized. This applies even
when a particular change is not known to alter the KTX2 contract; relaxing that coupling requires
explicit contract-version metadata and a separate release-policy change.
Signal tests use real Unix signals and Windows console Ctrl+C.

### First publication

The four package identities completed bootstrap on 2026-09-18 (see below).
The following procedure documents that initial ownership/publication step.
Do not treat a dry-run as proof that these names can be published or that OIDC is
configured. For an explicitly approved bootstrap release, use the reviewed candidate
archives with interactive npm authentication, publish the platform packages first,
verify their registry integrity, and publish the entry last. Never publish empty
placeholder packages or rebuild approved archives during bootstrap.

Configure each new package's Trusted Publisher for shawn0326/ibl-baker,
publish.yml, Environment release, with Allow npm publish enabled. Thereafter use
a new version and the normal OIDC workflow. An interactive initial upload does
not substitute for this workflow's provenance verification; do not weaken that
check to accept bootstrap uploads. Keep initial-publication receipts separate.

### npm CLI bootstrap on 2026-09-18

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

### npm CLI rollout evidence

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

## Rollout evidence

CI and the all-group rehearsal must pass before marking infrastructure rollout
complete. Record the PR/run links and remaining real-publication validation here.
Do not treat rehearsals as proof of OIDC authorization, registry checksums after
upload, provenance, or real partial-failure recovery.

Rollout on 2026-09-17:

- [Implementation PR #1](https://github.com/shawn0326/ibl-baker/pull/1) merged as e2bc2848e2ac9b1779947e37dcb7791812d8024e.
- [Implementation PR CI](https://github.com/shawn0326/ibl-baker/actions/runs/35194599409): passed.
- [Master CI and Pages deployment](https://github.com/shawn0326/ibl-baker/actions/runs/35195117843): passed.
- Master protection was read back after configuration: required PR, checks / Quality from GitHub Actions, strict status checks, administrator enforcement, no force pushes/deletion, zero required approving reviews.
- Local validation passed: 61 Rust tests, 22 loader tests, both viewer builds, TypeScript, 17 release/recovery tests, actionlint, Cargo dry-runs and archive consumers. Existing registry versions also passed exact-version consumer checks; no registry uploads were performed.

The [first all-group rehearsal](https://github.com/shawn0326/ibl-baker/actions/runs/35195133128)
passed all three platform builds and quality checks, then exposed npm 11.11 rejecting
occupied versions during native publish dry-run. The rehearsal-only preflight rule
above addresses that behavior; production availability checks remain unchanged.

- [Rehearsal compatibility fix PR #2](https://github.com/shawn0326/ibl-baker/pull/2) merged as 559ed79d5a4e026e002ce4ed6a4c0abcab2b33d4.
- [Fix PR CI](https://github.com/shawn0326/ibl-baker/actions/runs/35195891602): passed, including 18 release/recovery tests.
- [Updated master CI and Pages](https://github.com/shawn0326/ibl-baker/actions/runs/35196398791): passed.
- Each loader also passed an independent archive-consumer check against temporary fixtures without selecting Rust.
- [Successful all-group rehearsal](https://github.com/shawn0326/ibl-baker/actions/runs/35196405209): passed on 559ed79d5a4e026e002ce4ed6a4c0abcab2b33d4. All five package archives, Windows x64/macOS arm64/Linux x64 binaries and external candidate consumers passed.
- Downloaded release-candidate artifact 10486711223 and independently verified every package/binary SHA-256 and release-note checksum. Toolchain evidence matches Node 24.19.0, npm 11.11.0 and Cargo 1.98.0.
- The three crates remain 0.2.1 and both loaders remain 0.2.0. All five occupied versions and missing new release notes are explicitly marked NOT publishable. The publish, verify and finalize jobs were skipped; no registry upload, tag or Release was created.
- Infrastructure acceptance is complete. Actual five-package OIDC publication, npm provenance after upload, production verification/Release finalization and real partial-failure recovery remain for the next explicitly selected release. Recovery behavior is currently covered by simulated tests.
