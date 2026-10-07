const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const pkg = require('../../package.json');
const root = path.resolve(__dirname, '../..');

function git(...args) {
    try {
        return execFileSync('git', args, { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
    } catch {
        return '';
    }
}

function repositoryUrl(value) {
    const normalized = value.replace(/^git@([^:]+):/, 'https://$1/').replace(/^github:/, 'https://github.com/');
    const url = new URL(normalized);
    url.protocol = 'https:';
    url.username = '';
    url.password = '';
    url.pathname = url.pathname.replace(/\.git\/?$/, '').replace(/\/$/, '');
    return url.toString().replace(/\/$/, '');
}

const hash = process.env.BUILD_SHA || git('rev-parse', 'HEAD');
const repository = repositoryUrl(process.env.BUILD_SOURCE_URL || git('config', '--get', 'remote.origin.url') || pkg.repository);
const sourceUrl = hash && hash !== 'unknown' ? `${repository}/tree/${hash}` : repository;
const values = { version: pkg.version, buildTime: new Date().toISOString(), sourceUrl };
const source = Object.entries(values).map(([key, value]) => `export const ${key} = ${JSON.stringify(value)};`).join('\n') + '\n';
const destination = path.resolve(__dirname, '../src/environments/version.ts');
fs.writeFileSync(destination, source);
console.log(`Updated application version ${pkg.version}`);
