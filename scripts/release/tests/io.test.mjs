import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { installedPackageVersion, npmCli, npmEnvironment } from '../io.mjs';

test('release npm client is resolved from the installed package, independent of npm_execpath', () => {
    const { npm_execpath, ...env } = process.env;
    const cwd = mkdtempSync(join(tmpdir(), 'ibl release npm '));
    assert.equal(installedPackageVersion('npm'), '11.11.0');
    assert.equal(npmCli(['--version'], { cwd, env }), '11.11.0');
});

test('release npm client does not inherit pnpm-only configuration', () => {
    const env = npmEnvironment('npm-cli.js', {
        NPM_CONFIG_MANAGE_PACKAGE_MANAGER_VERSIONS: 'false',
        npm_config_registry: 'https://registry.npmjs.org',
    });

    assert.equal(env.npm_execpath, 'npm-cli.js');
    assert.equal(env.NPM_CONFIG_MANAGE_PACKAGE_MANAGER_VERSIONS, undefined);
    assert.equal(env.npm_config_registry, 'https://registry.npmjs.org');
});
