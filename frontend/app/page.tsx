'use client';

import { motion } from 'framer-motion';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';

import Nav from '@/components/Nav';
import { api } from '@/lib/api';
import { readPlayer, signIn } from '@/lib/player';

const BLURB = [
  {
    k: 'Grid demand',
    c: 'text-robot',
    d: 'Hourly electricity load for a US region, with the temperature forecast as your only clue.',
  },
  {
    k: 'Mystery stock',
    c: 'text-truth',
    d: 'A real headline drops. The chart stops. Draw what the next 50 bars did.',
  },
  {
    k: 'Search trends',
    c: 'text-crowd',
    d: 'Weekly search interest for one term. When does the season spike?',
  },
];

export default function Landing() {
  const router = useRouter();
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [daily, setDaily] = useState<number | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    const stored = readPlayer();
    if (stored) setName(stored.name);
    api
      .daily()
      .then((d) => {
        setDaily(d.number);
        setOnline(true);
      })
      .catch(() => setOnline(false));
  }, []);

  const start = useCallback(
    async (mode: 'daily' | 'endless') => {
      const trimmed = name.trim();
      if (!trimmed) {
        setError('Pick a name first — it is the only thing we store about you.');
        return;
      }
      setBusy(true);
      setError(null);
      try {
        await signIn(trimmed);
        router.push(`/play?mode=${mode}`);
      } catch (e) {
        setError(
          e instanceof Error && e.message
            ? `Could not reach the server: ${e.message}`
            : 'Could not reach the server.',
        );
        setBusy(false);
      }
    },
    [name, router],
  );

  return (
    <>
      <Nav />
      <main className="mx-auto w-full max-w-5xl px-4 pb-20 pt-10 sm:pt-16">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
        >
          <p className="label">Hackathon demo</p>
          <h1 className="mt-2 text-balance text-5xl font-black leading-[0.95] tracking-tight sm:text-7xl">
            TAPE<span className="text-you">:</span> Draw It
          </h1>
          <p className="mt-4 max-w-xl text-pretty text-lg text-chalk-dim sm:text-xl">
            Draw the future. Beat the AI. Teach it something.
          </p>
        </motion.div>

        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="panel mt-8 p-5 sm:p-6"
        >
          <label htmlFor="name" className="label">
            Display name
          </label>
          <div className="mt-2 flex flex-col gap-3 sm:flex-row">
            <input
              id="name"
              value={name}
              maxLength={32}
              autoComplete="off"
              placeholder="e.g. chart_goblin"
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && void start('daily')}
              className="min-w-0 flex-1 rounded-xl border border-ink-700 bg-ink-950/70 px-4 py-3 text-base outline-none transition placeholder:text-chalk-faint focus:border-you/60"
            />
            <div className="flex gap-3">
              <button
                type="button"
                disabled={busy}
                onClick={() => void start('daily')}
                className="btn-primary flex-1 sm:flex-none"
              >
                Daily 5{daily ? ` · #${daily}` : ''}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void start('endless')}
                className="btn-ghost flex-1 sm:flex-none"
              >
                Endless
              </button>
            </div>
          </div>
          <p className="mt-3 text-xs text-chalk-faint">
            No account, no email. The name lives in this browser and on the leaderboard.
          </p>
          {error && <p className="mt-2 text-sm text-danger">{error}</p>}
          {online === false && (
            <p className="mt-2 text-sm text-danger">
              Backend offline — start it with <code className="num">npm run dev</code>.
            </p>
          )}
        </motion.section>

        <section className="mt-10 grid gap-3 sm:grid-cols-2">
          {BLURB.map((b, i) => (
            <motion.div
              key={b.k}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.16 + i * 0.06 }}
              className="panel p-4"
            >
              <p className={`text-sm font-bold ${b.c}`}>{b.k}</p>
              <p className="mt-1 text-sm text-chalk-dim">{b.d}</p>
            </motion.div>
          ))}
        </section>

        <section className="mt-10 grid gap-4 text-sm text-chalk-dim sm:grid-cols-3">
          {[
            ['1 · Draw', 'You get 10 seconds and 50 slots. One y per x — scribble over it to fix your line.'],
            ['2 · Reveal', 'The truth traces in, then two ghosts: what the crowd drew and what the AI predicted.'],
            ['3 · Teach', 'Your line joins the crowd average. Every 25 drawings the AI re-fits how much it trusts us.'],
          ].map(([t, d]) => (
            <div key={t} className="panel p-4">
              <p className="font-bold text-chalk">{t}</p>
              <p className="mt-1">{d}</p>
            </div>
          ))}
        </section>
      </main>
    </>
  );
}
