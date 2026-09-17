import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { catalog, read, selectPackages, validateSelection, channel, assertChannelAdvance, assertResume,
    assertContext, assertExistingRelease, assertNotes } from '../core.mjs';

test('three groups expand in Cargo dependency order and retain independent npm versions', () => {
    const all = catalog();
    assert.deepEqual(selectPackages(all, { rust_cli: true }).map(p => p.name), ['ktx2_writer', 'ibl_core', 'ibl_cli']);
    assert.equal(selectPackages(all, { npm_ibla_loader: true }).length, 1);
    assert.equal(selectPackages(all, { rust_cli: true, npm_ibla_loader: true, npm_ktx2_loader: true }).length, 5);
    assert.throws(() => selectPackages(all, {}), /Select/);
    assert.throws(() => selectPackages(all, { rust_cli: 'true' }), /Invalid/);
    assert.throws(() => selectPackages(all, { private_viewer: true }), /Invalid/);
});
test('workspace version and internal dependencies cannot drift', () => {
    assert.throws(() => catalog(path => path === 'crates/ibl_cli/Cargo.toml'
        ? read(path).replace('version = "' + catalog()[0].version + '"', 'version = "99.0.0"') : read(path)), /dependency/);
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
    const release = { body: 'marker', draft: false, assets: [{ name: 'bin.zip', digest: 'sha256:abc' }, { name: 'p.crate', digest: 'sha256:def' }] };
    assert.equal(assertExistingRelease(undefined, undefined, group, 'sha', 'marker'), false);
    assert.equal(assertExistingRelease({ ...release, draft: true }, 'sha', group, 'sha', 'marker'), false);
    assert.equal(assertExistingRelease(release, 'sha', group, 'sha', 'marker'), true);
    assert.throws(() => assertExistingRelease(release, 'other', group, 'sha', 'marker'), /commit/);
    assert.throws(() => assertExistingRelease({ ...release, assets: [] }, 'sha', group, 'sha', 'marker'), /assets/);
    assert.throws(() => assertExistingRelease({ ...release, body: 'other' }, 'sha', group, 'sha', 'marker'), /different candidate/);
});
test('release notes use the group heading and require a dated entry', () => {
    const p = catalog()[0];
    assertNotes('# Rust/CLI ' + p.version + '\n\nDate: 2026-09-17\n\nChanges.\n', p);
    assert.throws(() => assertNotes('# Placeholder\n', p), /notes/);
});
