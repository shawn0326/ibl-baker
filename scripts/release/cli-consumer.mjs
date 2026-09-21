import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, accessSync, constants } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { catalog, root, hash, platforms } from './core.mjs';
import { output, npm, run, writeJson, archivePath, checkFiles } from './io.mjs';
import { selectTarget } from '../../packages/cli/launcher.mjs';

export function assertCliEvidence(value, mode, readEvidence = name => JSON.parse(readFileSync(join(output, name), 'utf8'))) {
    const packages = value.packages.filter(p => p.group === 'npm_cli');
    if (!packages.length) return;
    const archives = packages.map(p => ({ name: p.name, sha256: p.sha256 }));
    const reports = [];
    for (const platform of platforms) {
        const evidence = readEvidence('cli-' + mode + '-' + platform + '.json');
        if (!evidence || evidence.status !== 'passed' || evidence.mode !== mode || evidence.platform !== platform
            || evidence.sha !== value.sha || evidence.runId !== value.runId
            || JSON.stringify(evidence.archives) !== JSON.stringify(archives)) throw new Error('Missing matching CLI ' + mode + ' evidence: ' + platform);
        reports.push(evidence);
    }
    return reports;
}

export async function cliConsumer(value, mode) {
    const entry = value.packages.find(p => p.kind === 'cli');
    if (!entry) throw new Error('npm_cli must be selected.');
    const target = selectTarget();
    const platform = value.packages.find(p => p.kind === 'cli-platform' && p.platform === target.platform);
    if (!platform) throw new Error('Current platform archive missing.');
    for (const pkg of value.packages.filter(p => p.group === 'npm_cli')) checkFiles(pkg);
    const dir = mkdtempSync(join(tmpdir(), 'ibl-cli consumer-'));
    writeJson(join(dir, 'package.json'), { private: true, type: 'module' });
    const cache = join(dir, 'cache');
    const installFlags = ['--ignore-scripts', '--no-audit', '--no-fund', '--include=optional', '--cache', cache, '--registry=https://registry.npmjs.org'];
    const specs = mode === 'registry' ? [entry.name + '@' + entry.version] : [archivePath(platform.archive), archivePath(entry.archive)];
    npm(['install', ...installFlags, ...specs], { cwd: dir });
    const installed = join(dir, 'node_modules/@ibltools');
    const manifest = JSON.parse(readFileSync(join(installed, 'cli/package.json'), 'utf8'));
    assert.equal(manifest.version, entry.version);
    assert.equal(manifest.iblBinaryVersion, entry.binaryVersion);
    assert.deepEqual(manifest.optionalDependencies, Object.fromEntries(entry.dependencies.map(d => [d.name, d.version])));
    const native = join(installed, platform.slug, 'bin', target.executable);
    assert.equal(hash(readFileSync(native)), platform.binarySha256);
    if (process.platform !== 'win32') accessSync(native, constants.X_OK);
    for (const slug of ['cli', platform.slug]) {
        const m = JSON.parse(readFileSync(join(installed, slug, 'package.json'), 'utf8'));
        assert.equal(m.version, entry.version);
        assert.equal(m.scripts, undefined);
        for (const file of ['LICENSE', 'README.md']) readFileSync(join(installed, slug, file));
    }
    const launcher = join(installed, 'cli/bin/ibl-baker.mjs');
    const invoke = args => run(process.execPath, [launcher, ...args], { cwd: dir });
    const versionOutput = '@ibltools/cli ' + entry.version + '\nibl-baker ' + entry.binaryVersion;
    assert.equal(run(native, ['--version'], { cwd: dir }), 'ibl-baker ' + entry.binaryVersion);
    assert.equal(invoke(['--version']), versionOutput);
    assert.equal(invoke(['--version', 'extra']), versionOutput);
    assert.equal(invoke(['-V']), invoke(['--version']));
    assert.equal(invoke(['--help']), run(native, ['--help'], { cwd: dir }));
    for (const args of [['unknown-command'], ['validate', 'missing file 中文.ibla'], ['validate', '--version']]) {
        const options = { cwd: dir, encoding: 'utf8' };
        const wrapped = spawnSync(process.execPath, [launcher, ...args], options);
        const direct = spawnSync(native, args, options);
        assert.equal(wrapped.status, direct.status);
        assert.equal(wrapped.stdout, direct.stdout);
        assert.equal(wrapped.stderr, direct.stderr);
    }
    assert.equal(npm(['exec', '--offline', '--cache', cache, '--', 'ibl-baker', '--version'], { cwd: dir }), versionOutput);
    assert.equal(npm(['exec', '--offline', '--cache', cache, '--', '@ibltools/cli', '--version'], { cwd: dir }), versionOutput);
    if (mode === 'registry') {
        const fresh = join(dir, 'fresh-npx');
        mkdirSync(fresh);
        assert.equal(npm(['exec', '--yes', '--ignore-scripts', '--cache', join(fresh, 'cache'),
            '--', entry.name + '@' + entry.version, '--version'], { cwd: fresh }), versionOutput);
    }
    const globalPrefix = join(dir, 'global');
    npm(['install', '--global', '--prefix', globalPrefix, ...installFlags, ...specs], { cwd: dir });
    const globalShim = join(globalPrefix, ...(process.platform === 'win32' ? ['ibl-baker.cmd'] : ['bin', 'ibl-baker']));
    if (process.platform === 'win32') {
        assert.equal(run('pwsh', ['-NoProfile', '-Command', '& $env:IBL_CLI_SHIM --version; exit $LASTEXITCODE'],
            { cwd: dir, env: { ...process.env, IBL_CLI_SHIM: globalShim } }), versionOutput);
    } else assert.equal(run(globalShim, ['--version'], { cwd: dir }), versionOutput);
    const baked = join(dir, 'baked 中文');
    invoke(['bake', resolve(root, 'fixtures/inputs/pisa.hdr'), '--out-dir', baked, '--size', '16', '--irradiance-size', '8',
        '--samples', '16', '--quality', 'low', '--output-format', 'both']);
    for (const kind of ['specular', 'irradiance']) invoke(['validate', join(baked, kind + '.ibla')]);
    assert.ok(readFileSync(join(baked, 'brdf-lut.png')).subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10])));
    const readers = catalog().filter(p => p.kind === 'loader');
    npm(['install', ...installFlags, ...readers.map(p => {
        const selected = value.packages.find(q => q.id === p.id);
        return mode === 'candidate' && selected ? archivePath(selected.archive) : p.name + '@' + p.version;
    })], { cwd: dir });
    const checks = [];
    for (const [slug, fn, ext] of [['ibla-loader', 'parseIBLA', 'ibla'], ['ktx2-loader', 'parseKTX2IBL', 'ktx2']]) {
        for (const kind of ['specular', 'irradiance']) {
            const index = checks.length;
            const parsed = 'p' + index;
            checks.push(
                'const b' + index + ' = fs.readFileSync(' + JSON.stringify(join(baked, kind + '.' + ext)) + ');'
                + 'const ' + parsed + ' = ' + fn + '(b' + index + '.buffer.slice(b' + index + '.byteOffset, b' + index + '.byteOffset + b' + index + '.byteLength));'
                + (ext === 'ktx2' ? 'assert.equal(' + parsed + '.header.vkFormat, 143);' : ''));
        }
    }
    run(process.execPath, ['--input-type=module', '-e', 'import fs from "node:fs"; import assert from "node:assert/strict"; import {parseIBLA} from "@ibltools/ibla-loader"; import {parseKTX2IBL} from "@ibltools/ktx2-loader";' + checks.join('\n')], { cwd: dir });
    const evidence = { status: 'passed', mode, platform: target.platform, sha: value.sha, runId: value.runId,
        archives: value.packages.filter(p => p.group === 'npm_cli').map(p => ({ name: p.name, sha256: p.sha256 })), directory: dir };
    writeJson(join(output, 'cli-' + mode + '-' + target.platform + '.json'), evidence);
    return evidence;
}
