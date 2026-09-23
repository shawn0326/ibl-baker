import test from 'node:test';
import assert from 'node:assert/strict';
import { waitForVersion, publishNpmPackages, publishCargoPackages, validateNpmCandidate } from '../publication.mjs';
import { getJson } from '../core.mjs';

const npmPkg = name => ({ name, registry: 'npm', version: '1.0.0-beta.2', integrity: 'sha512-approved' });
const receipt = pkg => pkg.registry === 'npm' ? { dist: { integrity: pkg.integrity } } : { checksum: pkg.sha256 };
function clock() {
    let time = 0;
    const events = [], sleeps = [];
    return { now: () => time, sleep: async ms => { sleeps.push(ms); time += ms; },
        emit: event => events.push(event), events, sleeps };
}
test('visibility polling stays at ten seconds and reports progress every thirty seconds', async () => {
    const c = clock(), pkg = npmPkg('snapshot');
    await waitForVersion(pkg, { ...c, lookup: async () => c.now() < 70000 ? null : receipt(pkg) });
    assert.deepEqual(c.events.filter(e => e.phase === 'registry-wait').map(e => e.elapsedMs), [0, 30000, 60000]);
    assert.equal(c.events.at(-1).phase, 'registry-confirmed');
    assert.equal(c.events.at(-1).elapsedMs, 70000);
    assert.ok(c.sleeps.every(ms => ms === 10000));
});
test('missing version times out at ten minutes using a simulated clock', async () => {
    const c = clock();
    await assert.rejects(waitForVersion(npmPkg('snapshot'), { ...c, lookup: async () => null }), /visibility timeout/);
    assert.equal(c.now(), 600000);
    assert.equal(c.events.at(-1).phase, 'registry-failed');
});
test('registry authentication, network and checksum failures are never treated as absence', async () => {
    for (const status of [401, 403, 429, 500]) {
        const c = clock();
        const lookup = () => getJson('https://example.invalid', { allowMissing: true,
            fetcher: async () => new Response('', { status }) });
        await assert.rejects(waitForVersion(npmPkg('snapshot'), { ...c, lookup }), /HTTP/);
        assert.equal(c.sleeps.length, 0);
    }
    for (const lookup of [async () => { throw new Error('offline'); }, async () => ({ dist: { integrity: 'wrong' } })]) {
        const c = clock();
        await assert.rejects(waitForVersion(npmPkg('snapshot'), { ...c, lookup }), /offline|differs/);
        assert.equal(c.sleeps.length, 0);
    }
});
test('404 responses are polled until the immutable registry receipt appears', async () => {
    const c = clock(), pkg = npmPkg('snapshot');
    const lookup = () => getJson('https://example.invalid', { allowMissing: true,
        fetcher: async () => c.now() < 10000 ? new Response('', { status: 404 }) : Response.json(receipt(pkg)) });
    await waitForVersion(pkg, { ...c, lookup });
    assert.equal(c.now(), 10000);
});
test('npm resumes a partial release without reuploading matching packages', async () => {
    const a = npmPkg('snapshot'), b = npmPkg('webgpu'), c = clock(), uploaded = [], checked = [];
    const registry = new Map([[a.name, receipt(a)]]);
    await publishNpmPackages([a, b], { ...c, lookup: async p => registry.get(p.name) ?? null,
        checkChannel: async p => checked.push(p.name),
        upload: async p => { uploaded.push(p.name); registry.set(p.name, receipt(p)); throw new Error('lost upload response'); } });
    assert.deepEqual(uploaded, [b.name]);
    assert.deepEqual(checked, [b.name]);
    assert.equal(c.events.find(e => e.phase === 'upload-finished').outcome, 'uncertain');
    assert.equal(c.events.at(-1).phase, 'registry-confirmed');
});
test('npm confirms dependencies before uploading dependents even when input is reversed', async () => {
    const core = npmPkg('core'), app = { ...npmPkg('app'), dependencies: [{ registry: 'npm', name: core.name, version: core.version }] };
    const registry = new Map(), events = [];
    await publishNpmPackages([app, core], {
        ...clock(),
        lookup: async p => registry.get(p.name) ?? null,
        checkChannel: async () => {},
        upload: async p => {
            events.push('upload:' + p.name);
            if (p === app) assert.ok(registry.has(core.name));
            registry.set(p.name, receipt(p));
        },
        emit: event => { if (event.phase === 'registry-confirmed') events.push('confirmed:' + event.name); },
    });
    assert.deepEqual(events, ['upload:core', 'confirmed:core', 'upload:app', 'confirmed:app']);
});
test('npm rejects conflicting receipts and channel downgrades before upload', async () => {
    let uploads = 0;
    const upload = async () => uploads++;
    await assert.rejects(publishNpmPackages([npmPkg('snapshot')], { ...clock(), upload,
        lookup: async () => ({ dist: { integrity: 'conflict' } }), checkChannel: async () => {} }), /differs/);
    await assert.rejects(publishNpmPackages([npmPkg('snapshot')], { ...clock(), upload,
        lookup: async () => null, checkChannel: async () => { throw new Error('backwards'); } }), /backwards/);
    assert.equal(uploads, 0);
});
test('Cargo partial publication resumes only the remaining approved archive', async () => {
    const packages = ['snapshot', 'runtime'].map(name => ({ name, version: '1.0.0', registry: 'cargo', sha256: 'approved-' + name, dependencies: [] }));
    const registry = new Map(), uploads = [], prepared = [], checked = [];
    let first = true, failSnapshot = true;
    const callbacks = {
        lookup: async p => registry.get(p.name) ?? null,
        prepare: async pkg => prepared.push(pkg.name),
        checkArchives: async pkg => checked.push(pkg.name),
        upload: async pkg => {
            uploads.push(pkg.name);
            if (pkg.name === 'runtime' && first) {
                first = false;
                registry.set(pkg.name, receipt(pkg));
                throw new Error('lost upload response');
            }
            if (pkg.name === 'snapshot' && failSnapshot) { failSnapshot = false; throw new Error('partial upload'); }
            registry.set(pkg.name, receipt(pkg));
         },
    };
    await assert.rejects(publishCargoPackages(packages, { ...clock(), ...callbacks }), /visibility timeout/);
    await publishCargoPackages(packages, { ...clock(), ...callbacks });
    assert.deepEqual(uploads, ['runtime', 'snapshot', 'snapshot']);
    assert.deepEqual(prepared, ['runtime', 'snapshot', 'snapshot']);
    assert.deepEqual(checked, ['runtime', 'snapshot', 'snapshot']);
    assert.equal(registry.size, 2);
});
test('Cargo confirms dependencies before preparing dependents', async () => {
    const core = { name: 'core', version: '1.0.0', registry: 'cargo', sha256: 'approved-core', dependencies: [] };
    const cli = { name: 'cli', version: '1.0.0', registry: 'cargo', sha256: 'approved-cli',
        dependencies: [{ registry: 'cargo', name: core.name, version: core.version }] };
    const registry = new Map(), events = [];
    await publishCargoPackages([cli, core], {
        ...clock(),
        lookup: async p => registry.get(p.name) ?? null,
        prepare: async p => {
            events.push('prepare:' + p.name);
            if (p === cli) assert.ok(registry.has(core.name));
        },
        upload: async p => { events.push('upload:' + p.name); registry.set(p.name, receipt(p)); },
        checkArchives: async p => events.push('checked:' + p.name),
        emit: event => { if (event.phase === 'registry-confirmed') events.push('confirmed:' + event.name); },
    });
    assert.deepEqual(events, [
        'prepare:core', 'upload:core', 'checked:core', 'confirmed:core',
        'prepare:cli', 'upload:cli', 'checked:cli', 'confirmed:cli',
    ]);
});
test('Cargo archive mismatch blocks upload and yanked receipts block resume', async () => {
    const pkg = { name: 'snapshot', version: '1.0.0', registry: 'cargo', sha256: 'approved' };
    let uploads = 0;
    const callbacks = { ...clock(), upload: async () => uploads++, checkArchives: async () => {},
        prepare: async () => { throw new Error('archive differs'); } };
    await assert.rejects(publishCargoPackages([pkg], { ...callbacks, lookup: async () => null }), /archive differs/);
    await assert.rejects(publishCargoPackages([pkg], { ...callbacks, lookup: async () => ({ checksum: 'approved', yanked: true }) }), /yanked/);
    assert.equal(uploads, 0);
});

test("occupied npm rehearsals skip only the native publish check, never new-version errors", async () => {
    const pkg = npmPkg('reader'), occupied = [pkg.name + '@' + pkg.version];
    let checks = 0;
    const validate = async () => { checks++; throw new Error('native preflight failed'); };
    assert.equal(await validateNpmCandidate(pkg, { dryRun: true, occupied, validate }), 'occupied-rehearsal');
    assert.equal(checks, 0);
    await assert.rejects(validateNpmCandidate(pkg, { dryRun: true, occupied: [], validate }), /native preflight/);
    await assert.rejects(validateNpmCandidate(pkg, { dryRun: false, occupied, validate }), /native preflight/);
    assert.equal(checks, 2);
    assert.equal(await validateNpmCandidate(pkg, { dryRun: false, occupied: [], validate: async () => {} }), 'checked');
});
