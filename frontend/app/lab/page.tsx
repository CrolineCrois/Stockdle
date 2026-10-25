'use client';

/**
 * The analytics dashboard ("the lab"): what human tricks taught the detector.
 *
 * Every chart has a hover tooltip and a table view. Colour follows the entity
 * (see lib/viz.ts): human exploits blue, machine-made fakes orange, true
 * headlines aqua. One y-axis per chart; rates are all on the same 0-100% scale.
 */

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ErrorBar,
  LabelList,
  Line,
  LineChart,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import ChangeList from '@/components/ChangeList';
import Nav from '@/components/Nav';
import { analyticsApi, exploitsApi, type Analytics, type CI, type ExploitRow } from '@/lib/api';
import { INK, SERIES, pct } from '@/lib/viz';

const AXIS = { stroke: INK.axis, tick: { fill: INK.muted, fontSize: 12 }, tickLine: false } as const;
const GRID = { stroke: INK.grid, vertical: false } as const;
const BAR_END = [4, 4, 0, 0] as [number, number, number, number];
const BAR_END_H = [0, 4, 4, 0] as [number, number, number, number];
// Legend text stays in ink; the swatch beside it carries the series identity.
const LEGEND = {
  wrapperStyle: { fontSize: 12 },
  formatter: (value: string) => <span style={{ color: INK.secondary }}>{value}</span>,
};

function TipBox({ active, payload, label, format }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-ink-600 bg-ink-950/95 px-3 py-2 text-xs shadow-panel">
      <p className="font-semibold text-chalk">{label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} className="mt-1 flex items-center gap-2 text-chalk-dim">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: p.color }} aria-hidden />
          {p.name}: <span className="num text-chalk">{format ? format(p.value) : p.value}</span>
        </p>
      ))}
    </div>
  );
}

function Panel({
  kicker,
  title,
  caption,
  table,
  children,
  wide = false,
}: {
  kicker: string;
  title: string;
  caption: string;
  table: React.ReactNode;
  children: React.ReactNode;
  wide?: boolean;
}) {
  const [showTable, setShowTable] = useState(false);
  return (
    <section className={`panel p-4 sm:p-5 ${wide ? 'lg:col-span-2' : ''}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="label">{kicker}</p>
          <h2 className="mt-1 text-lg font-bold leading-snug">{title}</h2>
        </div>
        <button type="button" className="chip shrink-0" onClick={() => setShowTable((v) => !v)}>
          {showTable ? 'Show chart' : 'Show table'}
        </button>
      </div>
      <p className="mt-1 text-sm text-chalk-dim">{caption}</p>
      <div className="mt-4">{showTable ? table : children}</div>
    </section>
  );
}

function Table({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-chalk-faint">
            {head.map((h) => (
              <th key={h} className="px-2 py-2 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-ink-800">
              {r.map((c, j) => (
                <td key={j} className={`px-2 py-2 ${j ? 'num text-chalk-dim' : 'font-semibold'}`}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Empty({ what }: { what: string }) {
  return <p className="grid h-48 place-items-center rounded-xl bg-ink-950/40 text-sm text-chalk-dim">{what}</p>;
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

const pctLabel = (v: number | null) => (v === null || v === undefined ? '' : pct(v));
const MODEL_ORDER = ['v0', 'v1-synthetic', 'v1-human', 'v1-combined'];
const ciText = (c?: CI) =>
  !c || c.value === null ? '—' : `${pct(c.value)} [${pct(c.lo)}–${pct(c.hi)}] n=${c.n}`;
/** Rows for a one-metric bar chart with 95% CI whiskers. */
const ciRows = (items: [string, CI | undefined][]) =>
  items
    .filter(([, c]) => c && c.value !== null)
    .map(([name, c]) => {
      const e = [c!.value! - (c!.lo ?? c!.value!), (c!.hi ?? c!.value!) - c!.value!];
      // No whisker for a zero-width interval (duplicate-key warning in Recharts).
      return { name, value: c!.value, err: e[0] > 0 || e[1] > 0 ? e : null, n: c!.n };
    });

function CIChart({ rows, height = 240, name }: { rows: ReturnType<typeof ciRows>; height?: number; name: string }) {
  return (
    <div style={{ height }}>
      <ResponsiveContainer>
        <BarChart data={rows} margin={{ top: 24, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="name" {...AXIS} />
          <YAxis {...AXIS} domain={[0, 1]} tickFormatter={(v: number) => pct(v)} />
          <Tooltip content={<TipBox format={pct} />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Bar name={name} dataKey="value" fill={SERIES.human} radius={BAR_END}>
            <ErrorBar dataKey="err" width={6} stroke={INK.secondary} strokeWidth={1.5} />
            <LabelList dataKey="value" position="top" offset={14} formatter={pctLabel} fill={INK.secondary} fontSize={11} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function Lab() {
  const [judge, setJudge] = useState<'all' | 'real'>('all');
  const [data, setData] = useState<Analytics | null>(null);
  const [top, setTop] = useState<ExploitRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    analyticsApi.get(judge).then(setData).catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
    exploitsApi.list(5).then((r) => setTop(r.rows)).catch(() => undefined);
  }, [judge]);

  useEffect(() => {
    load();
    const id = setInterval(load, 15_000);
    return () => clearInterval(id);
  }, [load]);


  return (
    <>
      <Nav />
      <main className="mx-auto w-full max-w-6xl px-4 pb-16 pt-8">
        <p className="label">The lab</p>
        <h1 className="mt-1 text-4xl font-black tracking-tight">Where the fact-checker fails — and what fixes it</h1>
        <p className="mt-2 max-w-3xl text-sm text-chalk-dim">
          Every win in the game is a real failure of a search-backed fact-checker. Models are compared on
          held-out exploits from headlines none of them trained on, held-out true headlines, and the
          VitaminC benchmark, each with 95% bootstrap intervals. Small or negative results are shown as they are.
        </p>

        {/* Filters: one row, above the charts. */}
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <span className="label mr-1">Attempts judged by</span>
          {(['all', 'real'] as const).map((j) => (
            <button
              key={j}
              type="button"
              onClick={() => setJudge(j)}
              className={`chip ${judge === j ? 'border-accent/60 text-accent' : ''}`}
            >
              {j === 'all' ? 'Any judge' : 'LLM judge only'}
            </button>
          ))}
          {data && data.mock_judged_attempts > 0 && (
            <span className="text-xs text-chalk-faint">
              {data.mock_judged_attempts} attempt{data.mock_judged_attempts === 1 ? ' was' : 's were'} ruled by the
              mock judge (no API key) — development data, not research data.
            </span>
          )}
        </div>
        {error && <p className="mt-4 text-sm text-danger">{error}</p>}

        {data && (
          <>
            <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <Tile label="Rounds played" value={data.totals.rounds_played} />
              <Tile label="Attempts logged" value={data.totals.attempts} />
              <Tile label="Exploits found" value={data.totals.exploits} sub="snuck past the detector" />
              <Tile label="Zero-days" value={data.totals.zero_days} sub="novel tricks" />
              <Tile label="Exploits patched" value={data.totals.patched} sub="caught by a later version" />
              <Tile label="Live detector" value={data.totals.current_detector} sub={`${data.totals.players} player${data.totals.players === 1 ? '' : 's'}`} />
            </div>

            <div className="mt-5 grid gap-4 lg:grid-cols-2">
              <Panel
                wide
                kicker="Key finding"
                title="Which kinds of lie does the fact-checker miss?"
                caption="Of the judge-approved lies of each kind, the share the evidence verifier let through (SUPPORTED or not enough info) — even with the source article retrievable. Whiskers are 95% bootstrap intervals."
                table={
                  <Table
                    head={['Edit type', 'Missed', 'Supported', 'Not enough info', 'Lies']}
                    rows={data.verifier_failures.map((r) => [r.edit_type, ciText(r.failure_rate), r.supported, r.nei, r.n])}
                  />
                }
              >
                {data.verifier_failures.length === 0 ? (
                  <Empty what="No judged lies yet." />
                ) : (
                  <CIChart name="Missed by the verifier" rows={ciRows(data.verifier_failures.map((r) => [r.edit_type, r.failure_rate]))} />
                )}
              </Panel>

              <Panel
                wide
                kicker="Main result"
                title="Does human-found data teach the verifier more than LLM-made data?"
                caption={
                  data.evaluation
                    ? `Refute recall on held-out human exploits (headlines no model trained on). Same base model, settings and training-set size for every v1. ${data.evaluation.counts.train_exploits} training exploits, ${data.evaluation.counts.test_exploits} held out${data.evaluation.dev_data ? ' — DEV RUN with unreviewed data, not a result' : ''}.`
                    : 'Run `npm run evaluate` once enough exploits are approved.'
                }
                table={
                  data.evaluation ? (
                    <Table
                      head={['Model', 'Held-out exploits caught', 'Fresh exploits caught', 'True headlines refuted', 'VitaminC macro-F1']}
                      rows={MODEL_ORDER.filter((m) => data.evaluation!.models[m]).map((m) => {
                        const x = data.evaluation!.models[m];
                        return [m, ciText(x.held_out_exploits.overall), ciText(x.fresh_exploits.overall),
                                ciText(x.true_headlines.overall), ciText(x.vitaminc.macro_f1)];
                      })}
                    />
                  ) : (
                    <Empty what="No evaluation results yet." />
                  )
                }
              >
                {!data.evaluation ? (
                  <Empty what="No evaluation results yet — approve exploits on /admin, then run npm run evaluate." />
                ) : (
                  <CIChart
                    name="Held-out exploits caught"
                    rows={ciRows(MODEL_ORDER.map((m) => [m, data.evaluation!.models[m]?.held_out_exploits.overall]))}
                  />
                )}
              </Panel>

              <Panel
                kicker="Sanity check"
                title="False positives by version"
                caption="Share of held-out TRUE headlines each model wrongly refutes. Catching more lies only counts if this doesn't jump."
                table={
                  <Table
                    head={['Model', 'True headlines refuted']}
                    rows={MODEL_ORDER.filter((m) => data.evaluation?.models[m]).map((m) => [m, ciText(data.evaluation!.models[m].true_headlines.overall)])}
                  />
                }
              >
                {!data.evaluation ? (
                  <Empty what="No evaluation results yet." />
                ) : (
                  <CIChart name="True headlines refuted" height={220}
                    rows={ciRows(MODEL_ORDER.map((m) => [m, data.evaluation!.models[m]?.true_headlines.overall]))} />
                )}
              </Panel>

              <Panel
                kicker="Generalisation"
                title="VitaminC macro-F1 by version"
                caption="A public fact-verification benchmark of minimal contrastive edits. Fine-tuning on our data should not make this worse."
                table={
                  <Table
                    head={['Model', 'Macro-F1', 'Accuracy']}
                    rows={MODEL_ORDER.filter((m) => data.evaluation?.models[m]).map((m) => [m, ciText(data.evaluation!.models[m].vitaminc.macro_f1), ciText(data.evaluation!.models[m].vitaminc.accuracy)])}
                  />
                }
              >
                {!data.evaluation ? (
                  <Empty what="No evaluation results yet." />
                ) : (
                  <CIChart name="VitaminC macro-F1" height={220}
                    rows={ciRows(MODEL_ORDER.map((m) => [m, data.evaluation!.models[m]?.vitaminc.macro_f1]))} />
                )}
              </Panel>

              <Panel
                kicker="Two modes"
                title="Evidence vs breaking-news win rates"
                caption="Share of judge-approved lies that fully snuck past. In breaking-news mode the source article is hidden from the fact-checker."
                table={<Table head={['Mode', 'Snuck', 'Partial', 'Lies', 'Win rate']} rows={data.modes.map((m) => [m.mode, m.snuck, m.partial, m.n, pct(m.win_rate)])} />}
              >
                {data.modes.every((m) => m.n === 0) ? (
                  <Empty what="No judged lies yet." />
                ) : (
                  <div className="h-56">
                    <ResponsiveContainer>
                      <BarChart data={data.modes} margin={{ top: 22, right: 8, left: -12, bottom: 0 }}>
                        <CartesianGrid {...GRID} />
                        <XAxis dataKey="mode" {...AXIS} />
                        <YAxis {...AXIS} domain={[0, 1]} tickFormatter={(v: number) => pct(v)} />
                        <Tooltip content={<TipBox format={pct} />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                        <Bar name="Win rate" dataKey="win_rate" fill={SERIES.human} radius={BAR_END}>
                          <LabelList dataKey="win_rate" position="top" formatter={pctLabel} fill={INK.secondary} fontSize={11} />
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </Panel>

              <Panel
                kicker="Data progress"
                title="Approved exploits over time"
                caption={`Toward ${data.review.target_before_patch_day} before the first patch day. Judge precision against human review: ${data.review.judge_precision === null ? 'not yet measured' : pct(data.review.judge_precision)} (${data.review.decisions_logged} decisions).`}
                table={<Table head={['Day', 'Approved (cumulative)']} rows={data.progress.map((d) => [d.day, d.total])} />}
              >
                {data.progress.length === 0 ? (
                  <Empty what="Nothing approved yet." />
                ) : (
                  <div className="h-56">
                    <ResponsiveContainer>
                      <LineChart data={data.progress} margin={{ top: 12, right: 12, left: -12, bottom: 0 }}>
                        <CartesianGrid {...GRID} />
                        <XAxis dataKey="day" {...AXIS} />
                        <YAxis {...AXIS} allowDecimals={false} />
                        <Tooltip content={<TipBox />} />
                        <Line name="Approved exploits" dataKey="total" stroke={SERIES.human} strokeWidth={2} dot={{ r: 4 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </Panel>

              <Panel
                kicker="Under pressure"
                title="Are rushed tricks sloppier?"
                caption="Success rate and average suspicion, by how much of the clock was left at submit. Both are shares of 100%."
                table={
                  <Table
                    head={['Clock left', 'Snuck past', 'Avg suspicion', 'Attempts']}
                    rows={(data.timer ?? []).map((t) => [t.bucket, pct(t.success_rate), pct(t.avg_suspicion), t.n])}
                  />
                }
              >
                {data.timer.every((t) => t.n === 0) ? (
                  <Empty what="No scored attempts yet." />
                ) : (
                  <div className="h-64">
                    <ResponsiveContainer>
                      <BarChart data={data.timer} barGap={2} margin={{ top: 22, right: 8, left: -12, bottom: 0 }}>
                        <CartesianGrid {...GRID} />
                        <XAxis dataKey="bucket" {...AXIS} />
                        <YAxis {...AXIS} domain={[0, 1]} tickFormatter={(v: number) => pct(v)} />
                        <Tooltip content={<TipBox format={pct} />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                        <Legend {...LEGEND} />
                        <Bar name="Snuck past" dataKey="success_rate" fill={SERIES.human} radius={BAR_END} />
                        <Bar name="Average suspicion" dataKey="avg_suspicion" fill={SERIES.machine} radius={BAR_END} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </Panel>

              <Panel
                kicker="How people lie"
                title="Successful exploits by kind of edit"
                caption="The judge’s label for each trick that snuck past."
                table={<Table head={['Edit type', 'Exploits']} rows={data.edit_types.map((e) => [e.edit_type, e.count])} />}
              >
                {data.edit_types.length === 0 ? (
                  <Empty what="No exploits yet." />
                ) : (
                  <div style={{ height: Math.max(140, data.edit_types.length * 40) }}>
                    <ResponsiveContainer>
                      <BarChart data={data.edit_types} layout="vertical" margin={{ top: 0, right: 28, left: 8, bottom: 0 }}>
                        <CartesianGrid stroke={INK.grid} horizontal={false} />
                        <XAxis type="number" {...AXIS} allowDecimals={false} />
                        <YAxis type="category" dataKey="edit_type" {...AXIS} width={110} />
                        <Tooltip content={<TipBox />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                        <Bar name="Exploits" dataKey="count" fill={SERIES.human} radius={BAR_END_H}>
                          <LabelList dataKey="count" position="right" fill={INK.secondary} fontSize={11} />
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </Panel>

              <Panel
                kicker="The vocabulary of lies"
                title="Most common words added in exploits"
                caption="Words players put in to make a headline false (short function words left out)."
                table={
                  <Table
                    head={['Added', 'Times', 'Removed', 'Times']}
                    rows={Array.from({ length: Math.max(data.words_added.length, data.words_removed.length) }, (_, i) => [
                      data.words_added[i]?.word ?? '',
                      data.words_added[i]?.count ?? '',
                      data.words_removed[i]?.word ?? '',
                      data.words_removed[i]?.count ?? '',
                    ])}
                  />
                }
              >
                {data.words_added.length === 0 ? (
                  <Empty what="No exploits yet." />
                ) : (
                  <div style={{ height: Math.max(140, data.words_added.length * 30) }}>
                    <ResponsiveContainer>
                      <BarChart data={data.words_added} layout="vertical" margin={{ top: 0, right: 28, left: 8, bottom: 0 }}>
                        <CartesianGrid stroke={INK.grid} horizontal={false} />
                        <XAxis type="number" {...AXIS} allowDecimals={false} />
                        <YAxis type="category" dataKey="word" {...AXIS} width={90} />
                        <Tooltip content={<TipBox />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                        <Bar name="Times added" dataKey="count" fill={SERIES.human} radius={BAR_END_H}>
                          <LabelList dataKey="count" position="right" fill={INK.secondary} fontSize={11} />
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </Panel>

              <section className="panel p-4 sm:p-5">
                <p className="label">Exploit Board</p>
                <h2 className="mt-1 text-lg font-bold">Top zero-day tricks</h2>
                <div className="mt-3 space-y-3">
                  {top.length === 0 && <p className="text-sm text-chalk-dim">No zero-days yet.</p>}
                  {top.map((x) => (
                    <div key={x.id} className="rounded-xl bg-ink-950/50 p-3 text-sm">
                      <span className="chip border-danger/60 bg-danger/10 font-bold text-danger">{x.label}</span>
                      <p className="mt-2 select-none">
                        <ChangeList changes={x.changes} />
                        <span className="text-chalk-faint">· {x.edit_type} · {x.player}</span>
                      </p>
                    </div>
                  ))}
                </div>
                <Link href="/board" className="btn-ghost mt-4">
                  Full board
                </Link>
              </section>
            </div>
          </>
        )}
      </main>
    </>
  );
}
