'use client';

import { useEffect, useState } from 'react';

import Nav from '@/components/Nav';
import { api, type LeaderRow } from '@/lib/api';

export default function Leaderboard() {
  const [rows, setRows] = useState<LeaderRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      api
        .leaderboard()
        .then((r) => setRows(r.rows))
        .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
    load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, []);

  return (
    <>
      <Nav />
      <main className="mx-auto w-full max-w-3xl px-4 pb-16 pt-8">
        <p className="label">Best runs</p>
        <h1 className="mt-1 text-4xl font-black tracking-tight">Leaderboard</h1>
        {error && <p className="mt-4 text-sm text-danger">{error}</p>}
        <div className="panel mt-6 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-chalk-faint">
                <th className="px-4 py-3 font-medium">#</th>
                <th className="px-4 py-3 font-medium">Player</th>
                <th className="px-4 py-3 text-right font-medium">Score</th>
                <th className="px-4 py-3 text-right font-medium">Snuck</th>
                <th className="px-4 py-3 text-right font-medium">Streak</th>
                <th className="px-4 py-3 text-right font-medium">Detector</th>
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
                  <td className="num px-4 py-3 text-right text-chalk-dim">{r.detector_version}</td>
                </tr>
              ))}
              {rows?.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-chalk-dim">
                    No runs yet. Be the first to sneak one past.
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
