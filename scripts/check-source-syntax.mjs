import { readFileSync } from 'node:fs';
import { extname, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = resolve(import.meta.dirname, '..');
const tracked = spawnSync('git', ['ls-files', '-z', '--', '*.cjs', '*.js', '*.json', '*.mjs'], {
    cwd: root,
    encoding: 'utf8',
});

if (tracked.error) throw tracked.error;
if (tracked.status !== 0) {
    throw new Error(`git ls-files failed (${tracked.status}): ${tracked.stderr.trim()}`);
}

const files = tracked.stdout.split('\0').filter(Boolean).sort();
const failures = [];

for (const file of files) {
    if (extname(file) === '.json') {
        try {
            JSON.parse(readFileSync(resolve(root, file), 'utf8'));
        } catch (error) {
            failures.push(`${file}: ${error.message}`);
        }
        continue;
    }

    const result = spawnSync(process.execPath, ['--check', resolve(root, file)], {
        cwd: root,
        encoding: 'utf8',
    });
    if (result.error) throw result.error;
    if (result.status !== 0) {
        failures.push(`${file}:\n${(result.stderr || result.stdout).trim()}`);
    }
}

if (failures.length > 0) {
    throw new Error(`Source syntax checks failed:\n${failures.join('\n')}`);
}

console.log(`Validated ${files.length} tracked JavaScript and JSON files.`);
