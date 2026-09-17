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

Rust crates remain one coordinated group, ordered as ktx2_writer, ibl_core,
ibl_cli. Their internal dependency versions must match the workspace version.
The npm loaders have independent versions. Viewer packages are private and are
never published; update their loader dependency references when bumping loaders
so development continues to use the workspace packages.

Only change versions for consumer-facing changes. CI, website and release
infrastructure changes do not require a package release. Update the relevant
manifests, Cargo.lock and package-lock.json in a release PR. The workflow never
chooses a version or bumps it for you.

## One-time configuration

Configure a GitHub Trusted Publisher separately on each of the five packages:

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

Trusted Publisher configurations have been reported complete by the maintainer.
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

Toolchains are Node 24.19.0, npm 11.11.0 and Rust/Cargo 1.98.0. Actions are pinned
to reviewed commit SHAs. Release builds do not restore PR caches.

~~~sh
npm ci
cargo +1.98.0 check --locked --workspace
cargo +1.98.0 test --locked --workspace
npm run check:ts
npm run release:check
npm run release:test
cargo +1.98.0 build --release --locked -p ibl_cli
npm run ci:fixtures
~~~

The generated CI samples live under target/ci-fixtures, never fixtures/outputs.
The latter is ignored by Git and is not present in a clean clone. Set
IBL_FIXTURE_DIR to the absolute target/ci-fixtures path for loader tests and
release consumers. With that environment set, run:

~~~sh
npm run test:js
npm run test:ibla-viewer
npm run test:ktx2-viewer
npm run release:smoke
~~~

Use RUSTUP_TOOLCHAIN=1.98.0 when running release scripts. In PowerShell, set
environment variables using $env:RUSTUP_TOOLCHAIN = '1.98.0' and
$env:IBL_FIXTURE_DIR = (Resolve-Path target/ci-fixtures).Path.

Smoke tests package all five packages, perform Cargo's native multi-package
dry-run, and install archives outside the workspace. Local smoke checks allow
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
3. Select one or more of the three release units and leave dry_run enabled.
4. Inspect the run summary and release-candidate artifact.

The dispatch fixes the commit SHA and package selection. The workflow repeats
quality checks, prepares npm and Cargo archives, and builds Windows x64, macOS
arm64 and Linux x64 binaries when Rust/CLI is selected. Every binary runs a small
both bake and output checks on its own platform.

The candidate includes versions, channels, dependency information, notes,
toolchains, file lists, archive checksums and consumer evidence. Baked Rust output
is parsed by the selected npm archives, or exact current registry readers when
they are not selected. Loader-only consumers use disposable CI fixtures.

Rehearsals accept already-published versions and missing release notes, but label
them **NOT publishable** in the summary. Missing notes use an explicitly marked
rehearsal placeholder. This permits infrastructure acceptance without version
bumps. It is not permission to replace a registry version.

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

Cargo publishes in dependency order using a native multi-package command. Its
final dry-run archive hashes must match the approved candidate; archives are
checked again after upload. npm uploads the approved .tgz files with lifecycle
scripts disabled, in IBLA then KTX2 order.

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

Registries cannot publish five packages atomically. Some versions may become
visible before the full run completes.

- Use **Re-run failed jobs** on the original run after a partial failure.
- A full rerun restores the original candidate; it never replaces it with new
  archives. Rebuilt binary jobs are not substituted into that candidate.
- A version is skipped only when its registry checksum matches the candidate.
  Conflicts and yanked crates stop recovery.
- After an upload timeout/error, query registry acceptance before retrying.
  Missing versions are polled for up to ten minutes; authentication, network,
  rate-limit, server and checksum errors fail instead of meaning "available".
- Missing/expired original candidates block automatic recovery. If preparation
  failed before any candidate/upload, investigate and start a fresh run.
- If verification or Release creation fails after publication, rerun failed jobs.
  Completed Releases are checked and left unchanged. Tags are never moved.
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

## Rollout evidence

CI and the all-group rehearsal must pass before marking infrastructure rollout
complete. Record the PR/run links and remaining real-publication validation here.
Do not treat rehearsals as proof of OIDC authorization, registry checksums after
upload, provenance, or real partial-failure recovery.
