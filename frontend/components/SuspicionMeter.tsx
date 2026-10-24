'use client';

/**
 * The live "first glance" meter: the fact-checker's read of your edit against
 * the single best source passage, as you type. It does NOT decide the round --
 * on submit the verifier reads the top retrieved passages and rules -- so it is
 * labelled as a hint. The needle eases so it swings, not jumps.
 */

import { motion } from 'framer-motion';

export default function SuspicionMeter({
  value,
  threshold,
  nearFrom,
  pending,
  shaking,
}: {
  value: number | null;
  threshold: number;
  nearFrom: number;
  pending: boolean;
  shaking: boolean;
}) {
  const v = value ?? 0;
  const pct = Math.round(v * 100);
  const caught = value !== null && v >= threshold;
  const near = value !== null && !caught && v >= nearFrom;
  const tone = caught ? 'bg-danger' : near ? 'bg-accent' : 'bg-truth';
  const label = value === null ? 'Edit the headline…' : caught ? 'Looks suspicious' : near ? 'Borderline' : 'Looks fine';

  return (
    <div className={shaking ? 'animate-shake' : ''} aria-live="polite">
      <div className="flex items-baseline justify-between">
        <span className="label">First glance</span>
        <span className="text-xs text-chalk-dim">
          {label}
          {pending && <span className="ml-2 text-chalk-faint">…</span>}
        </span>
      </div>
      <div className="relative mt-2 h-5 overflow-hidden rounded-full border border-ink-700 bg-ink-950">
        <motion.div
          className={`h-full ${tone}`}
          initial={false}
          animate={{ width: `${Math.max(2, pct)}%` }}
          transition={{ type: 'spring', stiffness: 140, damping: 18 }}
        />
        <div
          className="absolute inset-y-0 w-0.5 bg-chalk"
          style={{ left: `${threshold * 100}%` }}
          aria-hidden
        />
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-chalk-faint">
        <span>looks true</span>
        <span className="num text-sm font-bold text-chalk">{value === null ? '—' : `${pct}%`}</span>
        <span>looks false</span>
      </div>
      <p className="mt-1 text-[11px] text-chalk-faint">
        A quick look at the source article. On submit the fact-checker searches more evidence and makes the real call.
      </p>
    </div>
  );
}
