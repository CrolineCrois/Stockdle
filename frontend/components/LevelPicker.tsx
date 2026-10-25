'use client';

/**
 * Pick which fact-checker to play against. Every patch day adds a level: the
 * newest is the hardest and scores full points; older ones are easier and
 * score less. Rounds on every level are logged and reviewed.
 */

import type { CI, LevelInfo } from '@/lib/api';
import { pct } from '@/lib/viz';

const rate = (c: CI | null, what: string) =>
  c && c.value !== null && c.n > 0 ? `catches ${pct(c.value)} of ${what} (${c.n})` : null;

export default function LevelPicker({ levels, onPick, last }: {
  levels: LevelInfo[];
  onPick: (name: string) => void;
  last?: string | null;
}) {
  const hardestFirst = [...levels].reverse();
  return (
    <section className="panel p-5 sm:p-6">
      <p className="label">Choose your opponent</p>
      <h1 className="mt-1 text-2xl font-black tracking-tight">Which fact-checker do you want to fool?</h1>
      <p className="mt-2 text-sm text-chalk-dim">
        Every patch day trains a new version on the lies players snuck past the last one. The newest is the
        hardest and scores full points.
      </p>
      <div className="mt-5 grid gap-3">
        {hardestFirst.map((lv) => {
          const live = rate(lv.live_caught, 'judge-approved lies in play');
          return (
            <button
              key={lv.name}
              type="button"
              onClick={() => onPick(lv.name)}
              className={`rounded-xl border p-4 text-left transition hover:border-accent/60 hover:bg-ink-800/40 ${
                lv.name === last ? 'border-accent/50' : 'border-ink-700'
              }`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-lg font-bold">Level {lv.number}</span>
                <span className="chip num">{lv.name}</span>
                {lv.newest ? (
                  <span className="chip border-accent/60 text-accent">Hardest · full points</span>
                ) : (
                  <span className="chip">×{lv.points_mult} points</span>
                )}
                {lv.name === last && <span className="text-xs text-chalk-faint">last played</span>}
              </div>
              <p className="mt-1 text-sm text-chalk-dim">
                {lv.number === 0
                  ? 'The off-the-shelf fact-checker, before any player data.'
                  : `Trained on ${lv.note.match(/(\d+) approved/)?.[1] ?? 'players’'} approved lies players snuck past the level before.`}
              </p>
              {live && <p className="mt-1 text-xs text-chalk-faint">{live}</p>}
            </button>
          );
        })}
      </div>
    </section>
  );
}
