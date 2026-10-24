'use client';

/** The round clock as a shrinking bar. Red and pulsing for the last 5 seconds. */

export default function TimerBar({
  remaining,
  total,
  paused,
}: {
  remaining: number;
  total: number;
  paused: boolean;
}) {
  const frac = total > 0 ? Math.max(0, Math.min(1, remaining / total)) : 0;
  const danger = remaining <= 5;
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs text-chalk-dim">
        <span className="label">{paused ? 'Clock paused — judging' : 'Time'}</span>
        <span className={`num font-bold ${danger ? 'text-danger' : 'text-chalk'}`}>
          {Math.max(0, remaining).toFixed(1)}s
        </span>
      </div>
      <div className="mt-1.5 h-2.5 overflow-hidden rounded-full bg-ink-800">
        <div
          className={`h-full rounded-full transition-[width] duration-100 ease-linear ${
            danger ? 'animate-pulse bg-danger' : 'bg-accent'
          } ${paused ? 'opacity-50' : ''}`}
          style={{ width: `${frac * 100}%` }}
        />
      </div>
    </div>
  );
}
