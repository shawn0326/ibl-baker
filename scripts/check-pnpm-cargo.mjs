import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const configPath = join(root, '.cargo', 'config.toml');
const cratesPath = join(root, '.pnpm', 'crates', 'crates-io');
const config = existsSync(configPath) ? readFileSync(configPath, 'utf8').replaceAll('\r\n', '\n') : '';

if (!config.includes('# >>> pnpm-managed cargo sources >>>')
    || !config.includes('[source.crates-io]\nreplace-with = "pnpm-crates-io"')
    || !config.includes('directory = ".pnpm/crates/crates-io"')
    || !config.includes('# <<< pnpm-managed cargo sources <<<')) {
    throw new Error('pnpm Cargo source configuration is missing or malformed. Run pnpm install first.');
}
if (!existsSync(cratesPath)) throw new Error('pnpm Cargo crate source is missing. Run pnpm install first.');

console.log('pnpm Cargo source is materialized and ready for offline Cargo commands.');
