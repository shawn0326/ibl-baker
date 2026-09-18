import { copyFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { catalog, root } from './core.mjs';
import { output, npm, run, cargoArchive, archivePath } from './io.mjs';
import { consumer } from './consumer.mjs';

const packages = catalog().filter(p => p.group !== 'npm_cli');
mkdirSync(output, { recursive: true });
for (const pkg of packages.filter(p => p.registry === 'npm')) {
    const result = JSON.parse(npm(['pack', '--json', '--pack-destination', output], { cwd: resolve(root, pkg.directory) }))[0];
    pkg.archive = result.filename;
}
const crates = packages.filter(p => p.registry === 'cargo');
const target = resolve(root, 'target/release-smoke-cargo');
// Local checks may inspect uncommitted edits; actual release preparation requires a clean checkout.
run('cargo', ['publish', '--dry-run', '--locked', '--all-features', '--allow-dirty', '--target-dir', target,
    ...crates.flatMap(p => ['-p', p.name])]);
for (const pkg of crates) {
    pkg.archive = pkg.name + '-' + pkg.version + '.crate';
    copyFileSync(cargoArchive(pkg, target), archivePath(pkg.archive));
}
await consumer(packages, 'candidate');
console.log('Release archive consumers passed; nothing was uploaded.');
