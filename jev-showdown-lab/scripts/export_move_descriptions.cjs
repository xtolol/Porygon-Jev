#!/usr/bin/env node
'use strict';

const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const DEFAULT_SHOWDOWN_PATH = path.resolve(__dirname, '../../pokemon-showdown');
const DEFAULT_OUTPUT = path.resolve(
    __dirname, '../src/showdown_state_tracer/data/move_descriptions_gen9.json'
);

function parseArgs(args) {
    const options = {showdownPath: DEFAULT_SHOWDOWN_PATH, output: DEFAULT_OUTPUT};
    for (let index = 0; index < args.length; index++) {
        const arg = args[index];
        if (arg === '--help' || arg === '-h') {
            return null;
        }
        if (arg !== '--showdown-path' && arg !== '--output') {
            throw new Error(`Unknown option: ${arg}. Use --help for usage.`);
        }
        const value = args[++index];
        if (!value || value.startsWith('--')) {
            throw new Error(`Expected a path after ${arg}.`);
        }
        options[arg === '--showdown-path' ? 'showdownPath' : 'output'] = path.resolve(value);
    }
    return options;
}

function exportDescriptions({showdownPath, output}) {
    const dexPath = path.join(showdownPath, 'dist/sim/dex.js');
    if (!fs.existsSync(dexPath)) {
        throw new Error(
            `Built Showdown Dex not found at ${dexPath}. ` +
            'Run npm ci and npm run build in the Showdown checkout, ' +
            'then retry with --showdown-path pointing to that checkout.'
        );
    }

    // Read the revision from this checkout, not an enclosing repository.
    const gitOptions = {cwd: showdownPath, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']};
    const gitRoot = execFileSync('git', ['rev-parse', '--show-toplevel'], gitOptions).trim();
    if (fs.realpathSync(gitRoot) !== fs.realpathSync(showdownPath)) {
        throw new Error('--showdown-path must point to the root of a Showdown Git checkout.');
    }
    const revision = execFileSync('git', ['rev-parse', 'HEAD'], gitOptions).trim();
    const changedData = execFileSync(
        'git', ['status', '--porcelain', '--', 'sim', 'data'], gitOptions
    ).trim();
    if (changedData) {
        throw new Error(
            'Showdown sim/ or data/ contains uncommitted changes. ' +
            'Use a clean checkout and rebuild so the recorded revision identifies the source.'
        );
    }

    const {Dex} = require(dexPath);
    const dex = Dex.mod('gen9');
    const text = dex.loadTextData('en').Moves;
    const moves = {};
    const missing = [];
    for (const move of [...dex.moves.all()].sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0)) {
        if (!move.exists) continue;
        const description = text[move.id]?.shortDesc;
        if (typeof description === 'string' && description.trim()) {
            moves[move.id] = description;
        } else {
            missing.push(move.id);
        }
    }
    if (!Object.keys(moves).length) {
        throw new Error('Showdown returned no move descriptions. Rebuild the checkout and retry.');
    }
    const data = {
        schema_version: 1,
        generation: 9,
        language: 'en',
        source: 'https://github.com/smogon/pokemon-showdown',
        showdown_revision: revision,
        moves,
    };

    // Finish reading and validating before atomically replacing an existing export.
    const serialized = JSON.stringify(data, null, 2) + '\n';
    fs.mkdirSync(path.dirname(output), {recursive: true});
    const temporary = `${output}.${process.pid}.tmp`;
    try {
        fs.writeFileSync(temporary, serialized, {encoding: 'utf8', flag: 'wx'});
        fs.renameSync(temporary, output);
    } finally {
        if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
    }
    console.log(`Exported ${Object.keys(moves).length} descriptions to ${output}`);
    if (missing.length) console.log(`No description: ${missing.join(', ')}`);
}

try {
    const options = parseArgs(process.argv.slice(2));
    if (options === null) {
        console.log(
            'Usage: node scripts/export_move_descriptions.cjs ' +
            '[--showdown-path PATH] [--output PATH]\n' +
            'Export English Gen 9 descriptions from a built, clean Showdown checkout.\n' +
            'Rebuild Showdown after updating it and before refreshing this export.'
        );
    } else {
        exportDescriptions(options);
    }
} catch (error) {
    console.error(`Move description export failed: ${error.message}`);
    process.exitCode = 1;
}
