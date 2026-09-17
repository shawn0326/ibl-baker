import test from 'node:test';
import assert from 'node:assert/strict';
import { waitForVersion, publishNpmPackages, publishCargoPackages } from '../publication.mjs';
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
test('npm rejects conflicting receipts and channel downgrades before upload', async () => {
    let uploads = 0;
    const upload = async () => uploads++;
    await assert.rejects(publishNpmPackages([npmPkg('snapshot')], { ...clock(), upload,
        lookup: async () => ({ dist: { integrity: 'conflict' } }), checkChannel: async () => {} }), /differs/);
    await assert.rejects(publishNpmPackages([npmPkg('snapshot')], { ...clock(), upload,
        lookup: async () => null, checkChannel: async () => { throw new Error('backwards'); } }), /backwards/);
    assert.equal(uploads, 0);
});
test('Cargo partial batch failure resumes only the remaining approved archive', async () => {
    const packages = ['snapshot', 'runtime'].map(name => ({ name, version: '1.0.0', registry: 'cargo', sha256: 'approved-' + name }));
    const registry = new Map(), batches = [], prepared = [], checked = [];
    let first = true;
    const callbacks = {
        lookup: async p => registry.get(p.name) ?? null,
        prepare: async items => prepared.push(items.map(p => p.name)),
        checkArchives: async items => checked.push(items.map(p => p.name)),
        upload: async items => {
            batches.push(items.map(p => p.name));
            registry.set(items[0].name, receipt(items[0]));
            if (first) { first = false; throw new Error('partial upload'); }
        },
    };
    await assert.rejects(publishCargoPackages(packages, { ...clock(), ...callbacks }), /visibility timeout/);
    await publishCargoPackages(packages, { ...clock(), ...callbacks });
    assert.deepEqual(batches, [['snapshot', 'runtime'], ['runtime']]);
    assert.deepEqual(prepared, batches);
    assert.deepEqual(checked, batches);
    assert.equal(registry.size, 2);
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
