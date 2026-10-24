'use client';

/** The card above the chart: what the player knows before drawing. */

import type { GameRound } from '@/lib/api';

const ACCENT: Record<string, string> = {
  electricity: 'from-robot/15 to-transparent border-robot/30',
  stock: 'from-truth/15 to-transparent border-truth/30',
  trends: 'from-crowd/15 to-transparent border-crowd/30',
};

const EYEBROW_COLOR: Record<string, string> = {
  electricity: 'text-robot',
  stock: 'text-truth',
  trends: 'text-crowd',
};

export default function ContextCard({ round }: { round: GameRound }) {
  const { context } = round;

  return (
    <div
      className={`panel relative overflow-hidden border bg-gradient-to-br p-4 sm:p-5 ${
        ACCENT[round.type] ?? 'border-ink-700'
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`text-[11px] font-bold uppercase tracking-[0.18em] ${
            EYEBROW_COLOR[round.type] ?? 'text-chalk-dim'
          }`}
        >
          {context.eyebrow}
        </span>
        {round.is_seed && <span className="chip">seed data</span>}
      </div>

      <h2 className="mt-2 text-balance text-lg font-semibold leading-snug sm:text-xl">
        {context.title}
      </h2>

      <p className="mt-1.5 text-sm text-chalk-dim">{context.subtitle}</p>

      {context.chips?.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {context.chips.map((c) => (
            <span key={c} className="chip">
              {c}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
