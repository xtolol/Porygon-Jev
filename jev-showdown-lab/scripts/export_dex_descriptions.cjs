#!/usr/bin/env node
'use strict';

const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const DEFAULT_SHOWDOWN_PATH = path.resolve(__dirname, '../../pokemon-showdown');
const KINDS = {
    moves: {filename: 'move_descriptions_gen9.json', textTable: 'Moves'},
    abilities: {filename: 'ability_descriptions_gen9.json', textTable: 'Abilities'},
    items: {filename: 'item_descriptions_gen9.json', textTable: 'Items'},
};

function parseArgs(args) {
    const options = {showdownPath: DEFAULT_SHOWDOWN_PATH, output: null, kind: 'moves'};
    for (let index = 0; index < args.length; index++) {
        const arg = args[index];
        if (arg === '--help' || arg === '-h') {
            return null;
        }
        if (!['--showdown-path', '--output', '--kind'].includes(arg)) {
            throw new Error(`Unknown option: ${arg}. Use --help for usage.`);
        }
        const value = args[++index];
        if (!value || value.startsWith('--')) {
            throw new Error(`Expected a value after ${arg}.`);
        }
        if (arg === '--kind') {
            if (!Object.hasOwn(KINDS, value)) {
                throw new Error(`Unknown kind: ${value}. Choose moves, abilities, or items.`);
            }
            options.kind = value;
        } else {
            options[arg === '--showdown-path' ? 'showdownPath' : 'output'] = path.resolve(value);
        }
    }
    options.output ??= path.resolve(
        __dirname, '../src/showdown_state_tracer/data', KINDS[options.kind].filename
    );
    return options;
}

function exportDescriptions({showdownPath, output, kind}) {
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
    const text = dex.loadTextData('en')[KINDS[kind].textTable];
    const descriptions = {};
    const missing = [];
    for (const entry of [...dex[kind].all()].sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0)) {
        if (!entry.exists) continue;
        const description = text[entry.id]?.shortDesc;
        if (typeof description === 'string' && description.trim()) {
            descriptions[entry.id] = description;
        } else {
            missing.push(entry.id);
        }
    }
    if (!Object.keys(descriptions).length) {
        throw new Error(`Showdown returned no ${kind} descriptions. Rebuild the checkout and retry.`);
    }
    const data = {
        schema_version: 1,
        generation: 9,
        language: 'en',
        source: 'https://github.com/smogon/pokemon-showdown',
        showdown_revision: revision,
        [kind]: descriptions,
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
    console.log(`Exported ${Object.keys(descriptions).length} ${kind} descriptions to ${output}`);
    if (missing.length) console.log(`No description: ${missing.join(', ')}`);
}

try {
    const options = parseArgs(process.argv.slice(2));
    if (options === null) {
        console.log(
            'Usage: node scripts/export_dex_descriptions.cjs ' +
            '[--kind moves|abilities|items] [--showdown-path PATH] [--output PATH]\n' +
            'Export English Gen 9 descriptions from a built, clean Showdown checkout.\n' +
            'Defaults to moves. Each kind has a separate bundled JSON output.\n' +
            'Rebuild Showdown after updating it and before refreshing this export.'
        );
    } else {
        exportDescriptions(options);
    }
} catch (error) {
    console.error(`Dex description export failed: ${error.message}`);
    process.exitCode = 1;
}
