# Release Process

This is the operational guide for CI, release preparation, publishing and recovery.
Ordinary commits and pull requests never publish packages. The workflow does not
change versions or refresh local fixtures.

## Verified release status

The [2026-09-29 production release](release-history.md#production-release-2026-09-29)
verified OIDC publication, registry integrity, npm provenance, registry consumers
and GitHub Release finalization for eight selected packages: Rust/CLI 0.2.3
(three crates), @ibltools/ktx2-loader 0.3.0, and the four-package npm CLI 0.1.1 group.
All three npm CLI platform consumers passed. The .ibla loader was not selected,
so this run does not establish its production OIDC acceptance.

The existing CLI package identities completed bootstrap on 2026-09-18 and ordinary
registry installation is verified. Real recovery after a partial production
publication remains untested; ordering and checksum safeguards have simulated
coverage. Record real recovery evidence when it naturally occurs.
Historical rollout, bootstrap and rehearsal records live in [Release History](release-history.md).

## Release units and versions

| Input | Contents | Version source | GitHub tag |
| --- | --- | --- | --- |
| rust_cli | ktx2_writer, ibl_core, ibl_cli and three CLI binaries | Cargo workspace version | vVERSION |
| npm_ibla_loader | @ibltools/ibla-loader | Its package.json | npm/ibla-loader/vVERSION |
| npm_ktx2_loader | @ibltools/ktx2-loader | Its package.json | npm/ktx2-loader/vVERSION |
| npm_cli | @ibltools/cli and three platform packages | CLI workspace package.json | npm/cli/vVERSION |

Rust crates remain one coordinated group, ordered as ktx2_writer, ibl_core,
ibl_cli. Their internal dependency versions must match the workspace version.
The npm loaders have independent versions. The private Pages site is never published;
update its loader dependency references when bumping loaders so development continues
to use the workspace packages.

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
have been reported complete by the maintainer. The four CLI package identities
completed bootstrap on 2026-09-18 and successful OIDC publishing on 2026-09-29;
see [Release History](release-history.md). Apply the first-publication procedure
below only when introducing a new package identity.
The release Environment has been checked through the API. A dry-run cannot prove
registry authorization or provenance: mark those verified only after a real release.
For a new package, establish its ownership/initial publication before depending
on package-specific trusted publishing. After successful OIDC publishing, revoke
obsolete publish tokens and restrict traditional npm token publishing.

## Daily CI and local checks

Pushes to master, pull requests, and manually dispatched CI run the same quality
checks used by Publish. Only successful master CI deploys the private site to Pages.
master requires a PR and the CI Gate status check from GitHub Actions, including
for administrators. CI Gate waits for the complete reusable checks workflow,
including Linux Quality and both Windows/macOS Cargo checks. It always runs and
accepts only a success result; failure, cancellation or a skipped checks workflow
cannot pass. Pages deployment is separate from this merge gate.
Another person's PR approval is not required. Force pushes and branch deletion
are forbidden.

When adding or changing required jobs, keep them unconditional for ordinary CI
and confirm that their results are covered by CI Gate. Migrate branch protection
by adding CI Gate alongside the existing required check after PR validation;
remove the old requirement only after master CI and Pages succeed. Keep the
strict status policy and all other protection settings unchanged.

Toolchains are Node 24.19.0, pnpm 12.5.1, npm 11.11.0 and Rust/Cargo 1.98.0.
The repository pins Rust/Cargo through `rust-toolchain.toml`; commands run from
the checkout therefore use the release toolchain automatically. Commands run
outside the checkout, such as registry consumers, should set `RUSTUP_TOOLCHAIN`
explicitly when they must use the same toolchain.
pnpm manages the JavaScript workspace and npm 11.11.0 is resolved directly by the
release scripts for npm packing, publishing and consumer checks. The npm wrapper removes
pnpm-only configuration before invoking npm. Actions are pinned to reviewed commit SHAs.
Release builds do not restore PR caches.

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
pnpm run check:source
cargo +1.98.0 metadata --locked --offline --format-version 1
pnpm run check:fmt
pnpm run check:clippy
cargo +1.98.0 check --locked --workspace --offline
cargo +1.98.0 test --locked --workspace --offline
pnpm run check:ts
node scripts/release/run.mjs static
node --test scripts/release/tests/*.test.mjs
cargo +1.98.0 build --release --locked -p ibl_cli
pnpm run ci:fixtures
~~~

The frozen install is the lockfile consistency check and also materializes the pnpm-managed Cargo
source. `pnpm run check:pnpm-cargo` verifies that source before the offline Cargo checks.
`pnpm run check:fmt` enforces the rustfmt baseline, and `pnpm run check:clippy` treats all Clippy
warnings across workspace targets and features as errors. `pnpm run check:source` validates every
tracked JavaScript file with Node.js and parses every tracked JSON file. The generated source is a
build-time dependency location, not a vendored project source.
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

`pnpm run test:workspace` runs the loader and site workspace tests through pnpm's
dependency-aware task scheduler. Loader tests can run concurrently, while the site waits
for its workspace loaders. The individual commands remain useful when a single package
needs to be inspected.

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
- docs/releases/npm-cli-VERSION.md

Use a heading of "# Rust/CLI VERSION", "# @ibltools/ibla-loader VERSION",
"# @ibltools/ktx2-loader VERSION" or "# @ibltools/cli VERSION", followed by
"Date: YYYY-MM-DD". Describe actual changes, compatibility implications and
relevant installation instructions.
The heading is retained in the committed note for validation and archival. When
the workflow creates a GitHub Release, it uses that heading as the release title
and removes the first heading from the body to avoid repeating it. Do not invent
historical release notes or mark unreleased packages as published.

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

The existing four CLI package identities have completed bootstrap; their
[dated evidence](release-history.md#npm-cli-bootstrap-and-rollout-2026-09-18) is archived.
Use the following ownership/publication procedure for new package identities.
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
