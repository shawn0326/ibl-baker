import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { parse } from 'smol-toml';
import { targets } from '../../packages/cli/launcher.mjs';

export const root = resolve(import.meta.dirname, '../..');
export const repository = 'shawn0326/ibl-baker';
export const groups = ['rust_cli', 'npm_ibla_loader', 'npm_ktx2_loader', 'npm_cli'];
export const platforms = ['windows-x64', 'macos-arm64', 'linux-x64'];
export const read = path => readFileSync(resolve(root, path), 'utf8').replaceAll('\r\n', '\n');
export const json = path => JSON.parse(read(path));
export const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const semver = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?$/u;

export function channel(version) {
    if (!semver.test(version)) throw new Error('Invalid release version: ' + version);
    return version.includes('-') ? 'next' : 'latest';
}
export function catalog(readAt = read) {
    const workspaceVersion = parse(readAt('Cargo.toml')).workspace.package.version;
    const existing = [
        ['rust_cli', 'cargo', 'ktx2_writer'], ['rust_cli', 'cargo', 'ibl_core'], ['rust_cli', 'cargo', 'ibl_cli'],
        ['npm_ibla_loader', 'npm', 'ibla-loader'], ['npm_ktx2_loader', 'npm', 'ktx2-loader'],
    ].map(([group, registry, slug]) => {
        const directory = (registry === 'npm' ? 'packages/' : 'crates/') + slug;
        const m = registry === 'npm' ? JSON.parse(readAt(directory + '/package.json')) : parse(readAt(directory + '/Cargo.toml'));
        const p = registry === 'npm' ? m : m.package;
        const version = registry === 'npm' ? p.version : p.version?.workspace === true ? workspaceVersion : p.version;
        if (registry === 'cargo' && version !== workspaceVersion) throw new Error('Rust group versions must match.');
        const dependencies = Object.entries(m.dependencies ?? {}).filter(([name]) => ['ktx2_writer', 'ibl_core'].includes(name))
            .map(([name, spec]) => ({ name, version: spec.version?.replace(/^=/u, '') }));
        for (const d of dependencies) if (d.version !== workspaceVersion) throw new Error('Internal Rust dependency must match workspace version: ' + d.name);
        return { kind: registry === 'cargo' ? 'cargo' : 'loader', id: registry + '_' + slug, group, registry, slug, directory, name: p.name, version, dependencies,
            tag: registry === 'cargo' ? 'v' + version : 'npm/' + slug + '/v' + version,
            channel: channel(version), notesTitle: registry === 'cargo' ? 'Rust/CLI' : p.name,
            notes: 'docs/releases/' + (registry === 'cargo' ? 'rust-cli' : 'npm-' + slug) + '-' + version + '.md' };
    });
    const source = JSON.parse(readAt('packages/cli/package.json'));
    const version = source.version;
    const common = { group: 'npm_cli', registry: 'npm', version, binaryVersion: workspaceVersion,
        directory: 'packages/cli', tag: 'npm/cli/v' + version, channel: channel(version),
        notesTitle: '@ibltools/cli', notes: 'docs/releases/npm-cli-' + version + '.md' };
    const binaries = targets.map(t => ({ ...common, kind: 'cli-platform', id: 'npm_cli-' + t.suffix,
        slug: 'cli-' + t.suffix, name: '@ibltools/cli-' + t.suffix, platform: t.platform, dependencies: [] }));
    return [...existing, ...binaries, { ...common, kind: 'cli', id: 'npm_cli', slug: 'cli', name: '@ibltools/cli',
        dependencies: binaries.map(p => ({ name: p.name, version })) }];
}
export function selectPackages(packages, inputs) {
    for (const [key, value] of Object.entries(inputs)) {
        if (![...groups, 'dry_run'].includes(key) || typeof value !== 'boolean') throw new Error('Invalid release input: ' + key);
    }
    const selected = packages.filter(p => inputs[p.group] === true);
    if (!selected.length) throw new Error('Select at least one release group.');
    return selected;
}
export function assertContext(env, sha) {
    if (env.GITHUB_REPOSITORY !== repository || env.GITHUB_REF !== 'refs/heads/master'
        || env.GITHUB_EVENT_NAME !== 'workflow_dispatch'
        || env.GITHUB_WORKFLOW_REF !== repository + '/.github/workflows/publish.yml@refs/heads/master'
        || !/^[a-f0-9]{40}$/u.test(sha) || env.GITHUB_SHA !== sha || !/^\d+$/u.test(env.GITHUB_RUN_ID ?? '')) {
        throw new Error('Publishing requires publish.yml dispatched on shawn0326/ibl-baker master at the original SHA.');
    }
}
export async function getJson(url, { allowMissing = false, fetcher = fetch } = {}) {
    const response = await fetcher(url, { headers: { 'User-Agent': 'ibl-baker-release (github.com/shawn0326/ibl-baker)' }, signal: AbortSignal.timeout(30000) });
    if (response.status === 404 && allowMissing) return null;
    if (!response.ok) throw new Error('Registry request failed: HTTP ' + response.status + ' ' + url);
    return response.json();
}
export async function registryVersion(pkg) {
    if (pkg.registry === 'npm') return getJson('https://registry.npmjs.org/' + encodeURIComponent(pkg.name) + '/' + encodeURIComponent(pkg.version), { allowMissing: true });
    return (await getJson('https://crates.io/api/v1/crates/' + pkg.name + '/' + pkg.version, { allowMissing: true }))?.version ?? null;
}
export async function validateSelection(selected, dryRun, lookup = registryVersion) {
    const occupied = [];
    for (const pkg of selected) {
        if (await lookup(pkg)) {
            if (!dryRun) throw new Error(pkg.name + '@' + pkg.version + ' is already published; prepare a new version.');
            occupied.push(pkg.name + '@' + pkg.version);
        }
        for (const dep of pkg.dependencies) {
            if (!selected.some(p => p.registry === pkg.registry && p.name === dep.name && p.version === dep.version)) throw new Error('Missing selected dependency: ' + dep.name);
        }
    }
    return occupied;
}
export function assertNotes(text, pkg) {
    if (!text.startsWith('# ' + pkg.notesTitle + ' ' + pkg.version + '\n') || !/^Date: \d{4}-\d{2}-\d{2}$/mu.test(text)) throw new Error('Invalid release notes: ' + pkg.notes);
}
export function assertResume(manifest, expected) {
    if (manifest.schema !== 1 || manifest.sha !== expected.sha || manifest.runId !== expected.runId || manifest.dryRun !== expected.dryRun
        || JSON.stringify(manifest.packages.map(p => p.id)) !== JSON.stringify(expected.ids)) throw new Error('Candidate does not belong to this SHA, workflow run, mode and selection.');
}
export function publicationState(pkg, metadata) {
    if (!metadata) return 'pending';
    if (metadata.yanked) throw new Error(pkg.name + ' is yanked; refusing resume.');
    const checksum = pkg.registry === 'npm' ? metadata.dist?.integrity : metadata.checksum;
    const expected = pkg.registry === 'npm' ? pkg.integrity : pkg.sha256;
    if (!expected || checksum !== expected) throw new Error(pkg.name + ' registry artifact differs from the approved candidate.');
    return 'published';
}
export function compareVersions(a, b) {
    channel(a); channel(b);
    const parts = v => { const i = v.indexOf('-'); return [v.slice(0, i < 0 ? undefined : i).split('.'), i < 0 ? null : v.slice(i + 1).split('.')]; };
    const [am, ap] = parts(a), [bm, bp] = parts(b);
    for (let i = 0; i < 3; i++) if (BigInt(am[i]) !== BigInt(bm[i])) return BigInt(am[i]) < BigInt(bm[i]) ? -1 : 1;
    if (!ap || !bp) return ap === bp ? 0 : ap ? -1 : 1;
    for (let i = 0; i < Math.max(ap.length, bp.length); i++) {
        if (ap[i] === undefined || bp[i] === undefined) return ap[i] === undefined ? -1 : 1;
        if (ap[i] === bp[i]) continue;
        const an = /^\d+$/u.test(ap[i]), bn = /^\d+$/u.test(bp[i]);
        if (an && bn) return BigInt(ap[i]) < BigInt(bp[i]) ? -1 : 1;
        if (an !== bn) return an ? -1 : 1;
        return ap[i] < bp[i] ? -1 : 1;
    }
    return 0;
}
export function assertChannelAdvance(pkg, tags) {
    const current = tags?.[pkg.channel];
    if (current && compareVersions(pkg.version, current) < 0) throw new Error('Refusing to move npm ' + pkg.channel + ' backwards: ' + pkg.name);
}
export function assertExistingRelease(existing, commit, group, sha, marker) {
    if (commit && commit !== sha) throw new Error('Existing tag points at another commit: ' + group.tag);
    if (!existing) return false;
    if (!existing.body?.includes(marker)) throw new Error('Existing release belongs to a different candidate: ' + group.tag);
    if (existing.draft) return false;
    if (!group.assets.every(p => existing.assets.some(a => a.name === p.archive && a.digest === 'sha256:' + p.sha256))) throw new Error('Existing release assets differ from candidate.');
    return true;
}
