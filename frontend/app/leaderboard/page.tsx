'use client';

import { motion } from 'framer-motion';
import Link from 'next/link';
import { useEffect, useState } from 'react';

import Nav from '@/components/Nav';
import { api, type LeaderRow } from '@/lib/api';
import { readPlayer } from '@/lib/player';

const MEDAL = ['🥇', '🥈', '🥉'];

export default function LeaderboardPage() {
  const [period, setPeriod] = useState<'today' | 'all'>('today');
  const [rows, setRows] = useState<LeaderRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const me = typeof window !== 'undefined' ? readPlayer() : null;

  useEffect(() => {
    setRows(null);
    api
      .leaderboard(period)
      .then((d) => setRows(d.rows))
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, [period]);

  return (
    <>
      <Nav />
      <main className="mx-auto w-full max-w-3xl px-4 pb-20 pt-8">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="label">Standings</p>
            <h1 className="mt-1 text-3xl font-black sm:text-4xl">Leaderboard</h1>
          </div>
          <div className="flex gap-1 rounded-xl border border-ink-700 bg-ink-900/70 p-1">
            {(['today', 'all'] as const).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setPeriod(p)}
                className={`rounded-lg px-3 py-1.5 text-sm transition ${
                  period === p
                    ? 'bg-you font-semibold text-ink-950'
                    : 'text-chalk-dim hover:text-chalk'
                }`}
              >
                {p === 'today' ? 'Today' : 'All time'}
              </button>
            ))}
          </div>
        </div>

        <div className="panel mt-6 overflow-hidden">
          {error && <p className="p-6 text-sm text-danger">{error}</p>}
          {!rows && !error && (
            <p className="animate-pulse p-6 text-sm text-chalk-dim">Loading…</p>
          )}
          {rows?.length === 0 && (
            <div className="p-8 text-center">
              <p className="text-sm text-chalk-dim">Nobody has played yet.</p>
              <Link href="/" className="btn-primary mt-4">
                Be the first
              </Link>
            </div>
          )}

          {rows && rows.length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ink-800 text-left">
                  <th className="label px-4 py-3 font-semibold">#</th>
                  <th className="label px-2 py-3 font-semibold">Player</th>
                  <th className="label px-2 py-3 text-right font-semibold">Score</th>
                  <th className="label hidden px-2 py-3 text-right font-semibold sm:table-cell">
                    Rounds
                  </th>
                  <th className="label px-4 py-3 text-right font-semibold">Avg</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const isMe = me?.player_id === r.player_id;
                  return (
                    <motion.tr
                      key={r.player_id}
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: Math.min(i * 0.025, 0.5) }}
                      className={`border-b border-ink-800/60 last:border-0 ${
                        isMe ? 'bg-you/[0.07]' : ''
                      }`}
                    >
                      <td className="num px-4 py-3 text-chalk-dim">
                        {MEDAL[r.rank - 1] ?? r.rank}
                      </td>
                      <td className="max-w-[1px] truncate px-2 py-3 font-medium">
                        {r.name}
                        {isMe && <span className="ml-2 text-xs text-you">you</span>}
                        {r.is_bot && (
                          <span className="ml-2 text-[10px] uppercase tracking-wider text-chalk-faint">
                            sim
                          </span>
                        )}
                      </td>
                      <td className="num px-2 py-3 text-right font-bold">
                        {r.score.toLocaleString()}
                      </td>
                      <td className="num hidden px-2 py-3 text-right text-chalk-dim sm:table-cell">
                        {r.rounds}
                      </td>
                      <td className="num px-4 py-3 text-right text-chalk-dim">{r.avg}</td>
                    </motion.tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <p className="mt-4 text-xs text-chalk-faint">
          Rows marked <span className="uppercase tracking-wider">sim</span> are simulated
          players from the demo seed script, kept visible so the numbers are not
          mistaken for a real crowd.
        </p>
      </main>
    </>
  );
}
