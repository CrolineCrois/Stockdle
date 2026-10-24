'use client';

/**
 * Admin review: approve or reject each exploit before it trains or evaluates
 * a verifier. Token-guarded (SIP_ADMIN_TOKEN). Shows the player-made fake in
 * full, because reviewers must read it -- always under the FAKE label.
 */

import { useCallback, useEffect, useState } from 'react';

import Nav from '@/components/Nav';
import { adminApi, type ReviewItem, type ReviewStats } from '@/lib/api';

const KEY = 'sip.admin';

function load(): { token: string; reviewer: string } {
  try {
    return JSON.parse(window.sessionStorage.getItem(KEY) ?? '') as { token: string; reviewer: string };
  } catch {
    return { token: '', reviewer: '' };
  }
}

function Tile({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="panel p-4">
      <p className="label">{label}</p>
      <p className="mt-1 text-3xl font-black tracking-tight">{value}</p>
      {sub && <p className="mt-1 text-xs text-chalk-dim">{sub}</p>}
    </div>
  );
}

export default function Admin() {
  const [token, setToken] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [status, setStatus] = useState('pending');
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [label, setLabel] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  useEffect(() => {
    const saved = load();
    setToken(saved.token);
    setReviewer(saved.reviewer);
  }, []);

  const refresh = useCallback(() => {
    if (!token) return;
    adminApi
      .queue(token, status)
      .then((r) => {
        setItems(r.items);
        setStats(r.stats);
        setLabel(r.label);
        setError(null);
        try {
          window.sessionStorage.setItem(KEY, JSON.stringify({ token, reviewer }));
        } catch {
          /* private mode */
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, [token, reviewer, status]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const decide = async (id: number, decision: 'approved' | 'rejected') => {
    if (!reviewer.trim()) {
      setError('Enter your reviewer name first — every decision is logged with it.');
      return;
    }
    setBusy(id);
    try {
      const r = await adminApi.decide(token, id, decision, reviewer.trim());
      setStats(r.stats);
      setItems((xs) => (status === 'all' ? xs.map((x) => (x.id === id ? { ...x, review_status: decision } : x)) : xs.filter((x) => x.id !== id)));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
    } finally {
      setBusy(null);
    }
  };

  const progress = stats ? Math.min(1, stats.approved / stats.target_before_patch_day) : 0;

  return (
    <>
      <Nav />
      <main className="mx-auto w-full max-w-5xl px-4 pb-16 pt-8">
        <p className="label">Admin</p>
        <h1 className="mt-1 text-4xl font-black tracking-tight">Exploit review</h1>
        <p className="mt-2 max-w-3xl text-sm text-chalk-dim">
          Only approved exploits train or evaluate a verifier. Approve if the edit is a real,
          meaningful lie the judge was right to accept; reject if it is pedantic, vague, actually
          true, or nonsense.
        </p>

        <div className="mt-5 flex flex-wrap items-end gap-3">
          <label className="text-xs text-chalk-dim">
            Admin token
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              className="mt-1 block rounded-lg border border-ink-700 bg-ink-950/70 px-3 py-2 text-sm text-chalk outline-none focus:border-accent/60"
            />
          </label>
          <label className="text-xs text-chalk-dim">
            Reviewer
            <input
              value={reviewer}
              maxLength={40}
              onChange={(e) => setReviewer(e.target.value)}
              className="mt-1 block rounded-lg border border-ink-700 bg-ink-950/70 px-3 py-2 text-sm text-chalk outline-none focus:border-accent/60"
            />
          </label>
          <div className="flex gap-2">
            {['pending', 'approved', 'rejected', 'all'].map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setStatus(s)}
                className={`chip ${status === s ? 'border-accent/60 text-accent' : ''}`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        {error && <p className="mt-3 text-sm text-danger">{error}</p>}

        {stats && (
          <>
            <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <Tile label="Attempts" value={stats.attempts} />
              <Tile label="Judge-valid" value={stats.judge_valid} sub="real lies, any outcome" />
              <Tile label="Exploits" value={stats.exploits} sub="snuck or partial" />
              <Tile label="Pending" value={stats.pending} />
              <Tile label="Approved" value={stats.approved} sub={`target ${stats.target_before_patch_day}`} />
              <Tile
                label="Judge precision"
                value={stats.judge_precision === null ? '—' : `${Math.round(stats.judge_precision * 100)}%`}
                sub={`${stats.decisions_logged} decisions logged`}
              />
            </div>
            <div className="panel mt-3 p-4">
              <div className="flex justify-between text-xs text-chalk-dim">
                <span>Approved exploits toward the first patch day</span>
                <span className="num">
                  {stats.approved}/{stats.target_before_patch_day}
                </span>
              </div>
              <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-ink-800">
                <div className="h-full rounded-full bg-accent" style={{ width: `${progress * 100}%` }} />
              </div>
              {stats.by_edit_type.length > 0 && (
                <table className="mt-4 w-full text-sm">
                  <thead>
                    <tr className="text-left text-chalk-faint">
                      <th className="py-1 font-medium">Edit type</th>
                      <th className="py-1 text-right font-medium">Exploits</th>
                      <th className="py-1 text-right font-medium">Approved</th>
                      <th className="py-1 text-right font-medium">Rejected</th>
                      <th className="py-1 text-right font-medium">Pending</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.by_edit_type.map((r) => (
                      <tr key={r.edit_type} className="border-t border-ink-800">
                        <td className="py-1.5 font-semibold">{r.edit_type}</td>
                        <td className="num py-1.5 text-right">{r.exploits}</td>
                        <td className="num py-1.5 text-right">{r.approved ?? 0}</td>
                        <td className="num py-1.5 text-right">{r.rejected ?? 0}</td>
                        <td className="num py-1.5 text-right">{r.pending ?? 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}

        <div className="mt-6 space-y-4">
          {token && stats && items.length === 0 && (
            <p className="panel p-5 text-sm text-chalk-dim">Nothing {status === 'all' ? 'yet' : status}.</p>
          )}
          {items.map((x) => (
            <article key={x.id} className="panel p-4 sm:p-5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="chip border-danger/60 bg-danger/10 font-bold text-danger">{label}</span>
                <span className="chip">{x.outcome}</span>
                <span className="chip">{x.mode}</span>
                <span className="chip">{x.edit_type}</span>
                <span className="chip">
                  materiality {x.materiality ?? '—'} · specificity {x.original_specificity ?? '—'}→{x.specificity ?? '—'}
                </span>
                {x.review_status && x.review_status !== 'pending' && (
                  <span className="chip border-accent/60 text-accent">
                    {x.review_status} by {x.reviewer_id}
                  </span>
                )}
              </div>
              <p className="mt-3 text-sm text-chalk-faint">{x.original}</p>
              <p className="mt-1 font-semibold">{x.edited}</p>
              {x.vagueness_flags.length > 0 && (
                <p className="mt-1 text-xs text-danger">vague: {x.vagueness_flags.join('; ')}</p>
              )}
              <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                {x.judge_runs.map((r) => (
                  <div key={r.phrasing} className="rounded-lg bg-ink-950/60 p-3">
                    <p className="label">
                      Judge {x.judge} · phrasing {r.phrasing}
                    </p>
                    <p className="mt-1 text-chalk-dim">{r.explanation}</p>
                  </div>
                ))}
              </div>
              <details className="mt-3 text-sm">
                <summary className="cursor-pointer text-chalk-dim">
                  Verifier {x.verifier.version}: {x.verifier.verdict || '—'} · evidence ({x.evidence.length})
                </summary>
                <ul className="mt-2 space-y-2">
                  {x.evidence.map((e, i) => (
                    <li key={i} className="rounded-lg border border-ink-700 p-2 text-chalk-dim">
                      {e.text}
                      <span className="mt-1 block text-[11px] text-chalk-faint">
                        {e.source}
                        {e.same_story ? ' · same story' : ''}
                      </span>
                    </li>
                  ))}
                </ul>
              </details>
              <div className="mt-4 flex gap-3">
                <button type="button" className="btn-primary" disabled={busy === x.id} onClick={() => void decide(x.id, 'approved')}>
                  Approve
                </button>
                <button type="button" className="btn-ghost" disabled={busy === x.id} onClick={() => void decide(x.id, 'rejected')}>
                  Reject
                </button>
              </div>
            </article>
          ))}
        </div>
      </main>
    </>
  );
}
