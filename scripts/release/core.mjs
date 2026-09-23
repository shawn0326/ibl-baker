import { readFileSync, readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { dirname, relative, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { parse } from 'smol-toml';
import { targets } from '../../packages/cli/launcher.mjs';
import { orderPackages } from './graph.mjs';

export const root = resolve(import.meta.dirname, '../..');
export const repository = 'shawn0326/ibl-baker';
export const groups = ['rust_cli', 'npm_ibla_loader', 'npm_ktx2_loader', 'npm_cli'];
export const platforms = ['windows-x64', 'macos-arm64', 'linux-x64'];
export const read = path => readFileSync(resolve(root, path), 'utf8').replaceAll('\r\n', '\n');
export const json = path => JSON.parse(read(path));
export const hash = bytes => createHash('sha256').update(bytes).digest('hex');
export const rustToolchain = parse(read('rust-toolchain.toml')).toolchain.channel;
const semver = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?$/u;
let cachedCargoMetadata;

function normalizePath(path) {
    const normalized = resolve(path).replaceAll('\\', '/');
    return process.platform === 'win32' ? normalized.toLowerCase() : normalized;
}

function cargoPackageIsPublishable(packageMetadata) {
    return packageMetadata.publish == null || packageMetadata.publish.includes('crates-io');
}

function internalDependencyVersion(specifier) {
    const value = specifier.startsWith('workspace:') ? specifier.slice('workspace:'.length) : specifier;
    if (value === '*' || value === '^' || value === '~') return null;
    return value.replace(/^[=^~]/u, '');
}

export function readCargoMetadata() {
    if (cachedCargoMetadata) return cachedCargoMetadata;
    const result = spawnSync('cargo', ['metadata', '--no-deps', '--format-version', '1', '--locked', '--manifest-path', resolve(root, 'Cargo.toml')], {
        cwd: root, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024,
        env: { ...process.env, RUSTUP_TOOLCHAIN: rustToolchain },
    });
    if (result.error) throw result.error;
    if (result.status !== 0) throw new Error('cargo metadata failed (' + result.status + '): ' + (result.stderr ?? '').trim());
    try { cachedCargoMetadata = JSON.parse(result.stdout); }
    catch (error) { throw new Error('cargo metadata returned invalid JSON: ' + error.message); }
    return cachedCargoMetadata;
}

export function channel(version) {
    if (!semver.test(version)) throw new Error('Invalid release version: ' + version);
    return version.includes('-') ? 'next' : 'latest';
}
export function catalog(readAt = read, cargo = readCargoMetadata()) {
    const workspaceVersion = parse(readAt('Cargo.toml')).workspace.package.version;
    const workspaceCargoMembers = new Map(cargo.packages
        .filter(p => cargo.workspace_members.includes(p.id))
        .map(p => [normalizePath(p.manifest_path), p]));
    const cargoMembers = new Map([...workspaceCargoMembers].filter(([, p]) => cargoPackageIsPublishable(p)));
    const cargoDescriptors = new Map();
    for (const [manifestPath, metadata] of cargoMembers) {
        const relativeManifest = relative(root, metadata.manifest_path).replaceAll('\\', '/');
        const directory = dirname(relativeManifest).replaceAll('\\', '/');
        const m = parse(readAt(relativeManifest));
        const p = m.package;
        const version = p.version?.workspace === true ? workspaceVersion : p.version;
        if (metadata.version !== version) throw new Error('Cargo metadata drift: ' + metadata.name);
        if (version !== workspaceVersion) throw new Error('Rust group versions must match.');
        cargoDescriptors.set(manifestPath, { kind: 'cargo', id: 'cargo_' + metadata.name, group: 'rust_cli', registry: 'cargo', slug: metadata.name,
            directory, name: metadata.name, version, dependencies: [],
            tag: 'v' + version, channel: channel(version), notesTitle: 'Rust/CLI', notes: 'docs/releases/rust-cli-' + version + '.md' });
    }
    for (const [manifestPath, metadata] of cargoMembers) {
        const descriptor = cargoDescriptors.get(manifestPath);
        for (const dependency of metadata.dependencies.filter(d => d.path)) {
            const dependencyManifest = normalizePath(resolve(dependency.path, 'Cargo.toml'));
            const target = cargoDescriptors.get(dependencyManifest);
            const workspaceTarget = workspaceCargoMembers.get(dependencyManifest);
            if (!target) {
                if (workspaceTarget) throw new Error('Published Rust package depends on a non-publishable workspace package: ' + dependency.name);
                continue;
            }
            const normalizedVersion = internalDependencyVersion(dependency.req);
            if (normalizedVersion !== target.version) {
                throw new Error('Internal Rust dependency must match workspace version: ' + dependency.name);
            }
            descriptor.dependencies.push({ registry: 'cargo', name: target.name, version: target.version });
        }
    }
    const npmGroups = new Map([
        ['@ibltools/ibla-loader', 'npm_ibla_loader'],
        ['@ibltools/ktx2-loader', 'npm_ktx2_loader'],
    ]);
    const npmWorkspace = new Map();
    const npmDescriptors = new Map();
    for (const entry of readdirSync(resolve(root, 'packages'), { withFileTypes: true })) {
        if (!entry.isDirectory()) continue;
        const directory = 'packages/' + entry.name;
        const manifestPath = resolve(root, directory, 'package.json');
        let m;
        try { m = JSON.parse(readFileSync(manifestPath, 'utf8')); }
        catch { continue; }
        npmWorkspace.set(m.name, { directory, manifest: m, private: m.private === true });
        if (m.private === true) continue;
        const group = npmGroups.get(m.name);
        if (!group) throw new Error('Public npm package is not assigned to a release group: ' + m.name);
        npmDescriptors.set(m.name, { kind: 'loader', id: 'npm_' + entry.name, group, registry: 'npm', slug: entry.name,
            directory, name: m.name, version: m.version, dependencies: [],
            tag: 'npm/' + entry.name + '/v' + m.version, channel: channel(m.version), notesTitle: m.name,
            notes: 'docs/releases/npm-' + entry.name + '-' + m.version + '.md' });
    }
    for (const entry of npmDescriptors.values()) {
        const manifest = npmWorkspace.get(entry.name).manifest;
        for (const [name, spec] of Object.entries({ ...manifest.dependencies, ...manifest.optionalDependencies, ...manifest.peerDependencies })) {
            const target = npmDescriptors.get(name);
            const workspaceTarget = npmWorkspace.get(name);
            if (!workspaceTarget) continue;
            if (!target) throw new Error('Published npm package depends on a private workspace package: ' + name);
            const normalizedVersion = typeof spec === 'string' ? internalDependencyVersion(spec) : null;
            if (normalizedVersion && normalizedVersion !== target.version) {
                throw new Error('Internal npm dependency must match workspace version: ' + name);
            }
            entry.dependencies.push({ registry: 'npm', name: target.name, version: target.version });
        }
    }
    const existing = [...cargoDescriptors.values(), ...npmDescriptors.values()];
    const source = JSON.parse(readAt('packages/cli/package.json'));
    const version = source.version;
    const common = { group: 'npm_cli', registry: 'npm', version, binaryVersion: workspaceVersion,
        directory: 'packages/cli', tag: 'npm/cli/v' + version, channel: channel(version),
        notesTitle: '@ibltools/cli', notes: 'docs/releases/npm-cli-' + version + '.md' };
    const binaries = targets.map(t => ({ ...common, kind: 'cli-platform', id: 'npm_cli-' + t.suffix,
        slug: 'cli-' + t.suffix, name: '@ibltools/cli-' + t.suffix, platform: t.platform, dependencies: [] }));
    return orderPackages([...existing, ...binaries, { ...common, kind: 'cli', id: 'npm_cli', slug: 'cli', name: '@ibltools/cli',
        dependencies: binaries.map(p => ({ registry: 'npm', name: p.name, version })).sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0) }]);
}
export function selectPackages(packages, inputs) {
    for (const [key, value] of Object.entries(inputs)) {
        if (![...groups, 'dry_run'].includes(key) || typeof value !== 'boolean') throw new Error('Invalid release input: ' + key);
    }
    const selected = packages.filter(p => inputs[p.group] === true);
    if (!selected.length) throw new Error('Select at least one release group.');
    if ((inputs.rust_cli === true || inputs.npm_cli === true) && inputs.npm_ktx2_loader !== true) {
        throw new Error('Rust/CLI releases require npm_ktx2_loader for the KTX2 format contract.');
    }
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
            if (!selected.some(p => p.registry === dep.registry && p.name === dep.name && p.version === dep.version)) throw new Error('Missing selected dependency: ' + dep.registry + ':' + dep.name);
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
