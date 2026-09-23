import { publicationState, registryVersion } from './core.mjs';
import { orderPackages } from './graph.mjs';

const realSleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const quiet = () => {};
const identity = pkg => ({ name: pkg.name, version: pkg.version, registry: pkg.registry });

export async function waitForVersion(pkg, {
    lookup = registryVersion, now = Date.now, sleep = realSleep, emit = quiet,
} = {}) {
    const start = now();
    let lastLog = start;
    emit({ ...identity(pkg), phase: 'registry-wait', elapsedMs: 0 });
    try {
        while (true) {
            const metadata = await lookup(pkg);
            const elapsedMs = now() - start;
            if (publicationState(pkg, metadata) === 'published') {
                emit({ ...identity(pkg), phase: 'registry-confirmed', elapsedMs });
                return metadata;
            }
            if (elapsedMs >= 600000) throw new Error('Registry visibility timeout: ' + pkg.name + '. Inspect registry before retrying.');
            if (now() - lastLog >= 30000) {
                emit({ ...identity(pkg), phase: 'registry-wait', elapsedMs });
                lastLog = now();
            }
            await sleep(10000);
        }
    } catch (error) {
        emit({ ...identity(pkg), phase: 'registry-failed', elapsedMs: now() - start, message: error.message });
        throw error;
    }
}

export async function publishNpmPackages(packages, {
    lookup = registryVersion, upload, checkChannel, now = Date.now, sleep = realSleep, emit = quiet,
}) {
    for (const pkg of orderPackages(packages)) {
        if (publicationState(pkg, await lookup(pkg)) === 'pending') {
            await checkChannel(pkg);
            const start = now();
            emit({ ...identity(pkg), phase: 'upload-started', elapsedMs: 0 });
            try {
                await upload(pkg);
                emit({ ...identity(pkg), phase: 'upload-finished', elapsedMs: now() - start, outcome: 'success' });
            } catch (error) {
                // An unsuccessful command may still have uploaded the exact candidate.
                emit({ ...identity(pkg), phase: 'upload-finished', elapsedMs: now() - start, outcome: 'uncertain', message: error.message });
            }
        } else {
            emit({ ...identity(pkg), phase: 'already-published', elapsedMs: 0 });
        }
        await waitForVersion(pkg, { lookup, now, sleep, emit });
    }
}

export async function publishCargoPackages(packages, {
    lookup = registryVersion, prepare, upload, checkArchives, now = Date.now, sleep = realSleep, emit = quiet,
}) {
    for (const pkg of orderPackages(packages)) {
        if (publicationState(pkg, await lookup(pkg)) === 'published') {
            emit({ ...identity(pkg), phase: 'already-published', elapsedMs: 0 });
            continue;
        }
        const preparedAt = now();
        await prepare(pkg);
        emit({ ...identity(pkg), phase: 'cargo-prepared', elapsedMs: now() - preparedAt });
        const startedAt = now();
        emit({ ...identity(pkg), phase: 'upload-started', elapsedMs: 0 });
        let outcome = 'success', message;
        try { await upload(pkg); }
        catch (error) { outcome = 'uncertain'; message = error.message; }
        emit({ ...identity(pkg), phase: 'upload-finished', elapsedMs: now() - startedAt, outcome, ...(message ? { message } : {}) });
        await checkArchives(pkg);
        await waitForVersion(pkg, { lookup, now, sleep, emit });
    }
}

// npm itself rejects occupied versions even with --dry-run. Rehearsals still pack
// and consume those archives; never hide errors from checks of a new version.
export async function validateNpmCandidate(pkg, { dryRun, occupied, validate }) {
    if (dryRun && occupied.includes(pkg.name + '@' + pkg.version)) return 'occupied-rehearsal';
    await validate(pkg);
    return 'checked';
}
