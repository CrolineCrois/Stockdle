#!/usr/bin/env node
/**
 * Cross-platform task runner for Sneak It Past.
 *
 * Exists so the root package.json scripts work the same on Windows, macOS and
 * Linux: the venv interpreter lives at `.venv/Scripts/python.exe` on Windows
 * and `.venv/bin/python` elsewhere, and npm scripts cannot branch on that.
 *
 *   node scripts/tasks.mjs setup      venv, deps, seed headlines, stub detector, frontend
 *   node scripts/tasks.mjs dev        API (:8000) and web app (:3000) together
 *   node scripts/tasks.mjs setup-ml   torch + transformers, training fakes, DistilBERT v0
 *   node scripts/tasks.mjs scrape     pull fresh headlines from the RSS feeds
 *   node scripts/tasks.mjs test       backend test suite
 */

import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const BACKEND = join(ROOT, 'backend');
const FRONTEND = join(ROOT, 'frontend');
const WIN = process.platform === 'win32';
const VENV_PY = join(BACKEND, '.venv', WIN ? 'Scripts/python.exe' : 'bin/python');

/**
 * Pick a system Python the pinned wheels support. The newest Python is often
 * ahead of compiled dependencies (pydantic-core failed to build on 3.14), so
 * prefer known-good versions and fall back to whatever `python3` is.
 */
function systemPython() {
  const candidates = WIN
    ? [['py', ['-3.13']], ['py', ['-3.12']], ['py', ['-3.11']], ['python', []]]
    : [['python3.13', []], ['python3.12', []], ['python3.11', []], ['python3', []]];
  for (const [cmd, pre] of candidates) {
    const probe = spawnSync(cmd, [...pre, '--version'], { encoding: 'utf8', shell: WIN });
    if (probe.status === 0) return [cmd, pre];
  }
  console.error('\n  No Python 3.11+ found. Install Python 3.13 and re-run setup.\n');
  process.exit(1);
}

function py() {
  if (existsSync(VENV_PY)) return VENV_PY;
  console.error(`\n  No virtualenv at ${VENV_PY}\n  Run:  npm run setup\n`);
  process.exit(1);
}

function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: 'inherit', shell: WIN, ...opts });
    child.on('error', reject);
    child.on('exit', (code) =>
      code === 0 ? resolve() : reject(new Error(`${cmd} exited with ${code}`)),
    );
  });
}

function runParallel(specs) {
  const children = specs.map(({ name, cmd, args, cwd }) => {
    console.log(`  [${name}] ${cmd} ${args.join(' ')}`);
    const child = spawn(cmd, args, { stdio: 'inherit', shell: WIN, cwd });
    child.on('exit', (code) => {
      if (code !== 0 && code !== null) console.error(`  [${name}] exited with ${code}`);
    });
    return child;
  });
  const stop = () => children.forEach((c) => !c.killed && c.kill());
  process.on('SIGINT', () => {
    stop();
    process.exit(0);
  });
  process.on('SIGTERM', stop);
  process.on('exit', stop);
  return new Promise(() => {});
}

const tasks = {
  async setup() {
    if (!existsSync(VENV_PY)) {
      const [cmd, pre] = systemPython();
      console.log(`→ creating backend virtualenv with ${cmd} ${pre.join(' ')}`.trim());
      await run(cmd, [...pre, '-m', 'venv', '.venv'], { cwd: BACKEND });
    }
    console.log('→ installing backend requirements');
    await run(VENV_PY, ['-m', 'pip', 'install', '-q', '--upgrade', 'pip'], { cwd: BACKEND });
    await run(VENV_PY, ['-m', 'pip', 'install', '-q', '-r', 'requirements.txt'], { cwd: BACKEND });
    console.log('→ loading seed headlines');
    await run(VENV_PY, ['-m', 'ingest.seed'], { cwd: BACKEND });
    console.log('→ training the stub detector');
    await run(VENV_PY, ['-m', 'detector.train_stub'], { cwd: BACKEND });
    console.log('→ installing frontend packages');
    await run('npm', ['install', '--no-audit', '--no-fund'], { cwd: FRONTEND });
    console.log('\n  Ready. Start everything with:  npm run dev\n');
  },

  dev: () => {
    console.log('\n  Sneak It Past — http://localhost:3000  (API on :8000)\n');
    return runParallel([
      { name: 'api', cmd: py(), args: ['-m', 'uvicorn', 'app.main:app', '--reload', '--port', '8000'], cwd: BACKEND },
      { name: 'web', cmd: 'npm', args: ['run', 'dev'], cwd: FRONTEND },
    ]);
  },
  api: () => run(py(), ['-m', 'uvicorn', 'app.main:app', '--reload', '--port', '8000'], { cwd: BACKEND }),
  web: () => run('npm', ['run', 'dev'], { cwd: FRONTEND }),
  scrape: () => run(py(), ['-m', 'ingest.scrape_rss'], { cwd: BACKEND }),
  seed: () => run(py(), ['-m', 'ingest.seed'], { cwd: BACKEND }),
  'train-stub': () => run(py(), ['-m', 'detector.train_stub'], { cwd: BACKEND }),
  /** The real detector: installs torch/transformers (~1GB), makes fakes, trains v0. */
  async 'setup-ml'() {
    console.log('→ installing ML requirements (torch, transformers, sentence-transformers)');
    await run(py(), ['-m', 'pip', 'install', '-q', '-r', 'requirements-optional.txt'], { cwd: BACKEND });
    console.log('→ generating training fakes (Claude if ANTHROPIC_API_KEY is set, else rules)');
    await run(py(), ['-m', 'ingest.make_fakes'], { cwd: BACKEND });
    console.log('→ training detector v0 (DistilBERT)');
    await run(py(), ['-m', 'detector.train_v0'], { cwd: BACKEND });
  },
  fakes: () => run(py(), ['-m', 'ingest.make_fakes'], { cwd: BACKEND }),
  'train-v0': () => run(py(), ['-m', 'detector.train_v0'], { cwd: BACKEND }),
  'patch-day': () => run(py(), ['-m', 'verifier.patch_day', ...process.argv.slice(3)], { cwd: BACKEND }),
  'patch-style': () => run(py(), ['-m', 'detector.patch_day', ...process.argv.slice(3)], { cwd: BACKEND }),
  articles: () => run(py(), ['-m', 'ingest.articles'], { cwd: BACKEND }),
  evaluate: () => run(py(), ['-m', 'evaluation.run', ...process.argv.slice(3)], { cwd: BACKEND }),
  bounties: () => run(py(), ['-m', 'detector.bounties'], { cwd: BACKEND }),
  test: () => run(py(), ['-m', 'pytest'], { cwd: BACKEND }),
  build: () => run('npm', ['run', 'build'], { cwd: FRONTEND }),
};

const task = process.argv[2];
if (!task || !tasks[task]) {
  console.error(`\n  Unknown task ${task ?? '(none)'}.\n  Available: ${Object.keys(tasks).join(', ')}\n`);
  process.exit(1);
}
tasks[task]().catch((err) => {
  console.error(`\n  ${err.message}\n`);
  process.exit(1);
});
