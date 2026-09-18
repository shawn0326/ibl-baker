import test from 'node:test';
import assert from 'node:assert/strict';
import { catalog, platforms } from '../core.mjs';
import { assertCliEvidence } from '../cli-consumer.mjs';
import { publishNpmPackages } from '../publication.mjs';

const candidate = () => ({ sha: 'commit', runId: '42', packages: catalog().filter(p => p.group === 'npm_cli').map(p => ({ ...p, sha256: 'sha-' + p.name, integrity: 'integrity-' + p.name })) });
const reports = (v, mode) => Object.fromEntries(platforms.map(platform => ['cli-' + mode + '-' + platform + '.json', {
    status: 'passed', mode, platform, sha: v.sha, runId: v.runId, archives: v.packages.map(p => ({ name: p.name, sha256: p.sha256 })),
}]));
test('CLI publication requires all three reports from the exact candidate', () => {
    const v = candidate(), evidence = reports(v, 'candidate');
    assertCliEvidence(v, 'candidate', name => evidence[name]);
    for (const field of ['sha', 'runId', 'status', 'platform', 'archives', 'mode']) {
        const changed = structuredClone(evidence);
        changed[Object.keys(changed)[0]][field] = 'changed';
        assert.throws(() => assertCliEvidence(v, 'candidate', name => changed[name]), /matching CLI/);
    }
    assert.throws(() => assertCliEvidence(v, 'registry', name => evidence[name]));
    assertCliEvidence({ packages: [] }, 'candidate', () => { throw Error('Must not read CLI evidence'); });
});
test('CLI entry waits for every platform and partial retries reuse exact receipts', async () => {
    const v = candidate(), registry = new Map(), uploads = [];
    let now = 0, fail = true;
    const options = {
        lookup: async p => registry.get(p.name) ?? null,
        checkChannel: async () => {},
        now: () => now,
        sleep: async ms => { now += ms; },
        upload: async p => {
            uploads.push(p.name);
            if (fail && p === v.packages[1]) throw Error('network');
            registry.set(p.name, { dist: { integrity: p.integrity } });
        },
    };
    await assert.rejects(publishNpmPackages(v.packages, options), /visibility timeout/);
    assert.equal(uploads.includes('@ibltools/cli'), false);
    fail = false;
    await publishNpmPackages(v.packages, options);
    assert.equal(uploads.filter(n => n === v.packages[0].name).length, 1);
    assert.equal(uploads.at(-1), '@ibltools/cli');
    registry.set(v.packages[0].name, { dist: { integrity: 'conflict' } });
    await assert.rejects(publishNpmPackages(v.packages, options), /differs/);
});
