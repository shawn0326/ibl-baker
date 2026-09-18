import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync, spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, copyFileSync, mkdirSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { once } from 'node:events';
import { selectTarget } from '../launcher.mjs';

const moduleUrl = new URL('../launcher.mjs', import.meta.url).href;
const node = (code, options = {}) => spawnSync(process.execPath, ['--input-type=module', '-e', code], { encoding: 'utf8', ...options });
const launchCode = args => 'import {launch} from ' + JSON.stringify(moduleUrl) + ';launch(process.execPath,' + JSON.stringify(args) + ');';

test('selects supported targets and rejects unsupported architectures and musl', () => {
    assert.equal(selectTarget('win32', 'x64', true).suffix, 'win32-x64');
    assert.equal(selectTarget('darwin', 'arm64', true).suffix, 'darwin-arm64');
    assert.equal(selectTarget('linux', 'x64', '2.39').suffix, 'linux-x64-gnu');
    for (const args of [['linux', 'x64', false], ['linux', 'arm64', true], ['darwin', 'x64', true], ['win32', 'arm64', true]]) {
        assert.throws(() => selectTarget(...args), /Unsupported platform/);
    }
});
test('forwards arguments, working directory, environment, stdin and streams without shell interpretation', () => {
    const cwd = mkdtempSync(join(tmpdir(), 'ibl launcher 中文 '));
    const code = 'process.stdout.write(JSON.stringify({args:process.argv.slice(1),cwd:process.cwd(),env:process.env.IBL_TEST}));process.stderr.write("stderr");process.stdin.pipe(process.stdout)';
    const args = ['-e', code, '--', 'a b', '中文', '$HOME', '; echo unexpected'];
    const result = node(launchCode(args), { cwd, env: { ...process.env, IBL_TEST: 'inherited' }, input: 'stdin' });
    assert.equal(result.status, 0);
    assert.equal(result.stderr, 'stderr');
    assert.equal(result.stdout, JSON.stringify({ args: args.slice(3), cwd: realpathSync(cwd), env: 'inherited' }) + 'stdin');
});
test('preserves child exit codes and reports startup failure', () => {
    assert.equal(node(launchCode(['-e', 'process.exit(37)'])).status, 37);
    const result = node('import {launch} from ' + JSON.stringify(moduleUrl) + ';launch("missing-ibl-executable",[]);');
    assert.equal(result.status, 1);
    assert.match(result.stderr, /Cannot start binary/);
});
test('reports missing, mismatched and incomplete platform packages', () => {
    const dir = mkdtempSync(join(tmpdir(), 'ibl launcher resolver '));
    copyFileSync(new URL('../launcher.mjs', import.meta.url), join(dir, 'launcher.mjs'));
    writeFileSync(join(dir, 'package.json'), JSON.stringify({ type: 'module', version: '0.1.0', iblBinaryVersion: '0.2.2' }));
    const code = 'import {resolveBinary} from ' + JSON.stringify(pathToFileURL(join(dir, 'launcher.mjs')).href) + ';try{resolveBinary()}catch(e){console.error(e.message);process.exitCode=1}';
    assert.match(node(code).stderr, /Missing platform package/);
    const target = selectTarget();
    const p = join(dir, 'node_modules/@ibltools/cli-' + target.suffix);
    mkdirSync(p, { recursive: true });
    writeFileSync(join(p, 'package.json'), JSON.stringify({ version: '0.0.0' }));
    assert.match(node(code).stderr, /version mismatch/);
    writeFileSync(join(p, 'package.json'), JSON.stringify({ version: '0.1.0', iblBinaryVersion: '0.2.2' }));
    assert.match(node(code).stderr, /Missing or non-executable/);
});
for (const signal of ['SIGINT', 'SIGTERM']) test('forwards ' + signal + ' and leaves no child running', { skip: process.platform === 'win32', timeout: 15000 }, async () => {
    const childCode = 'console.log(process.pid);setInterval(()=>{},1000)';
    const parent = spawn(process.execPath, ['--input-type=module', '-e', launchCode(['-e', childCode])], { stdio: ['ignore', 'pipe', 'pipe'] });
    try {
        const [data] = await once(parent.stdout, 'data');
        const pid = Number(String(data).trim());
        const exited = once(parent, 'exit');
        parent.kill(signal);
        const [code, received] = await exited;
        assert.equal(code, null);
        assert.equal(received, signal);
        assert.throws(() => process.kill(pid, 0), /ESRCH/);
    } finally { if (parent.exitCode === null && parent.signalCode === null) parent.kill('SIGKILL'); }
});

test('Windows console Ctrl+C stops both launcher and child', { skip: process.platform !== 'win32', timeout: 40000 }, () => {
    const dir = mkdtempSync(join(tmpdir(), 'ibl ctrl-c '));
    const ready = join(dir, 'ready.json'), script = join(dir, 'launcher.mjs');
    const child = 'require("node:fs").writeFileSync(process.env.IBL_TEST_READY,JSON.stringify({pid:process.pid}));setInterval(()=>{},1000)';
    writeFileSync(script, launchCode(['-e', child]));
    const result = spawnSync('pwsh', ['-NoProfile', '-File', fileURLToPath(new URL('./windows-ctrl-c.ps1', import.meta.url))], {
        encoding: 'utf8', timeout: 35000, env: { ...process.env, IBL_TEST_NODE: process.execPath, IBL_TEST_SCRIPT: script, IBL_TEST_READY: ready },
    });
    assert.equal(result.status, 0, result.stderr || result.error?.message);
});
