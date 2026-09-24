import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { catalog, read, selectPackages, validateSelection, channel, assertChannelAdvance, assertResume,
    assertContext, assertExistingRelease, assertNotes } from '../core.mjs';

function cargoMetadata() {
    const result = spawnSync('cargo', ['metadata', '--no-deps', '--format-version', '1', '--locked'], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    return JSON.parse(result.stdout);
}

test('three groups expand in Cargo dependency order and retain independent npm versions', () => {
    const all = catalog();
    assert.deepEqual(selectPackages(all, { rust_cli: true, npm_ktx2_loader: true }).filter(p => p.group === 'rust_cli').map(p => p.name), ['ktx2_writer', 'ibl_core', 'ibl_cli']);
    assert.equal(selectPackages(all, { npm_ibla_loader: true }).length, 1);
    assert.equal(selectPackages(all, { rust_cli: true, npm_ibla_loader: true, npm_ktx2_loader: true }).length, 5);
    assert.throws(() => selectPackages(all, {}), /Select/);
    assert.throws(() => selectPackages(all, { rust_cli: 'true' }), /Invalid/);
    assert.throws(() => selectPackages(all, { private_viewer: true }), /Invalid/);
});
test('Cargo release dependencies come from metadata rather than package declaration order', () => {
    const metadata = cargoMetadata();
    metadata.packages.reverse();
    metadata.workspace_members.reverse();
    const rust = catalog(read, metadata).filter(p => p.registry === 'cargo');
    assert.deepEqual(rust.map(p => p.name), ['ktx2_writer', 'ibl_core', 'ibl_cli']);
    assert.deepEqual(rust[1].dependencies, [{ registry: 'cargo', name: 'ktx2_writer', version: rust[0].version }]);
    assert.deepEqual(rust[2].dependencies, [{ registry: 'cargo', name: 'ibl_core', version: rust[0].version }]);
});
test('Cargo metadata publish filters and renamed path dependencies are represented in the graph', () => {
    const metadata = cargoMetadata();
    const writer = metadata.packages.find(p => p.name === 'ktx2_writer');
    const core = metadata.packages.find(p => p.name === 'ibl_core');
    const cli = metadata.packages.find(p => p.name === 'ibl_cli');
    cli.publish = ['private-registry'];
    core.dependencies.find(p => p.name === writer.name).rename = 'writer_alias';
    const cargo = catalog(read, metadata).filter(p => p.registry === 'cargo');
    assert.deepEqual(cargo.map(p => p.name), ['ktx2_writer', 'ibl_core']);
    assert.deepEqual(cargo[1].dependencies, [{ registry: 'cargo', name: 'ktx2_writer', version: writer.version }]);
});
test('workspace version and internal dependencies cannot drift', () => {
    const metadata = cargoMetadata();
    metadata.packages.find(p => p.name === 'ibl_cli').dependencies.find(p => p.name === 'ibl_core').req = '^99.0.0';
    assert.throws(() => catalog(read, metadata), /dependency/);
});
test('published Cargo packages cannot depend on non-publishable workspace members', () => {
    const metadata = cargoMetadata();
    metadata.packages.find(p => p.name === 'ibl_core').publish = [];
    assert.throws(() => catalog(read, metadata), /non-publishable workspace package/);
});
test('occupied versions are reported in rehearsals and rejected in new production runs', async () => {
    const pkg = selectPackages(catalog(), { npm_ibla_loader: true });
    assert.deepEqual(await validateSelection(pkg, true, async () => ({})), [pkg[0].name + '@' + pkg[0].version]);
    await assert.rejects(validateSelection(pkg, false, async () => ({})), /already published/);
    await assert.rejects(validateSelection(pkg, true, async () => { throw new Error('offline'); }), /offline/);
    await assert.rejects(validateSelection(catalog().filter(p => p.name === 'ibl_cli'), true, async () => null), /dependency/);
});
test('channels distinguish numeric prereleases and reject downgrade', () => {
    assert.equal(channel('1.0.0'), 'latest');
    assert.equal(channel('1.0.0-beta.2'), 'next');
    assert.throws(() => channel('v1.0.0'), /Invalid/);
    assert.throws(() => assertChannelAdvance({ name: 'p', version: '1.0.0-beta.2', channel: 'next' }, { next: '1.0.0-beta.10' }), /backwards/);
    assertChannelAdvance({ version: '1.0.0', channel: 'latest' }, null);
});
test('candidate identity includes SHA, run, selection and dry-run mode', () => {
    const m = { schema: 1, sha: 'a', runId: '1', dryRun: true, packages: [{ id: 'p' }] };
    const expected = { sha: 'a', runId: '1', dryRun: true, ids: ['p'] };
    assertResume(m, expected);
    for (const changed of [{ sha: 'b' }, { runId: '2' }, { dryRun: false }, { ids: [] }]) assert.throws(() => assertResume(m, { ...expected, ...changed }), /Candidate/);
});
test('publishing context is restricted to the original master dispatch', () => {
    const sha = 'a'.repeat(40);
    const env = { GITHUB_REPOSITORY: 'shawn0326/ibl-baker', GITHUB_REF: 'refs/heads/master', GITHUB_EVENT_NAME: 'workflow_dispatch',
        GITHUB_WORKFLOW_REF: 'shawn0326/ibl-baker/.github/workflows/publish.yml@refs/heads/master', GITHUB_SHA: sha, GITHUB_RUN_ID: '123' };
    assertContext(env, sha);
    for (const changed of [{ GITHUB_REF: 'refs/heads/other' }, { GITHUB_EVENT_NAME: 'push' }, { GITHUB_SHA: 'b'.repeat(40) }]) assert.throws(() => assertContext({ ...env, ...changed }, sha), /requires/);
});
test('every mutating command is blocked unless dry_run is explicitly false', () => {
    for (const command of ['publish-cargo', 'publish-npm', 'finalize']) {
        const result = spawnSync(process.execPath, ['scripts/release/run.mjs', command], { encoding: 'utf8', env: { ...process.env, RELEASE_INPUTS: '{"rust_cli":true,"dry_run":true}' } });
        assert.notEqual(result.status, 0);
        assert.match(result.stderr, /Publishing is disabled/);
    }
});
test('release finalization resumes a matching draft or skips a matching published release', () => {
    const group = { tag: 'v1.0.0', assets: [{ archive: 'bin.zip', sha256: 'abc' }, { archive: 'p.crate', sha256: 'def' }] };
    const evidence = [{ archive: 'manifest.json', sha256: 'manifest' }, { archive: 'verified.json', sha256: 'verified' }];
    const release = { body: 'marker', draft: false, assets: [
        { name: 'bin.zip', digest: 'sha256:abc' }, { name: 'p.crate', digest: 'sha256:def' },
        { name: 'manifest.json', digest: 'sha256:manifest' }, { name: 'verified.json', digest: 'sha256:verified' },
    ] };
    assert.equal(assertExistingRelease(undefined, undefined, group, 'sha', 'marker'), false);
    assert.equal(assertExistingRelease({ ...release, draft: true }, 'sha', group, 'sha', 'marker'), false);
    assert.throws(() => assertExistingRelease({ ...release, draft: true, assets: release.assets.map(a => a.name === 'manifest.json' ? { ...a, digest: 'sha256:wrong' } : a) }, 'sha', group, 'sha', 'marker', evidence), /assets/);
    assert.equal(assertExistingRelease(release, 'sha', group, 'sha', 'marker', evidence), true);
    assert.equal(assertExistingRelease({ ...release, assets: release.assets.slice(0, 2) }, 'sha', group, 'sha', 'marker', evidence), false);
    assert.throws(() => assertExistingRelease({ ...release, assets: release.assets.slice(0, 2).concat({ name: 'manifest.json', digest: 'sha256:wrong' }) }, 'sha', group, 'sha', 'marker', evidence), /assets/);
    assert.throws(() => assertExistingRelease(release, 'other', group, 'sha', 'marker', evidence), /commit/);
    assert.throws(() => assertExistingRelease({ ...release, assets: release.assets.map(a => a.name === 'verified.json' ? { ...a, digest: 'sha256:wrong' } : a) }, 'sha', group, 'sha', 'marker', evidence), /assets/);
    assert.throws(() => assertExistingRelease({ ...release, body: 'other' }, 'sha', group, 'sha', 'marker'), /different candidate/);
});
test('release notes use the group heading and require a dated entry', () => {
    const p = catalog()[0];
    assertNotes('# Rust/CLI ' + p.version + '\n\nDate: 2026-09-17\n\nChanges.\n', p);
    assert.throws(() => assertNotes('# Placeholder\n', p), /notes/);
});

test('npm CLI forms an independent complete release group with exact platform dependencies', () => {
    const all = catalog(), cli = selectPackages(all, { npm_cli: true, npm_ktx2_loader: true }).filter(p => p.group === 'npm_cli');
    assert.equal(cli.length, 4);
    assert.deepEqual(cli.map(p => p.kind), ['cli-platform', 'cli-platform', 'cli-platform', 'cli']);
    assert.equal(new Set(cli.map(p => p.version)).size, 1);
    assert.equal(new Set(cli.map(p => p.tag)).size, 1);
    assert.equal(cli[3].binaryVersion, all[0].version);
    assert.deepEqual(cli[3].dependencies, cli.slice(0, 3).map(p => ({ registry: 'npm', name: p.name, version: p.version })));
    assert.equal(selectPackages(all, { rust_cli: true, npm_cli: true, npm_ktx2_loader: true }).length, 8);
    assert.equal(selectPackages(all, { rust_cli: true, npm_cli: true, npm_ibla_loader: true, npm_ktx2_loader: true }).length, 9);
});
test('native KTX2 producers require the matching KTX2 loader release', () => {
    const all = catalog();
    assert.throws(() => selectPackages(all, { rust_cli: true }), /npm_ktx2_loader/);
    assert.throws(() => selectPackages(all, { npm_cli: true }), /npm_ktx2_loader/);
});
test('an incomplete CLI group cannot pass dependency validation', async () => {
    const entry = catalog().find(p => p.kind === 'cli');
    await assert.rejects(validateSelection([entry], true, async () => null), /Missing selected dependency/);
});
test('private source workspace does not depend on unpublished platform packages', () => {
    const source = JSON.parse(read('packages/cli/package.json'));
    assert.equal(source.private, true);
    assert.equal(source.optionalDependencies, undefined);
    assert.equal(source.scripts.postinstall, undefined);
});
