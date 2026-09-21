import { resolve } from 'node:path';
import { catalog, root } from './core.mjs';
import { npm, output, run } from './io.mjs';
import { packCli } from './cli-package.mjs';
import { cliConsumer } from './cli-consumer.mjs';
import { selectTarget } from '../../packages/cli/launcher.mjs';

const target = selectTarget();
const packages = catalog().filter(p => p.kind === 'loader' || p.kind === 'cli' || (p.kind === 'cli-platform' && p.platform === target.platform));
const binary = resolve(root, 'target/release', target.executable);
for (const pkg of packages) {
    if (pkg.kind === 'loader') {
        const packed = JSON.parse(npm(['pack', '--json', '--pack-destination', output], { cwd: resolve(root, pkg.directory) }))[0];
        pkg.archive = packed.filename;
    } else packCli(pkg, output, pkg.kind === 'cli-platform' ? binary : undefined);
}
await cliConsumer({ packages, sha: run('git', ['rev-parse', 'HEAD']), runId: 'local' }, 'candidate');
