#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { launch, resolveBinary } from '../launcher.mjs';
try {
    const binary = resolveBinary();
    const args = process.argv.slice(2);
    if (args[0] === '--version' || args[0] === '-V') {
        const { version } = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
        process.stdout.write('@ibltools/cli ' + version + '\n', () => launch(binary, args));
    } else {
        launch(binary, args);
    }
} catch (error) {
    console.error('ibl-baker: ' + error.message);
    process.exitCode = 1;
}
