'use client';

/**
 * What happened to one finished headline: the stamp, the tags, the judge's
 * ruling, the evidence verifier's verdict with the passages it read, the points.
 */

import { AnimatePresence, motion } from 'framer-motion';

import ChangeList from '@/components/ChangeList';
import type { SubmitResult } from '@/lib/api';
import { useCountUp } from '@/lib/useCountUp';

const VERDICT_LABEL = {
  supported: { text: 'SUPPORTED', cls: 'text-truth' },
  refuted: { text: 'REFUTED', cls: 'text-danger' },
  nei: { text: 'NOT ENOUGH INFO', cls: 'text-accent' },
} as const;

const STAMP = {
  snuck: { text: 'SNUCK PAST', cls: 'border-truth text-truth' },
  partial: { text: 'PARTIAL', cls: 'border-accent text-accent' },
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
        ['materiality', p.materiality_mult],
        ['sharp', p.sharp_mult],
        ['vague', p.vague_mult],
        ['partial', p.partial_mult],
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

      {result.tags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {result.tags.map((t) => (
            <span
              key={t}
              className={`chip ${/vague|pedantic/i.test(t) ? 'border-danger/50 text-danger' : 'border-accent/60 text-accent'}`}
            >
              {t}
            </span>
          ))}
        </div>
      )}

      <div className="mt-4 space-y-1 text-sm">
        <p className="text-chalk-faint line-through decoration-chalk-faint/60">{original}</p>
        {result.changes.length > 0 && (
          <p className="text-chalk">
            <ChangeList changes={result.changes} />
          </p>
        )}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl bg-ink-950/60 p-3 text-sm">
          <p className="label">Evidence check{result.mode === 'breaking' ? ' · breaking news' : ''}</p>
          {result.verifier ? (
            <>
              <p className={`num mt-1 text-lg font-bold ${VERDICT_LABEL[result.verifier.verdict].cls}`}>
                {VERDICT_LABEL[result.verifier.verdict].text}
              </p>
              <p className="text-xs text-chalk-dim">
                supported {Math.round(result.verifier.probs.supported * 100)}% · refuted{' '}
                {Math.round(result.verifier.probs.refuted * 100)}% · not enough info{' '}
                {Math.round(result.verifier.probs.nei * 100)}%
              </p>
            </>
          ) : (
            <p className="mt-1 text-chalk-dim">
              {result.outcome === 'timeout' && !result.verdict.explanation
                ? 'Never got to check it.'
                : (result.verdict as { vague_caught?: boolean }).vague_caught
                  ? 'Not checked: too vague to count as a lie.'
                  : 'Not checked: the judge ruled it isn’t a usable lie.'}
            </p>
          )}
          {result.suspicion !== null && (
            <p className="mt-2 text-[11px] text-chalk-faint">
              First glance said {Math.round(result.suspicion * 100)}% suspicious
            </p>
          )}
        </div>
        <div className="rounded-xl bg-ink-950/60 p-3 text-sm">
          <p className="label">Judge{result.verdict.judge === 'mock' ? ' (mock)' : ''}</p>
          <p className="mt-1 text-chalk-dim">
            {result.verdict.explanation ?? 'Ran out of time before submitting.'}
          </p>
          {result.verdict.edit_type && <span className="chip mt-2">{result.verdict.edit_type}</span>}
        </div>
      </div>

      {result.verifier && result.verifier.evidence.length === 0 && (
        <p className="mt-4 rounded-xl bg-ink-950/40 p-3 text-sm text-chalk-dim">
          {result.mode === 'breaking'
            ? 'No other coverage found — the fact-checker had nothing to check your claim against.'
            : 'The fact-checker found no relevant passages for this claim.'}
        </p>
      )}
      {result.verifier && result.verifier.evidence.length > 0 && (
        <details className="mt-4 rounded-xl bg-ink-950/40 p-3 text-sm" open={result.outcome === 'caught'}>
          <summary className="cursor-pointer font-semibold text-chalk">
            What the verifier read ({result.verifier.evidence.length} passage
            {result.verifier.evidence.length === 1 ? '' : 's'})
          </summary>
          <ul className="mt-2 space-y-2">
            {result.verifier.evidence.map((e, i) => (
              <li
                key={i}
                className={`rounded-lg border p-2.5 ${e.decisive ? 'border-accent/60' : 'border-ink-700'}`}
              >
                <p className="text-chalk-dim">“{e.text}”</p>
                <p className="mt-1 text-[11px] text-chalk-faint">
                  {e.decisive && <span className="mr-1 font-semibold text-accent">deciding passage ·</span>}
                  <a href={e.url} target="_blank" rel="noreferrer" className="underline">
                    {e.source}
                  </a>{' '}
                  · supports {Math.round(e.probs.supported * 100)}% · refutes {Math.round(e.probs.refuted * 100)}%
                </p>
              </li>
            ))}
          </ul>
        </details>
      )}

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
