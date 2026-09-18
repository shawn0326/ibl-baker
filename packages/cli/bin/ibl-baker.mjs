#!/usr/bin/env node
import { launch, resolveBinary } from '../launcher.mjs';
try {
    launch(resolveBinary(), process.argv.slice(2));
} catch (error) {
    console.error('ibl-baker: ' + error.message);
    process.exitCode = 1;
}
