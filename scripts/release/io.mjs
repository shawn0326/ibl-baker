import { spawnSync } from 'node:child_process';
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { basename, dirname, join, resolve } from 'node:path';
import { root, hash, rustToolchain } from './core.mjs';

const require = createRequire(import.meta.url);
export const output = resolve(root, 'target/release');
export function writeJson(path, value) { writeFileSync(path, JSON.stringify(value, null, 2) + '\n'); }
export function run(command, args, options = {}) {
    mkdirSync(output, { recursive: true });
    console.log('> ' + command + ' ' + args.join(' '));
    const childOptions = { cwd: root, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, ...options };
    if (command === 'cargo') childOptions.env = { ...process.env, ...(options.env ?? {}), RUSTUP_TOOLCHAIN: rustToolchain };
    const result = spawnSync(command, args, childOptions);
    appendFileSync(join(output, 'commands.log'), '> ' + command + ' ' + args.join(' ') + '\n' + (result.stdout ?? '') + (result.stderr ?? '') + '\n');
    if (result.stderr) process.stderr.write(result.stderr);
    if (result.error) throw result.error;
    if (result.status !== 0) throw new Error(command + ' failed (' + result.status + '): ' + (result.stdout ?? '').slice(-4000));
    return (result.stdout ?? '').trim();
}
export function packageManifest(name) {
    const path = require.resolve(name + '/package.json');
    return JSON.parse(readFileSync(path, 'utf8'));
}
export function installedPackageVersion(name) {
    return packageManifest(name).version;
}
export function npmCli(args, options) {
    const manifestPath = require.resolve('npm/package.json');
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
    const entry = typeof manifest.bin === 'string' ? manifest.bin : manifest.bin?.npm;
    if (!entry) throw new Error('npm package does not expose an npm CLI entry.');
    const cliPath = resolve(dirname(manifestPath), entry);
    return run(process.execPath, [cliPath, ...args], { ...options, env: { ...process.env, ...(options?.env ?? {}), npm_execpath: cliPath } });
}
export function archivePath(file) {
    if (!file || basename(file) !== file) throw new Error('Invalid candidate artifact filename.');
    return join(output, file);
}
export function checkFiles(pkg) {
    if (hash(readFileSync(archivePath(pkg.archive))) !== pkg.sha256) throw new Error('Candidate archive checksum mismatch: ' + pkg.name);
}
export function clean() {
    if (run('git', ['status', '--porcelain']).length) throw new Error('Release checkout must be clean (including untracked files).');
}
export function cargoArchive(pkg, target) {
    const name = pkg.name + '-' + pkg.version + '.crate';
    const path = [join(target, 'package', 'tmp-crate', name), join(target, 'package', name)].find(existsSync);
    if (!path) throw new Error('Cargo archive missing: ' + name);
    return path;
}
export function listFiles(archive) {
    const files = run('tar', ['-tf', archive]).split(/\r?\n/u);
    if (files.some(file => file.startsWith('/') || file.includes('\\') || file.split('/').includes('..'))) throw new Error('Unsafe archive entry.');
    return files;
}

export function progress(event) {
    mkdirSync(output, { recursive: true });
    const record = { at: new Date().toISOString(), ...event };
    const label = event.name + "@" + event.version;
    const elapsed = (event.elapsedMs / 1000).toFixed(1) + "s";
    const line = label + ": " + event.phase + " (" + elapsed + ")" + (event.outcome ? " [" + event.outcome + "]" : "") + (event.message ? " " + event.message : "");
    console.log(line);
    appendFileSync(join(output, "commands.log"), line + "\n");
    appendFileSync(join(output, "progress.jsonl"), JSON.stringify(record) + "\n");
    if (process.env.GITHUB_STEP_SUMMARY && event.phase !== "registry-wait") {
        const safe = line.replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll("\n", " ");
        appendFileSync(process.env.GITHUB_STEP_SUMMARY, "- " + safe + "\n");
    }
}
