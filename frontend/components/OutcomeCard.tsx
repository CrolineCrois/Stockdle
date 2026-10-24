'use client';

/** What happened to one finished headline: the stamp, the judge's ruling, the points. */

import { AnimatePresence, motion } from 'framer-motion';

import type { SubmitResult } from '@/lib/api';
import { useCountUp } from '@/lib/useCountUp';

const STAMP = {
  snuck: { text: 'SNUCK PAST', cls: 'border-truth text-truth' },
  caught: { text: 'CAUGHT', cls: 'border-danger text-danger' },
  timeout: { text: "TIME'S UP", cls: 'border-danger text-danger' },
  invalid: { text: 'NOT A LIE', cls: 'border-chalk-dim text-chalk-dim' },
} as const;

export default function OutcomeCard({
  result,
  original,
  onNext,
}: {
  result: SubmitResult;
  original: string;
  onNext: () => void;
}) {
  const stamp = STAMP[result.outcome];
  const exhausted = result.events.includes('exhausted');
  const p = result.points;
  const shown = useCountUp(p?.total ?? 0);
  const caught = result.outcome === 'caught' || result.outcome === 'timeout';
  const multipliers = p
    ? ([
        ['words', p.word_mult],
        ['streak', p.streak_mult],
        ['time', p.time_mult],
        ['novel', p.novelty_mult],
        ['bounty', p.bounty_mult],
      ] as const).filter(([, m]) => m !== 1)
    : [];

  return (
    <div className={`panel relative overflow-hidden p-5 ${caught ? 'animate-shake' : ''}`}>
      <motion.div
        initial={{ scale: 2.4, rotate: -14, opacity: 0 }}
        animate={{ scale: 1, rotate: -6, opacity: 1 }}
        transition={{ type: 'spring', stiffness: 260, damping: 16 }}
        className={`inline-block rounded-lg border-4 px-4 py-1 text-3xl font-black tracking-widest ${stamp.cls}`}
      >
        {exhausted ? 'OUT OF TRIES' : stamp.text}
      </motion.div>

      <AnimatePresence>
        {result.events.includes('quick_hands') && (
          <motion.span
            key="quick"
            initial={{ y: 10, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            className="ml-3 chip border-accent/60 text-accent"
          >
            ⚡ Quick hands
          </motion.span>
        )}
        {result.events.includes('zero_day') && (
          <motion.span
            key="zero"
            initial={{ y: 10, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.15 }}
            className="ml-3 chip border-crowd/60 text-crowd"
          >
            🧨 Zero-day exploit · +50%
          </motion.span>
        )}
        {p && p.bounty_mult > 1 && (
          <motion.span key="bounty" initial={{ y: 10, opacity: 0 }} animate={{ y: 0, opacity: 1 }} className="ml-3 chip border-accent/60 text-accent">
            ★ Bounty · 3×
          </motion.span>
        )}
        {result.near_miss && (
          <motion.span key="near" initial={{ y: 10, opacity: 0 }} animate={{ y: 0, opacity: 1 }} className="ml-3 chip">
            so close!
          </motion.span>
        )}
      </AnimatePresence>

      <div className="mt-4 space-y-1 text-sm">
        <p className="text-chalk-faint line-through decoration-chalk-faint/60">{original}</p>
        {result.changes.length > 0 && (
          <p className="text-chalk">
            {result.changes.map((c, i) => (
              <span key={i} className="mr-2">
                {c.before && <span className="text-chalk-faint line-through">{c.before}</span>}
                {c.before && c.after && ' → '}
                {c.after && <span className="font-semibold text-accent">{c.after}</span>}
              </span>
            ))}
          </p>
        )}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl bg-ink-950/60 p-3 text-sm">
          <p className="label">Detector</p>
          <p className="mt-1 text-chalk">
            {result.suspicion === null ? 'Never got to see it.' : (
              <>
                <span className="num text-lg font-bold">{Math.round(result.suspicion * 100)}%</span> suspicious
              </>
            )}
          </p>
        </div>
        <div className="rounded-xl bg-ink-950/60 p-3 text-sm">
          <p className="label">Judge{result.verdict.judge === 'mock' ? ' (mock)' : ''}</p>
          <p className="mt-1 text-chalk-dim">
            {result.outcome === 'timeout' ? 'Ran out of time before submitting.' : result.verdict.explanation}
          </p>
          {result.verdict.edit_type && <span className="chip mt-2">{result.verdict.edit_type}</span>}
        </div>
      </div>

      {p && (
        <div className="mt-4">
          <p className="num text-4xl font-black text-accent">+{shown.toLocaleString()}</p>
          <p className="mt-1 text-xs text-chalk-dim">
            {p.base} base{multipliers.map(([k, m]) => ` × ${m} ${k}`).join('')}
          </p>
        </div>
      )}

      <button type="button" onClick={onNext} className="btn-primary mt-5 w-full sm:w-auto" autoFocus>
        {result.run_over ? 'See your run' : 'Next headline'} <kbd className="num text-xs opacity-70">↵</kbd>
      </button>
    </div>
  );
}
