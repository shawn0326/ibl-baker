import { mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { parse } from 'smol-toml';
import { root, json, catalog } from './core.mjs';
import { archivePath, listFiles, npm, run, writeJson, output } from './io.mjs';

export const fixturesRoot = () => resolve(root, process.env.IBL_FIXTURE_DIR || 'fixtures/outputs');
export function bakeSmoke(binary, destination, size = 16) {
    mkdirSync(destination, { recursive: true });
    run(binary, ['--help']);
    run(binary, ['bake', resolve(root, 'fixtures/inputs/pisa.hdr'), '--out-dir', destination,
        '--size', String(size), '--irradiance-size', '8', '--samples', '16', '--quality', 'low', '--output-format', 'both']);
    for (const kind of ['specular', 'irradiance']) {
        run(binary, ['validate', join(destination, kind + '.ibla')]);
        if (!readFileSync(join(destination, kind + '.ktx2')).length) throw new Error('Missing KTX2 output.');
    }
    if (!readFileSync(join(destination, 'brdf-lut.png')).subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) throw new Error('Invalid BRDF PNG.');
}
export async function consumer(packages, mode) {
    // Keep failed consumers for diagnosis; OS temp cleanup owns these directories.
    const dir = mkdtempSync(join(tmpdir(), 'ibl-release-consumer-'));
    const rust = packages.filter(p => p.registry === 'cargo');
    let baked;
    if (rust.length) {
        const rustDir = join(dir, 'rust');
        mkdirSync(rustDir);
        const target = resolve(root, 'target/release-consumers');
        const env = { ...process.env, CARGO_TARGET_DIR: target };
        if (mode === 'registry') {
            run('cargo', ['install', 'ibl_cli', '--version', '=' + rust.find(p => p.name === 'ibl_cli').version,
                '--locked', '--root', rustDir, '--registry', 'crates-io'], { cwd: rustDir, env });
            // Check the published libraries independently, without workspace path patches.
            writeFileSync(join(rustDir, 'Cargo.toml'), '[package]\nname="ibl-registry-consumer"\nversion="0.0.0"\nedition="2021"\n[dependencies]\n'
                + rust.filter(p => p.name !== 'ibl_cli').map(p => p.name + '="=' + p.version + '"').join('\n')
                + '\n[[bin]]\nname="check"\npath="check.rs"\n');
            writeFileSync(join(rustDir, 'check.rs'), 'fn main() { assert_eq!(ibl_core::FORMAT_VERSION, 1); let _ = ktx2_writer::WriterMetadata { writer: "consumer" }; }\n');
            run('cargo', ['run', '--bin', 'check'], { cwd: rustDir, env });
            const lock = parse(readFileSync(join(rustDir, 'Cargo.lock'), 'utf8'));
            for (const p of rust.filter(p => p.name !== 'ibl_cli')) {
                const resolved = lock.package.find(q => q.name === p.name && q.version === p.version);
                if (resolved?.source !== 'registry+https://github.com/rust-lang/crates.io-index' || resolved.checksum !== p.sha256) throw new Error('Registry consumer source mismatch: ' + p.name);
            }
        } else {
            for (const p of rust) {
                listFiles(archivePath(p.archive));
                run('tar', ['-xzf', archivePath(p.archive), '-C', rustDir]);
            }
            const cli = rust.find(p => p.name === 'ibl_cli');
            const cliDir = join(rustDir, cli.name + '-' + cli.version);
            const patch = '\n[patch.crates-io]\n' + rust.filter(p => p.name !== 'ibl_cli')
                .map(p => p.name + ' = { path = "../' + p.name + '-' + p.version + '" }').join('\n') + '\n';
            writeFileSync(join(cliDir, 'Cargo.toml'), readFileSync(join(cliDir, 'Cargo.toml'), 'utf8') + patch);
            run('cargo', ['build', '--release'], { cwd: cliDir, env });
        }
        const binary = mode === 'registry' ? join(rustDir, 'bin', 'ibl-baker' + (process.platform === 'win32' ? '.exe' : ''))
            : join(target, 'release', 'ibl-baker' + (process.platform === 'win32' ? '.exe' : ''));
        baked = join(dir, 'baked');
        bakeSmoke(binary, baked);
    }
    // Rust-only releases still verify their output with the currently published readers.
    const readers = rust.length ? catalog().filter(p => p.registry === 'npm') : packages.filter(p => p.registry === 'npm');
    if (readers.length) {
        writeJson(join(dir, 'package.json'), { private: true, type: 'module' });
        const tsVersion = json('package-lock.json').packages['node_modules/typescript'].version;
        npm(['install', '--ignore-scripts', '--no-audit', '--no-fund', '--registry=https://registry.npmjs.org',
            'typescript@' + tsVersion, ...readers.map(p => {
                const selected = packages.find(q => q.id === p.id);
                return mode !== 'registry' && selected ? archivePath(selected.archive) : p.name + '@' + p.version;
            })], { cwd: dir });
        const smoke = ['import { readFileSync } from "node:fs";', 'import assert from "node:assert/strict";'];
        const types = [];
        for (const p of readers) {
            const installed = join(dir, 'node_modules', ...p.name.split('/'));
            const m = JSON.parse(readFileSync(join(installed, 'package.json'), 'utf8'));
            if (m.version !== p.version) throw new Error('Consumer resolved wrong version: ' + p.name);
            for (const file of ['LICENSE', 'README.md', 'dist/index.js', 'dist/index.d.ts']) readFileSync(join(installed, file));
            const ibla = p.slug === 'ibla-loader', fn = ibla ? 'parseIBLA' : 'parseKTX2IBL';
            smoke.push('import { ' + fn + ' } from ' + JSON.stringify(p.name) + ';');
            types.push('import { ' + fn + ' } from ' + JSON.stringify(p.name) + ';', fn + '(new ArrayBuffer(0));');
            const folders = baked ? [baked] : readdirSync(fixturesRoot(), { withFileTypes: true }).filter(e => e.isDirectory()).map(e => join(fixturesRoot(), e.name));
            let count = 0;
            for (const folder of folders) for (const file of readdirSync(folder).filter(f => f.endsWith(ibla ? '.ibla' : '.ktx2'))) {
                const filePath = join(folder, file);
                smoke.push('{ const b = readFileSync(' + JSON.stringify(filePath) + '); const p = ' + fn + '(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength)); assert.equal('
                    + (ibla ? 'p.manifest.faceCount' : 'p.header.faceCount') + ', 6); }');
                count++;
            }
            if (!count) throw new Error('No consumer samples for ' + p.name);
        }
        writeFileSync(join(dir, 'smoke.mjs'), smoke.join('\n'));
        writeFileSync(join(dir, 'types.ts'), types.join('\n'));
        writeJson(join(dir, 'tsconfig.json'), { compilerOptions: { module: 'NodeNext', moduleResolution: 'NodeNext', target: 'ES2022', strict: true, noEmit: true, types: [] }, files: ['types.ts'] });
        run(process.execPath, [join(dir, 'node_modules/typescript/bin/tsc'), '-p', join(dir, 'tsconfig.json')], { cwd: dir });
        run(process.execPath, [join(dir, 'smoke.mjs')], { cwd: dir });
    }
    writeJson(join(output, 'consumer-' + mode + '.json'), { status: 'passed', packages: packages.map(p => p.name + '@' + p.version), directory: dir });
}
