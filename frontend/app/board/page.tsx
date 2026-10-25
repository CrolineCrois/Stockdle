'use client';

/**
 * The Exploit Board (novel tricks that got past the detector) and the best runs.
 *
 * Exploits are player-made fakes: each is shown struck through against the
 * original, under a "FAKE — made in Sneak It Past" label, and is never offered
 * for copying or sharing.
 */

import { useEffect, useState } from 'react';

import ChangeList from '@/components/ChangeList';
import Nav from '@/components/Nav';
import { api, exploitsApi, type ExploitRow, type LeaderRow } from '@/lib/api';

export default function Board() {
  const [exploits, setExploits] = useState<ExploitRow[] | null>(null);
  const [rows, setRows] = useState<LeaderRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      Promise.all([exploitsApi.list(12), api.leaderboard()])
        .then(([e, l]) => {
          setExploits(e.rows);
          setRows(l.rows);
        })
        .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
    load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, []);

  return (
    <>
      <Nav />
      <main className="mx-auto w-full max-w-3xl px-4 pb-16 pt-8">
        <p className="label">Zero-day exploits</p>
        <h1 className="mt-1 text-4xl font-black tracking-tight">Exploit Board</h1>
        <p className="mt-2 text-sm text-chalk-dim">
          Tricks unlike any that came before them, which slipped past the fact-checker. Exploits against
          the newest version come first; older levels follow. Each one is training data for the next patch day.
        </p>
        {error && <p className="mt-4 text-sm text-danger">{error}</p>}

        <div className="mt-5 space-y-3">
          {exploits?.length === 0 && (
            <p className="panel p-5 text-sm text-chalk-dim">No zero-days yet. Find the first one.</p>
          )}
          {exploits?.map((x) => (
            <article key={x.id} className="panel p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="chip border-danger/60 bg-danger/10 font-bold text-danger">{x.label}</span>
                {x.level && (
                  <span className={`chip num ${x.newest ? 'border-accent/50 text-accent' : ''}`}>
                    vs {x.level}
                    {x.newest ? ' · newest' : ''}
                  </span>
                )}
                <span className="chip">{x.edit_type || 'other'}</span>
                {x.patched_in ? (
                  <span className="chip border-truth/50 text-truth">patched in {x.patched_in}</span>
                ) : (
                  <span className="chip border-accent/50 text-accent">unpatched</span>
                )}
              </div>
              <p className="mt-3 text-sm text-chalk-faint line-through decoration-chalk-faint/60">{x.original}</p>
              <p className="mt-1 select-none font-semibold text-chalk">
                <ChangeList changes={x.changes} />
              </p>
              <p className="mt-2 text-xs text-chalk-dim">
                <span className="font-semibold text-chalk">{x.player}</span> ·{' '}
                <span className="num">{x.points.toLocaleString()}</span> pts · first glance{' '}
                <span className="num">{Math.round((x.suspicion ?? 0) * 100)}%</span> suspicious
              </p>
            </article>
          ))}
        </div>

        <h2 className="mt-10 text-2xl font-black tracking-tight">Best runs</h2>
        <div className="panel mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-chalk-faint">
                <th className="px-4 py-3 font-medium">#</th>
                <th className="px-4 py-3 font-medium">Player</th>
                <th className="px-4 py-3 text-right font-medium">Score</th>
                <th className="px-4 py-3 text-right font-medium">Snuck</th>
                <th className="px-4 py-3 text-right font-medium">Streak</th>
                <th className="px-4 py-3 text-right font-medium">Level</th>
              </tr>
            </thead>
            <tbody>
              {rows?.map((r) => (
                <tr key={r.rank} className="border-t border-ink-800">
                  <td className="px-4 py-3 text-chalk-faint">{r.rank}</td>
                  <td className="px-4 py-3 font-semibold">{r.name}</td>
                  <td className="num px-4 py-3 text-right text-accent">{r.score.toLocaleString()}</td>
                  <td className="num px-4 py-3 text-right">{r.snuck}</td>
                  <td className="num px-4 py-3 text-right">{r.best_streak}</td>
                  <td className="num px-4 py-3 text-right text-chalk-dim">{r.level ?? r.detector_version}</td>
                </tr>
              ))}
              {rows?.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-chalk-dim">
                    No runs yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </main>
    </>
  );
}
