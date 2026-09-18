import { resolve } from 'node:path';
import { catalog, root } from './core.mjs';
import { output, run } from './io.mjs';
import { packCli } from './cli-package.mjs';
import { cliConsumer } from './cli-consumer.mjs';
import { selectTarget } from '../../packages/cli/launcher.mjs';

const target = selectTarget();
const packages = catalog().filter(p => p.kind === 'cli' || (p.kind === 'cli-platform' && p.platform === target.platform));
const binary = resolve(root, 'target/release', target.executable);
for (const pkg of packages) packCli(pkg, output, pkg.kind === 'cli-platform' ? binary : undefined);
await cliConsumer({ packages, sha: run('git', ['rev-parse', 'HEAD']), runId: 'local' }, 'candidate');
