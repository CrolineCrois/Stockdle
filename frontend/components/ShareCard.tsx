'use client';

/**
 * End-of-run card with a copyable result. The share text carries numbers only
 * -- never a headline -- so no player-made fake can leave the game through it.
 */

import { useState } from 'react';

import type { RunInfo } from '@/lib/api';

export function shareText(run: RunInfo): string {
  return [
    `🕵️ Sneak It Past — ${run.score.toLocaleString()} pts`,
    `✅ ${run.snuck} snuck past · 〰️ ${run.partial} partial · ❌ ${run.caught} caught · 🔥 best streak ${run.best_streak}`,
    `vs detector ${run.detector_version}`,
  ].join('\n');
}

export default function ShareCard({ run }: { run: RunInfo }) {
  const [copied, setCopied] = useState(false);
  const text = shareText(run);

  const share = async () => {
    try {
      if (navigator.share) {
        await navigator.share({ text });
        return;
      }
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* the user dismissed the share sheet */
    }
  };

  return (
    <div className="mx-auto mt-5 max-w-sm rounded-2xl border border-accent/40 bg-gradient-to-br from-accent/15 via-ink-900 to-ink-950 p-5 text-left shadow-glow">
      <p className="label text-accent">Sneak It Past</p>
      <p className="num mt-1 text-4xl font-black">{run.score.toLocaleString()}</p>
      <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs text-chalk-dim">
        <div className="rounded-lg bg-ink-950/60 p-2">
          <p className="num text-lg font-bold text-truth">{run.snuck}</p>snuck past
        </div>
        <div className="rounded-lg bg-ink-950/60 p-2">
          <p className="num text-lg font-bold text-danger">{run.caught}</p>caught
        </div>
        <div className="rounded-lg bg-ink-950/60 p-2">
          <p className="num text-lg font-bold text-accent">{run.best_streak}</p>best streak
        </div>
      </div>
      <p className="mt-3 text-xs text-chalk-faint">
        vs detector <span className="num">{run.detector_version}</span> · scores only, no headlines
      </p>
      <button type="button" onClick={() => void share()} className="btn-ghost mt-4 w-full">
        {copied ? 'Copied!' : 'Share result'}
      </button>
    </div>
  );
}
