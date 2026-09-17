import { appendFileSync, existsSync, copyFileSync, cpSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join, resolve } from 'node:path';
import { parse } from 'smol-toml';
import { catalog, root, read, json, hash, repository, selectPackages, assertContext, validateSelection,
    assertNotes, assertResume, assertChannelAdvance, getJson, platforms, assertExistingRelease } from './core.mjs';
import { output, run, npm, writeJson, archivePath, checkFiles, clean, cargoArchive, listFiles, progress } from './io.mjs';
import { consumer } from './consumer.mjs';
import { waitForVersion, publishNpmPackages, publishCargoPackages, validateNpmCandidate } from './publication.mjs';

const command = process.argv[2];
const inputs = JSON.parse(process.env.RELEASE_INPUTS ?? '{}');
const packages = catalog();
const manifestPath = join(output, 'manifest.json');
const sha = () => run('git', ['rev-parse', 'HEAD']);
const dryRun = inputs.dry_run !== false;
const selected = () => selectPackages(packages, inputs);
const cargoTarget = resolve(root, 'target/release-build');

function staticCheck() {
    const lock = json('package-lock.json');
    const cargoLock = parse(read('Cargo.lock'));
    for (const pkg of packages) {
        if (pkg.registry === 'npm') {
            const manifest = json(pkg.directory + '/package.json');
            if (manifest.private || manifest.publishConfig?.access !== 'public'
                || (manifest.publishConfig.registry && manifest.publishConfig.registry !== 'https://registry.npmjs.org/')
                || manifest.repository?.url !== 'git+https://github.com/' + repository + '.git') throw new Error('Invalid publication metadata: ' + pkg.name);
            if (lock.packages[pkg.directory]?.version !== pkg.version
                || JSON.stringify(lock.packages[pkg.directory]?.dependencies ?? {}) !== JSON.stringify(manifest.dependencies ?? {})) {
                throw new Error('package-lock.json drift: ' + pkg.name);
            }
        } else if (!cargoLock.package.some(p => p.name === pkg.name && p.version === pkg.version && !p.source)) {
            throw new Error('Cargo.lock drift: ' + pkg.name);
        }
    }
    console.log('Static release preflight passed.');
}
function context() { assertContext(process.env, sha()); }
function manifest() {
    context();
    const value = JSON.parse(readFileSync(manifestPath, 'utf8'));
    assertResume(value, { sha: sha(), runId: process.env.GITHUB_RUN_ID, ids: selected().map(p => p.id), dryRun });
    if (!dryRun && (value.occupied.length || value.missingNotes.length)) throw new Error('Rehearsal-only candidate cannot be published.');
    for (const pkg of value.packages) {
        const expected = packages.find(p => p.id === pkg.id);
        for (const key of Object.keys(expected)) {
            if (JSON.stringify(pkg[key]) !== JSON.stringify(expected[key])) throw new Error('Candidate metadata changed: ' + key);
        }
        checkFiles(pkg);
        if (hash(readFileSync(archivePath(pkg.notesFile))) !== pkg.notesSha256) throw new Error('Release notes checksum mismatch.');
    }
    for (const binary of value.binaries) checkFiles(binary);
    if (selected().some(p => p.registry === 'cargo') && (value.binaries.length !== 3 || !platforms.every(p => value.binaries.some(b => b.platform === p)))) throw new Error('Missing binary platforms.');
    return value;
}
function summary(value) {
    const lines = ['## Release candidate', '', 'Commit: ' + value.sha, '', '| Package | Version | Channel | SHA-256 |',
        '| --- | --- | --- | --- |', ...value.packages.map(p => '| ' + p.name + ' | ' + p.version + ' | '
            + (p.registry === 'npm' ? p.channel : 'crates.io') + ' | ' + p.sha256 + ' |'),
        '', ...(value.occupied.length ? ['Occupied versions (NOT publishable): ' + value.occupied.join(', ')] : []),
        ...(value.missingNotes.length ? ['Missing release notes (NOT publishable): ' + value.missingNotes.join(', ')] : []),
        ...value.binaries.map(b => b.platform + ': ' + b.archive + ' SHA-256 ' + b.sha256),
        '', 'Review the release-candidate artifact, notes, file lists and consumer reports before approving release.',
        'Stable npm packages enter latest immediately when published.'];
    const text = lines.join('\n') + '\n';
    writeFileSync(join(output, 'summary.md'), text);
    if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, text);
}
async function restore() {
    context();
    const pages = JSON.parse(run('gh', ['api', 'repos/' + repository + '/actions/runs/' + process.env.GITHUB_RUN_ID + '/artifacts?per_page=100', '--paginate', '--slurp']));
    const artifact = pages.flatMap(page => page.artifacts).find(a => a.name === 'release-candidate');
    if (artifact?.expired) throw new Error('Original candidate expired. Do not reconstruct a partially published release.');
    if (!artifact && Number(process.env.GITHUB_RUN_ATTEMPT) > 1) throw new Error('Original candidate missing. Start a new run only after confirming no publication occurred.');
    if (artifact) {
        const restored = mkdtempSync(resolve(root, 'target/release-restore-'));
        run('gh', ['run', 'download', process.env.GITHUB_RUN_ID, '--repo', repository, '--name', 'release-candidate', '--dir', restored]);
        cpSync(restored, output, { recursive: true });
        const value = manifest();
        summary(value);
    }
    if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT, 'restored=' + Boolean(artifact) + '\n');
}
function cargoArgs(items, dryRun) {
    return ['publish', ...(dryRun ? ['--dry-run'] : []), '--locked', '--all-features', '--registry', 'crates-io',
        '--target-dir', cargoTarget, ...items.flatMap(p => ['-p', p.name])];
}
async function prepare() {
    context();
    clean();
    staticCheck();
    const items = selected();
    const occupied = await validateSelection(items, dryRun);
    if (!dryRun) for (const pkg of items.filter(p => p.registry === 'npm')) await checkChannel(pkg);
    const missingNotes = [];
    for (const pkg of items) {
        if (!existsSync(resolve(root, pkg.notes)) && dryRun) missingNotes.push(pkg.notes);
        else assertNotes(read(pkg.notes), pkg);
    }
    const value = { schema: 1, sha: sha(), runId: process.env.GITHUB_RUN_ID, dryRun, occupied, missingNotes, binaries: [], packages: items,
        toolchains: { node: process.version, npm: npm(['--version']), cargo: run('cargo', ['--version']) } };
    mkdirSync(output, { recursive: true });
    for (const pkg of items.filter(p => p.registry === 'npm')) {
        const packed = JSON.parse(npm(['pack', '--json', '--pack-destination', output], { cwd: resolve(root, pkg.directory) }))[0];
        pkg.archive = packed.filename;
        pkg.files = packed.files.map(f => f.path);
        const bytes = readFileSync(archivePath(pkg.archive));
        pkg.sha256 = hash(bytes);
        pkg.integrity = 'sha512-' + createHash('sha512').update(bytes).digest('base64');
        pkg.bytes = bytes.length;
        pkg.publishPreflight = await validateNpmCandidate(pkg, { dryRun, occupied,
            validate: p => npm(['publish', archivePath(p.archive), '--dry-run', '--ignore-scripts', '--access', 'public', '--tag', p.channel]) });
    }
    const crates = items.filter(p => p.registry === 'cargo');
    if (crates.length) {
        run('cargo', cargoArgs(crates, true));
        for (const pkg of crates) {
            pkg.archive = pkg.name + '-' + pkg.version + '.crate';
            copyFileSync(cargoArchive(pkg, cargoTarget), archivePath(pkg.archive));
            pkg.files = listFiles(archivePath(pkg.archive));
            const prefix = pkg.name + '-' + pkg.version + '/';
            for (const file of ['Cargo.toml', 'Cargo.lock', '.cargo_vcs_info.json', 'LICENSE', 'README.md', pkg.name === 'ibl_cli' ? 'src/main.rs' : 'src/lib.rs']) {
                if (!pkg.files.includes(prefix + file)) throw new Error('Missing crate file: ' + file);
            }
            const bytes = readFileSync(archivePath(pkg.archive));
            pkg.sha256 = hash(bytes);
            pkg.bytes = bytes.length;
        }
    }
    for (const pkg of items) {
        pkg.notesFile = pkg.id + '-notes.md';
        if (existsSync(resolve(root, pkg.notes))) copyFileSync(resolve(root, pkg.notes), archivePath(pkg.notesFile));
        else writeFileSync(archivePath(pkg.notesFile), '# Rehearsal only\n\nNo release notes were supplied. This candidate cannot be published.\n');
        pkg.notesSha256 = hash(readFileSync(archivePath(pkg.notesFile)));
    }
    if (crates.length) {
        for (const platform of platforms) {
            const directory = resolve(root, 'target/binaries');
            const binary = JSON.parse(readFileSync(join(directory, platform + '.json'), 'utf8'));
            if (binary.sha !== value.sha || binary.runId !== value.runId || binary.version !== crates[0].version || binary.platform !== platform || binary.status !== 'passed') throw new Error('Binary evidence mismatch: ' + platform);
            copyFileSync(join(directory, binary.archive), archivePath(binary.archive));
            checkFiles(binary);
            value.binaries.push(binary);
        }
    }
    await consumer(items, 'candidate');
    clean();
    writeJson(manifestPath, value);
    summary(value);
}
async function checkChannel(pkg) {
    const tags = await getJson("https://registry.npmjs.org/-/package/" + encodeURIComponent(pkg.name) + "/dist-tags", { allowMissing: true });
    assertChannelAdvance(pkg, tags);
}
async function publishNpm(ids) {
    const value = manifest();
    clean();
    await publishNpmPackages(value.packages.filter(p => ids.includes(p.id)), {
        checkChannel, emit: progress,
        upload: pkg => npm(["publish", archivePath(pkg.archive), "--ignore-scripts", "--access", "public", "--tag", pkg.channel, "--registry=https://registry.npmjs.org/"]),
    });
}
async function publishCargo() {
    const value = manifest();
    clean();
    const checkArchives = items => {
        for (const pkg of items) if (hash(readFileSync(cargoArchive(pkg, cargoTarget))) !== pkg.sha256) {
            throw new Error("Cargo archive differs from candidate: " + pkg.name);
        }
    };
    await publishCargoPackages(value.packages.filter(p => p.registry === "cargo"), {
        emit: progress,
        prepare: items => { run("cargo", cargoArgs(items, true)); checkArchives(items); },
        upload: items => run("cargo", cargoArgs(items, false)),
        checkArchives,
    });
}
async function verify() {
    const value = manifest();
    const receipts = [];
    for (const pkg of value.packages) {
        const metadata = await waitForVersion(pkg, { emit: progress });
        const url = pkg.registry === 'npm' ? metadata.dist.tarball
            : 'https://static.crates.io/crates/' + pkg.name + '/' + pkg.name + '-' + pkg.version + '.crate';
        const response = await fetch(url, { signal: AbortSignal.timeout(60000) });
        if (!response.ok || hash(Buffer.from(await response.arrayBuffer())) !== pkg.sha256) throw new Error('Downloaded registry artifact mismatch: ' + pkg.name);
        if (pkg.registry === 'npm') {
            const tags = await getJson('https://registry.npmjs.org/-/package/' + encodeURIComponent(pkg.name) + '/dist-tags');
            if (tags[pkg.channel] !== pkg.version) throw new Error('Unexpected npm ' + pkg.channel + ': ' + pkg.name + '. OIDC cannot repair dist-tags; inspect manually.');
            if (!metadata.dist.attestations) throw new Error('Missing npm provenance metadata: ' + pkg.name);
        }
        receipts.push({ name: pkg.name, version: pkg.version, sha256: pkg.sha256 });
    }
    await consumer(value.packages, 'registry');
    writeJson(join(output, 'verified.json'), { status: 'passed', sha: value.sha, runId: value.runId, receipts });
}
async function finalize() {
    const value = manifest();
    const verified = JSON.parse(readFileSync(join(output, 'verified.json'), 'utf8'));
    if (verified.status !== 'passed' || verified.sha !== value.sha || verified.runId !== value.runId
        || JSON.stringify(verified.receipts) !== JSON.stringify(value.packages.map(p => ({ name: p.name, version: p.version, sha256: p.sha256 })))) {
        throw new Error('Missing matching registry verification.');
    }
    const releases = JSON.parse(run('gh', ['api', 'repos/' + repository + '/releases?per_page=100', '--paginate', '--slurp'])).flat();
    const releaseGroups = [...new Set(value.packages.map(p => p.group))].map(id => {
        const items = value.packages.filter(p => p.group === id), pkg = items[0];
        return { ...pkg, assets: [...items, ...(id === 'rust_cli' ? value.binaries : [])] };
    });
    for (const group of releaseGroups) {
        const remote = run('git', ['ls-remote', '--tags', 'origin', 'refs/tags/' + group.tag, 'refs/tags/' + group.tag + '^{}']);
        const refs = remote.split('\n').filter(Boolean);
        const commit = (refs.find(line => line.endsWith('^{}')) ?? refs[0])?.split(/\s/u)[0];
        const existing = releases.find(r => r.tag_name === group.tag);
        const marker = 'Commit: ' + value.sha + '\nCandidate SHA-256: ' + hash(readFileSync(manifestPath));
        const published = existing && !existing.draft ? JSON.parse(run('gh', ['api', 'repos/' + repository + '/releases/' + existing.id])) : existing;
        if (assertExistingRelease(published, commit, group, value.sha, marker)) continue;
        if (!commit) {
            const refPath = join(output, group.id + '-tag.json');
            writeJson(refPath, { ref: 'refs/tags/' + group.tag, sha: value.sha });
            run('gh', ['api', 'repos/' + repository + '/git/refs', '--method', 'POST', '--input', refPath]);
        }
        const notesPath = join(output, group.id + '-github-notes.md');
        writeFileSync(notesPath, readFileSync(archivePath(group.notesFile), 'utf8') + '\n' + marker + '\n');
        if (!existing) run('gh', ['release', 'create', group.tag, '--repo', repository, '--target', value.sha, '--draft',
            '--title', group.notesTitle + ' ' + group.version, '--notes-file', notesPath, ...(group.channel === 'next' ? ['--prerelease'] : [])]);
        run('gh', ['release', 'upload', group.tag, '--repo', repository, '--clobber', ...group.assets.map(p => archivePath(p.archive)), manifestPath, join(output, 'verified.json')]);
        run('gh', ['release', 'edit', group.tag, '--repo', repository, '--draft=false', '--latest=' + (group.group === 'rust_cli' && group.channel === 'latest')]);
    }

}
try {
    if ((command?.startsWith('publish-') || command === 'finalize') && inputs.dry_run !== false) {
        throw new Error('Publishing is disabled unless dry_run is explicitly false.');
    }
    if (command === 'static') staticCheck();
    else if (command === 'restore') await restore();
    else if (command === 'prepare') await prepare();
    else if (command === 'validate') manifest();
    else if (command === 'publish-cargo') await publishCargo();
    else if (command === 'publish-npm') await publishNpm(['npm_ibla-loader', 'npm_ktx2-loader']);
    else if (command === 'verify') await verify();
    else if (command === 'finalize') await finalize();
    else throw new Error('Unknown release command: ' + command);
} catch (error) {
    console.error(error);
    process.exitCode = 1;
}
