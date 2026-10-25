'use client';

import { motion } from 'framer-motion';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';

import Nav from '@/components/Nav';
import { api, versionsApi } from '@/lib/api';
import { readPlayer, signIn } from '@/lib/player';

const STEPS = [
  ['1 · Read', 'A real headline from today’s news, with a snippet of the article it came from.'],
  ['2 · Twist', 'Change up to 3 words to make it false. Fewer words, more points.'],
  ['3 · Sneak', 'Submit. If the fact-checker can’t find evidence against it, you snuck it past.'],
];

export default function Landing() {
  const router = useRouter();
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<{ judge: string; detector: string | null } | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    const stored = readPlayer();
    if (stored) setName(stored.name);
    api
      .health()
      .then((h) => {
        setStatus({ judge: h.judge, detector: null });
        setOnline(true);
        // The live fact-checker (the old style "detector" no longer decides anything).
        versionsApi
          .verifier()
          .then((v) => setStatus({ judge: h.judge, detector: v.current }))
          .catch(() => undefined);
      })
      .catch(() => setOnline(false));
  }, []);

  const start = useCallback(async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError('Pick a name first — it is the only thing we store about you.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await signIn(trimmed);
      router.push('/play');
    } catch (e) {
      setError(e instanceof Error && e.message ? `Could not reach the server: ${e.message}` : 'Could not reach the server.');
      setBusy(false);
    }
  }, [name, router]);

  return (
    <>
      <Nav />
      <main className="mx-auto w-full max-w-3xl px-4 pb-20 pt-10 sm:pt-16">
        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45 }}>
          <p className="label">Hackathon demo · misinformation research</p>
          <h1 className="mt-2 text-balance text-5xl font-black leading-[0.95] tracking-tight sm:text-7xl">
            Erm, <span className="text-accent">Akthually</span> <span aria-hidden>🤓</span>
          </h1>
          <p className="mt-4 max-w-xl text-pretty text-lg text-chalk-dim sm:text-xl">
            Edit a true headline into a lie the AI fact-checker can’t catch. Every trick that works
            becomes training data — and the fact-checker gets harder.
          </p>
        </motion.div>

        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, delay: 0.08 }}
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
              placeholder="e.g. spin_doctor"
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && void start()}
              className="min-w-0 flex-1 rounded-xl border border-ink-700 bg-ink-950/70 px-4 py-3 text-base outline-none transition placeholder:text-chalk-faint focus:border-accent/60"
            />
            <button type="button" disabled={busy} onClick={() => void start()} className="btn-primary">
              Start a run · 3 lives
            </button>
          </div>

          <div className="mt-4 rounded-xl border border-ink-700 bg-ink-950/50 p-3 text-xs leading-relaxed text-chalk-dim">
            <p className="font-semibold text-chalk">Before you play</p>
            <p className="mt-1">
              Everything you type is <strong className="text-chalk">logged for research</strong> and used to
              train the fact-checker. The headlines you make are synthetic misinformation: they stay in our
              database, labelled as made-up, and are never published. Please don’t copy them anywhere
              else. We store a display name only — no email, no account.
            </p>
          </div>

          {error && <p className="mt-3 text-sm text-danger">{error}</p>}
          {online === false && (
            <p className="mt-3 text-sm text-danger">
              Backend offline — start it with <code className="num">npm run dev</code>.
            </p>
          )}
          {status && (
            <p className="mt-3 text-xs text-chalk-faint">
              Fact-checker <span className="num">{status.detector ?? '…'}</span> · judge{' '}
              <span className="num">{status.judge}</span>
              {status.judge === 'mock' && ' (no API key: a rule-based stand-in is judging)'}
            </p>
          )}
        </motion.section>

        <section className="mt-8 grid gap-3 text-sm text-chalk-dim sm:grid-cols-3">
          {STEPS.map(([t, d]) => (
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
