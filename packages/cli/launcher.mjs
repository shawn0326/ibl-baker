import { spawn } from 'node:child_process';
import { readFileSync, accessSync, constants } from 'node:fs';
import { createRequire } from 'node:module';

export const targets = [
    { platform: 'windows-x64', os: 'win32', cpu: 'x64', suffix: 'win32-x64', target: 'x86_64-pc-windows-msvc', executable: 'ibl-baker.exe' },
    { platform: 'macos-arm64', os: 'darwin', cpu: 'arm64', suffix: 'darwin-arm64', target: 'aarch64-apple-darwin', executable: 'ibl-baker' },
    { platform: 'linux-x64', os: 'linux', cpu: 'x64', suffix: 'linux-x64-gnu', target: 'x86_64-unknown-linux-gnu', executable: 'ibl-baker', libc: ['glibc'] },
];

export function selectTarget(os = process.platform, cpu = process.arch, glibc = os !== 'linux' || process.report.getReport().header.glibcVersionRuntime) {
    const target = targets.find(t => t.os === os && t.cpu === cpu);
    if (!target || !glibc) throw new Error('Unsupported platform: ' + os + '/' + cpu + (os === 'linux' && !glibc ? ' (glibc required; musl is unsupported)' : '')
        + '. Supported: Windows x64, macOS arm64, Linux x64/glibc (tested on Ubuntu 24.04).');
    return target;
}

export function resolveBinary() {
    const target = selectTarget();
    const require = createRequire(import.meta.url);
    const name = '@ibltools/cli-' + target.suffix;
    const own = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'));
    let manifest;
    try { manifest = require.resolve(name + '/package.json'); }
    catch { throw new Error('Missing platform package ' + name + '@' + own.version + '. Reinstall @ibltools/cli with optional dependencies enabled (npm install --include=optional).'); }
    const installed = JSON.parse(readFileSync(manifest, 'utf8'));
    if (installed.version !== own.version || installed.iblBinaryVersion !== own.iblBinaryVersion) throw new Error('Platform package version mismatch: ' + name + '. Reinstall @ibltools/cli with optional dependencies enabled.');
    let binary;
    try {
        binary = require.resolve(name + '/bin/' + target.executable);
        accessSync(binary, process.platform === 'win32' ? constants.F_OK : constants.X_OK);
    } catch { throw new Error('Missing or non-executable binary in ' + name + '. Reinstall @ibltools/cli.'); }
    return binary;
}

export function launch(binary, args) {
    const child = spawn(binary, args, { stdio: 'inherit', shell: false });
    const handlers = new Map();
    let interrupted;
    for (const signal of ['SIGINT', 'SIGTERM']) {
        const handler = () => { interrupted = signal; child.kill(signal); };
        handlers.set(signal, handler);
        process.on(signal, handler);
    }
    const cleanup = () => { for (const [signal, handler] of handlers) process.off(signal, handler); };
    child.once('error', error => {
        cleanup();
        console.error('ibl-baker: Cannot start binary: ' + error.message + '. Check executable permissions and system runtime libraries.');
        process.exitCode = 1;
    });
    child.once('exit', (code, signal) => {
        cleanup();
        if (signal && process.platform !== 'win32') process.kill(process.pid, signal);
        else process.exitCode = interrupted ? (interrupted === 'SIGINT' ? 130 : 143) : (code ?? 1);
    });
    return child;
}
