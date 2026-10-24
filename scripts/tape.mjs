#!/usr/bin/env node
/**
 * Cross-platform task runner for TAPE.
 *
 * Exists so the root package.json scripts work the same on Windows, macOS and
 * Linux: the venv interpreter lives at `.venv/Scripts/python.exe` on Windows
 * and `.venv/bin/python` elsewhere, and npm scripts cannot branch on that.
 *
 *   node scripts/tape.mjs setup       create the venv, install, build data, train
 *   node scripts/tape.mjs dev         run the API and the web app together
 *   node scripts/tape.mjs api|web     run just one of them
 *   node scripts/tape.mjs pipeline    rebuild rounds (live sources where possible)
 *   node scripts/tape.mjs train       refit the base forecasters
 *   node scripts/tape.mjs seed-demo   add the simulated demo cohort
 *   node scripts/tape.mjs reset-demo  wipe play data and re-seed it
 *   node scripts/tape.mjs test        backend test suite
 */

import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const BACKEND = join(ROOT, 'backend');
const FRONTEND = join(ROOT, 'frontend');
const WIN = process.platform === 'win32';

const VENV_PY = join(BACKEND, '.venv', WIN ? 'Scripts/python.exe' : 'bin/python');
const SYSTEM_PY = WIN ? 'python' : 'python3';

function py() {
  if (existsSync(VENV_PY)) return VENV_PY;
  console.error(
    `\n  No virtualenv at ${VENV_PY}\n  Run:  npm run setup\n`,
  );
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

/** Run several long-lived processes, prefixing nothing and sharing the console. */
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
      console.log('→ creating backend virtualenv');
      await run(SYSTEM_PY, ['-m', 'venv', '.venv'], { cwd: BACKEND });
    }
    console.log('→ installing backend requirements');
    await run(VENV_PY, ['-m', 'pip', 'install', '-q', '--upgrade', 'pip'], { cwd: BACKEND });
    await run(VENV_PY, ['-m', 'pip', 'install', '-q', '-r', 'requirements.txt'], {
      cwd: BACKEND,
    });
    console.log('→ generating seed data');
    await run(VENV_PY, ['-m', 'pipeline.seed_gen'], { cwd: BACKEND });
    console.log('→ building rounds (offline; use `npm run pipeline` for live sources)');
    await run(VENV_PY, ['-m', 'pipeline.build_rounds', '--offline'], { cwd: BACKEND });
    console.log('→ training the base forecasters');
    await run(VENV_PY, ['-m', 'model.train'], { cwd: BACKEND });
    console.log('→ installing frontend packages');
    await run('npm', ['install', '--no-audit', '--no-fund'], { cwd: FRONTEND });
    console.log('\n  Ready. Start everything with:  npm run dev');
    console.log('  Optional, for a lively dashboard:  npm run seed-demo\n');
  },

  api: () =>
    run(py(), ['-m', 'uvicorn', 'app.main:app', '--reload', '--port', '8000'], {
      cwd: BACKEND,
    }),

  web: () => run('npm', ['run', 'dev'], { cwd: FRONTEND }),

  dev: () => {
    console.log('\n  TAPE: Draw It — http://localhost:3000  (API on :8000)\n');
    return runParallel([
      {
        name: 'api',
        cmd: py(),
        args: ['-m', 'uvicorn', 'app.main:app', '--reload', '--port', '8000'],
        cwd: BACKEND,
      },
      { name: 'web', cmd: 'npm', args: ['run', 'dev'], cwd: FRONTEND },
    ]);
  },

  pipeline: () => run(py(), ['-m', 'pipeline.build_rounds'], { cwd: BACKEND }),
  'pipeline-offline': () =>
    run(py(), ['-m', 'pipeline.build_rounds', '--offline'], { cwd: BACKEND }),
  seed: () => run(py(), ['-m', 'pipeline.seed_gen'], { cwd: BACKEND }),
  train: () => run(py(), ['-m', 'model.train'], { cwd: BACKEND }),
  plot: () => run(py(), ['-m', 'pipeline.plot_rounds'], { cwd: BACKEND }),
  'seed-demo': () => run(py(), ['-m', 'scripts.seed_demo'], { cwd: BACKEND }),
  'reset-demo': () => run(py(), ['-m', 'scripts.seed_demo', '--reset'], { cwd: BACKEND }),
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
