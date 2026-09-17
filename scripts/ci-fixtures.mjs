import { mkdirSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { root } from './release/core.mjs';
import { run } from './release/io.mjs';

// Generate disposable CI samples without refreshing fixtures/outputs.
const destination = resolve(root, 'target/ci-fixtures');
const binary = resolve(root, 'target/release/ibl-baker' + (process.platform === 'win32' ? '.exe' : ''));
mkdirSync(destination, { recursive: true });
for (const [input, name] of [
    ['Cannon_Exterior.hdr', 'cannon_exterior'], ['footprint_court.hdr', 'footprint_court'],
    ['helipad.hdr', 'helipad'], ['pisa.hdr', 'pisa'],
    ['spruit_sunrise_2k.jpg', 'spruit_sunrise_2k'], ['spruit_sunrise_2k.jpg', 'spruit_sunrise_2k_ktx2'],
]) {
    run(binary, ['bake', resolve(root, 'fixtures/inputs', input), '--out-dir', join(destination, name),
        '--size', '128', '--irradiance-size', '32', '--samples', '16', '--quality', 'low',
        '--target', 'specular', '--target', 'irradiance', '--output-format', 'both']);
}
