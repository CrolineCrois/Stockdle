'use client';

/**
 * The "science" page: what the crowd actually taught the model.
 *
 * Four questions, four forms:
 *   1. Did the blend beat either alone?        -> 3-series line over versions
 *   2. Do players improve with practice?       -> single-series bar, bucketed
 *   3. Which way are humans biased?            -> diverging bar around zero
 *   4. Do fake headlines move human drawings?  -> 2-series grouped bar
 */

import { useCallback, useEffect, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from 'recharts';

import Nav from '@/components/Nav';
import {
  AXIS,
  DataTable,
  Empty,
  GRID_PROPS,
  Panel,
  Stat,
  tooltip,
} from '@/components/charts';
import { api, type DashboardData } from '@/lib/api';
import { ACCENT, DIVERGING, SERIES } from '@/lib/palette';

const TYPE_LABEL: Record<string, string> = {
  electricity: 'Grid demand',
  stock: 'Real headline',
  trends: 'Search trends',
  fake_stock: 'Fake headline',
};

const f4 = (v: number) => v.toFixed(4);
const f3 = (v: number) => v.toFixed(3);

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .dashboard()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 12_000); // keeps the pitch screen live
    return () => clearInterval(id);
  }, [load]);

  if (error) {
    return (
      <>
        <Nav />
        <main className="mx-auto max-w-6xl px-4 py-10">
          <p className="panel p-6 text-sm text-danger">{error}</p>
        </main>
      </>
    );
  }

  if (!data) {
    return (
      <>
        <Nav />
        <main className="mx-auto max-w-6xl px-4 py-10">
          <p className="animate-pulse text-sm text-chalk-dim">Loading the numbers…</p>
        </main>
      </>
    );
  }

  const { versions, improvement, bias, headline_bias: headline, totals } = data;
  const last = versions[versions.length - 1];
  const blendWins =
    last?.blend != null && last.model != null && last.crowd != null
      ? last.blend < Math.min(last.model, last.crowd)
      : false;

  return (
    <>
      <Nav />
      <main className="mx-auto w-full max-w-6xl px-4 pb-20 pt-8">
        <p className="label">The science page</p>
        <h1 className="mt-1 text-3xl font-black sm:text-4xl">What the crowd taught it</h1>
        <p className="mt-2 max-w-2xl text-pretty text-chalk-dim">
          The forecaster is a ridge regression fit on historical windows. It never
          sees a game round in training. What players change is the{' '}
          <span className="text-chalk">blend weight</span>: how much the AI trusts its
          own model versus the average human drawing on that round. Every{' '}
          <span className="num">{totals.retrain_every}</span> drawings, that weight is
          re-fit and a new version ships.
        </p>

        {/* 4. Totals, as hero numbers. */}
        <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat
            label="Drawings collected"
            value={totals.drawings.toLocaleString()}
            sub={`${totals.rounds_with_crowd} rounds have a live crowd line`}
            accent={ACCENT}
          />
          <Stat label="Players" value={totals.players.toLocaleString()} sub="name only, no accounts" />
          <Stat
            label="AI version"
            value={`v${totals.ai_version}`}
            sub={
              totals.ai_version === 0
                ? 'no retrain yet'
                : `${totals.next_retrain_in} drawings to v${totals.ai_version + 1}`
            }
            accent={SERIES.ai}
          />
          <Stat
            label="Humans beat the AI"
            value={`${(totals.beat_ai_rate * 100).toFixed(0)}%`}
            sub={`avg score ${totals.avg_score} · ${totals.bullseyes} bullseyes`}
          />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {/* 1. The headline graph. */}
          <Panel
            wide
            kicker="Headline result"
            title="Humans + AI beat either alone"
            caption={
              versions.length
                ? `Held-out RMSE on completed rounds, lower is better.${
                    blendWins
                      ? ' The blend is currently below both the model-only and crowd-only lines.'
                      : ''
                  }`
                : 'Error of model-only, crowd-only and the blend across AI versions. Lower is better.'
            }
            table={
              <DataTable
                head={['Version', 'Model only', 'Crowd only', 'Blend', 'Rounds']}
                rows={versions.map((v) => [
                  `v${v.version}`,
                  v.model?.toFixed(4) ?? '—',
                  v.crowd?.toFixed(4) ?? '—',
                  v.blend?.toFixed(4) ?? '—',
                  v.n_eval,
                ])}
              />
            }
          >
            {versions.length < 2 ? (
              <Empty
                what={`Needs at least two AI versions. ${totals.next_retrain_in} more drawings until the next one — or run the demo seed script.`}
              />
            ) : (
              <div className="h-72 w-full">
                <ResponsiveContainer>
                  <LineChart
                    data={versions}
                    margin={{ top: 8, right: 56, bottom: 4, left: -8 }}
                  >
                    <CartesianGrid {...GRID_PROPS} />
                    <XAxis
                      dataKey="version"
                      tickFormatter={(v) => `v${v}`}
                      {...AXIS}
                    />
                    <YAxis
                      {...AXIS}
                      width={56}
                      domain={['auto', 'auto']}
                      tickFormatter={(v: number) => v.toFixed(3)}
                    />
                    {tooltip({ format: f4, labelPrefix: 'AI v' })}
                    <Legend
                      verticalAlign="top"
                      align="left"
                      height={28}
                      iconType="plainline"
                      wrapperStyle={{ fontSize: 12, color: '#94a3c4' }}
                    />
                    <Line
                      name="Model only"
                      dataKey="model"
                      stroke={SERIES.ai}
                      strokeWidth={2}
                      dot={false}
                      activeDot={{ r: 4 }}
                      connectNulls
                    />
                    <Line
                      name="Crowd only"
                      dataKey="crowd"
                      stroke={SERIES.crowd}
                      strokeWidth={2}
                      strokeDasharray="7 5"
                      dot={false}
                      activeDot={{ r: 4 }}
                      connectNulls
                    />
                    <Line
                      name="Blend (shipped)"
                      dataKey="blend"
                      stroke={SERIES.you}
                      strokeWidth={3}
                      dot={false}
                      activeDot={{ r: 5 }}
                      connectNulls
                      label={({ index, x, y, value }: any) =>
                        index === versions.length - 1 && typeof value === 'number' ? (
                          <text
                            x={x + 8}
                            y={y + 4}
                            fill={SERIES.you}
                            fontSize={11}
                            fontWeight={700}
                          >
                            {value.toFixed(3)}
                          </text>
                        ) : (
                          <g />
                        )
                      }
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>

          {/* 2. Player improvement. */}
          <Panel
            kicker="Learning curve"
            title="Do players get better?"
            caption="Average accuracy score by how many rounds that player had already drawn."
            table={
              <DataTable
                head={['Rounds played', 'Avg score', 'Drawings']}
                rows={improvement.map((b) => [b.bucket, b.avg_score, b.n])}
              />
            }
          >
            {improvement.length === 0 ? (
              <Empty what="No drawings yet." />
            ) : (
              <div className="h-64 w-full">
                <ResponsiveContainer>
                  <BarChart data={improvement} margin={{ top: 16, right: 8, bottom: 4, left: -16 }}>
                    <CartesianGrid {...GRID_PROPS} />
                    <XAxis dataKey="bucket" {...AXIS} />
                    <YAxis {...AXIS} width={44} domain={[0, 100]} />
                    {tooltip({ format: (v) => v.toFixed(1), labelPrefix: 'Rounds ' })}
                    <Bar
                      name="Avg score"
                      dataKey="avg_score"
                      fill={ACCENT}
                      radius={[4, 4, 0, 0]}
                      label={{ position: 'top', fill: '#94a3c4', fontSize: 11 }}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>

          {/* 3a. Signed bias by round type. */}
          <Panel
            kicker="Human bias"
            title="Over- or under-shooting?"
            caption="Average signed error per round type. Above zero means players drew the line too high; below means too low."
            table={
              <DataTable
                head={['Round type', 'Signed error', 'Avg RMSE', 'Drawings']}
                rows={bias.map((b) => [
                  TYPE_LABEL[b.type] ?? b.type,
                  b.avg_signed_error.toFixed(4),
                  b.avg_abs_error.toFixed(4),
                  b.n,
                ])}
              />
            }
          >
            {bias.length === 0 ? (
              <Empty what="No drawings yet." />
            ) : (
              <div className="h-64 w-full">
                <ResponsiveContainer>
                  <BarChart
                    data={bias.map((b) => ({ ...b, label: TYPE_LABEL[b.type] ?? b.type }))}
                    margin={{ top: 8, right: 8, bottom: 4, left: -8 }}
                  >
                    <CartesianGrid {...GRID_PROPS} />
                    <XAxis dataKey="label" {...AXIS} />
                    <YAxis {...AXIS} width={56} tickFormatter={(v: number) => v.toFixed(3)} />
                    {tooltip({ format: f4 })}
                    <ReferenceLine y={0} stroke={DIVERGING.midpoint} strokeWidth={1.5} />
                    <Bar name="Signed error" dataKey="avg_signed_error" radius={[3, 3, 3, 3]}>
                      {bias.map((b) => (
                        <Cell
                          key={b.type}
                          fill={b.avg_signed_error >= 0 ? DIVERGING.over : DIVERGING.under}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
                <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-chalk-dim">
                  <span className="flex items-center gap-1.5">
                    <span
                      className="h-2.5 w-2.5 rounded-sm"
                      style={{ background: DIVERGING.over }}
                      aria-hidden
                    />
                    drew too high
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span
                      className="h-2.5 w-2.5 rounded-sm"
                      style={{ background: DIVERGING.under }}
                      aria-hidden
                    />
                    drew too low
                  </span>
                </p>
              </div>
            )}
          </Panel>

          {/* 3b. The disinformation finding. */}
          <Panel
            wide
            kicker="Disinformation finding"
            title="Do fabricated headlines move human predictions?"
            caption="Average move players drew from the cut point, against the move that actually happened. A fake headline has no real information in it, so any gap is pure reaction to the words."
            table={
              <DataTable
                head={['Headline', 'Players drew', 'Actually happened', 'Overreaction', 'Avg score', 'n']}
                rows={headline.map((h) => [
                  h.label,
                  h.avg_predicted_move.toFixed(4),
                  h.avg_actual_move.toFixed(4),
                  h.overreaction.toFixed(4),
                  h.avg_score,
                  h.n,
                ])}
              />
            }
          >
            {headline.every((h) => h.n === 0) ? (
              <Empty what="No stock rounds played yet." />
            ) : (
              <>
                <div className="h-56 w-full">
                  <ResponsiveContainer>
                    <BarChart
                      data={headline}
                      margin={{ top: 16, right: 8, bottom: 4, left: -8 }}
                      barGap={6}
                    >
                      <CartesianGrid {...GRID_PROPS} />
                      <XAxis dataKey="label" {...AXIS} />
                      <YAxis {...AXIS} width={56} tickFormatter={(v: number) => v.toFixed(3)} />
                      {tooltip({ format: f4 })}
                      <Legend
                        verticalAlign="top"
                        align="left"
                        height={26}
                        wrapperStyle={{ fontSize: 12, color: '#94a3c4' }}
                      />
                      <ReferenceLine y={0} stroke={DIVERGING.midpoint} strokeWidth={1.5} />
                      <Bar
                        name="Players drew"
                        dataKey="avg_predicted_move"
                        fill={ACCENT}
                        radius={[4, 4, 0, 0]}
                      />
                      <Bar
                        name="Actually happened"
                        dataKey="avg_actual_move"
                        fill={SERIES.ai}
                        radius={[4, 4, 0, 0]}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {headline.map((h) => (
                    <p key={h.label} className="rounded-lg bg-ink-800/50 px-3 py-2 text-xs text-chalk-dim">
                      <span className="font-semibold text-chalk">{h.label}</span> ·{' '}
                      {h.n === 0 ? (
                        'no data yet'
                      ) : (
                        <>
                          overreaction{' '}
                          <span
                            className="num font-semibold"
                            style={{
                              color: Math.abs(h.overreaction) > 0.01 ? DIVERGING.over : undefined,
                            }}
                          >
                            {h.overreaction >= 0 ? '+' : ''}
                            {f3(h.overreaction)}
                          </span>{' '}
                          over {h.n} drawings
                        </>
                      )}
                    </p>
                  ))}
                </div>
              </>
            )}
          </Panel>
        </div>

        <section className="panel mt-4 p-4 sm:p-5">
          <p className="label">Current blend weights</p>
          <p className="mt-1 text-sm text-chalk-dim">
            <span className="num">w</span> is the share given to the model; the rest goes to
            the crowd. A round with fewer than three drawings falls back to the model alone.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.keys(totals.weights).length === 0 ? (
              <span className="chip">model only — no retrain yet</span>
            ) : (
              Object.entries(totals.weights).map(([k, w]) => (
                <span key={k} className="chip">
                  {TYPE_LABEL[k] ?? k}
                  <span className="num ml-1 text-chalk">
                    w={w.toFixed(2)} · crowd {(100 * (1 - w)).toFixed(0)}%
                  </span>
                </span>
              ))
            )}
          </div>
          {totals.latest_note && (
            <p className="mt-3 text-xs text-chalk-faint">Last change: {totals.latest_note}</p>
          )}
        </section>
      </main>
    </>
  );
}
