import { copyFileSync, mkdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { catalog, root, hash, platforms } from './core.mjs';
import { run, npm, writeJson } from './io.mjs';
import { bakeSmoke } from './consumer.mjs';
import { packCli, targets } from './cli-package.mjs';

const [platform, target] = process.argv.slice(2);
if (!platforms.includes(platform) || target !== targets.find(t => t.platform === platform)?.target) throw new Error('Expected platform and target.');
const directory = resolve(root, 'target/binaries');
const stage = resolve(root, 'target/binary-stage', platform);
mkdirSync(directory, { recursive: true });
mkdirSync(stage, { recursive: true });
const version = catalog()[0].version;
run('cargo', ['build', '--release', '--locked', '-p', 'ibl_cli', '--target', target]);
const name = 'ibl-baker' + (platform === 'windows-x64' ? '.exe' : '');
const binary = resolve(root, 'target', target, 'release', name);
const samples = resolve(root, 'target/binary-smoke', platform);
bakeSmoke(binary, samples);
for (const [slug, fn, ext] of [['ibla-loader', 'parseIBLA', 'ibla'], ['ktx2-loader', 'parseKTX2IBL', 'ktx2']]) {
    npm(['run', 'build', '-w', '@ibltools/' + slug]);
    const parser = (await import(pathToFileURL(resolve(root, 'packages', slug, 'dist/index.js')).href))[fn];
    for (const kind of ['specular', 'irradiance']) parser(readFileSync(join(samples, kind + '.' + ext)));
}
copyFileSync(binary, join(stage, name));
const archive = 'ibl-baker-v' + version + '-' + platform + (platform === 'windows-x64' ? '.zip' : '.tar.gz');
if (platform === 'windows-x64') {
    run('pwsh', ['-NoProfile', '-Command', 'Compress-Archive -LiteralPath $env:IBL_BINARY_FILE -DestinationPath $env:IBL_ARCHIVE_FILE -Force'],
        { env: { ...process.env, IBL_BINARY_FILE: join(stage, name), IBL_ARCHIVE_FILE: join(directory, archive) } });
} else run('tar', ['-czf', join(directory, archive), '-C', stage, name]);
writeJson(join(directory, platform + '.json'), { name: platform, platform, version, archive,
    sha256: hash(readFileSync(join(directory, archive))), binarySha256: hash(readFileSync(binary)), status: 'passed',
    sha: run('git', ['rev-parse', 'HEAD']), runId: process.env.GITHUB_RUN_ID,
    toolchains: { node: process.version, cargo: run('cargo', ['--version']), target } });

if (JSON.parse(process.env.RELEASE_INPUTS ?? '{}').npm_cli === true) {
    const pkg = catalog().find(p => p.kind === 'cli-platform' && p.platform === platform);
    packCli(pkg, directory, binary);
    writeJson(join(directory, 'npm-' + platform + '.json'), pkg);
}
if (platform === 'linux-x64') {
    writeJson(join(directory, 'linux-runtime.json'), { ldd: run('ldd', [binary]), symbols: run('objdump', ['-T', binary]) });
}
