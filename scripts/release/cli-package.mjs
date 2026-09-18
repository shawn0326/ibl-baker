import { chmodSync, copyFileSync, mkdirSync, readFileSync, mkdtempSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { root, hash, json } from './core.mjs';
import { npm, writeJson } from './io.mjs';
import { targets } from '../../packages/cli/launcher.mjs';

export { targets };

export function packCli(pkg, destination, binary) {
    mkdirSync(destination, { recursive: true });
    const staging = resolve(root, 'target/npm-cli-stage');
    mkdirSync(staging, { recursive: true });
    const stage = mkdtempSync(join(staging, pkg.slug + '-'));
    const source = json('packages/cli/package.json');
    const manifest = { name: pkg.name, version: pkg.version, description: source.description, license: source.license,
        repository: source.repository, engines: source.engines, publishConfig: { access: 'public' }, iblBinaryVersion: pkg.binaryVersion };
    copyFileSync(resolve(root, 'LICENSE'), join(stage, 'LICENSE'));
    copyFileSync(resolve(root, 'packages/cli/README.md'), join(stage, 'README.md'));
    mkdirSync(join(stage, 'bin'));
    if (pkg.kind === 'cli') {
        manifest.type = 'module';
        manifest.bin = { 'ibl-baker': './bin/ibl-baker.mjs' };
        manifest.files = ['bin/ibl-baker.mjs', 'launcher.mjs', 'LICENSE', 'README.md'];
        manifest.optionalDependencies = Object.fromEntries(pkg.dependencies.map(d => [d.name, d.version]));
        copyFileSync(resolve(root, 'packages/cli/bin/ibl-baker.mjs'), join(stage, 'bin/ibl-baker.mjs'));
        chmodSync(join(stage, 'bin/ibl-baker.mjs'), 0o755);
        copyFileSync(resolve(root, 'packages/cli/launcher.mjs'), join(stage, 'launcher.mjs'));
    } else {
        const target = targets.find(t => t.platform === pkg.platform);
        if (!binary || !target) throw new Error('Platform binary required: ' + pkg.name);
        manifest.os = [target.os]; manifest.cpu = [target.cpu];
        if (target.libc) manifest.libc = target.libc;
        manifest.files = ['bin/' + target.executable, 'LICENSE', 'README.md'];
        copyFileSync(binary, join(stage, 'bin', target.executable));
        chmodSync(join(stage, 'bin', target.executable), 0o755);
        pkg.binarySha256 = hash(readFileSync(binary));
    }
    writeJson(join(stage, 'package.json'), manifest);
    const packed = JSON.parse(npm(['pack', '--json', '--ignore-scripts', '--pack-destination', destination], { cwd: stage }))[0];
    const expected = [...manifest.files, 'package.json'].sort();
    if (JSON.stringify(packed.files.map(f => f.path).sort()) !== JSON.stringify(expected)) throw new Error('Unexpected CLI package contents: ' + pkg.name);
    const bytes = readFileSync(join(destination, packed.filename));
    Object.assign(pkg, { archive: packed.filename, files: expected, sha256: hash(bytes), bytes: bytes.length,
        integrity: 'sha512-' + createHash('sha512').update(bytes).digest('base64') });
    return pkg;
}
