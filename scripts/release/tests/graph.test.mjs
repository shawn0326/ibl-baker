import test from 'node:test';
import assert from 'node:assert/strict';
import { orderPackages, packageIdentity } from '../graph.mjs';

const pkg = (registry, name, dependencies = []) => ({ registry, name, version: '1.0.0', dependencies });
const dependency = (registry, name) => ({ registry, name, version: '1.0.0' });

test('orders dependencies before dependents with a stable order for independent nodes', () => {
    const packages = [
        pkg('npm', 'app', [dependency('npm', 'core')]),
        pkg('npm', 'zeta'),
        pkg('npm', 'core'),
        pkg('cargo', 'core'),
    ];
    assert.deepEqual(orderPackages(packages).map(packageIdentity), [
        'cargo:core@1.0.0', 'npm:core@1.0.0', 'npm:app@1.0.0', 'npm:zeta@1.0.0',
    ]);
});

test('orders synthetic CLI platform packages before the entry package', () => {
    const packages = [
        pkg('npm', '@ibltools/cli', [dependency('npm', '@ibltools/cli-win32-x64'), dependency('npm', '@ibltools/cli-linux-x64-gnu')]),
        pkg('npm', '@ibltools/cli-linux-x64-gnu'),
        pkg('npm', '@ibltools/cli-win32-x64'),
    ];
    assert.deepEqual(orderPackages(packages).map(p => p.name), [
        '@ibltools/cli-linux-x64-gnu', '@ibltools/cli-win32-x64', '@ibltools/cli',
    ]);
});

test('rejects missing, duplicate and cyclic release dependencies', () => {
    assert.throws(() => orderPackages([pkg('npm', 'app', [dependency('npm', 'missing')])]), /Missing release dependency/);
    assert.throws(() => orderPackages([pkg('npm', 'app'), pkg('npm', 'app')]), /Duplicate release package/);
    assert.throws(() => orderPackages([
        pkg('npm', 'a', [dependency('npm', 'b')]),
        pkg('npm', 'b', [dependency('npm', 'a')]),
    ]), /dependency cycle/);
});
