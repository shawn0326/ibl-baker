import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { installedPackageVersion, npmCli, npmWorkspace, packageManifest } from '../io.mjs';

test('release npm client is resolved from the installed package, independent of npm_execpath', () => {
    const { npm_execpath, ...env } = process.env;
    const cwd = mkdtempSync(join(tmpdir(), 'ibl release npm '));
    assert.equal(installedPackageVersion('npm'), '11.11.0');
    assert.equal(packageManifest('npm').version, '11.11.0');
    assert.equal(npmCli(['--version'], { cwd, env }), '11.11.0');
});

test('workspace npm helper preserves npm run arguments', () => {
    assert.equal(npmWorkspace(['env', '--workspace=@ibltools/ibla-loader']).includes('npm_lifecycle_event'), true);
});
