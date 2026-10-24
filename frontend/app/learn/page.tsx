'use client';

/**
 * "How it learns": the learning loop, step by step, with live numbers from
 * this game's own data at every stage, the model versions, and what the
 * fact-checker has (and hasn't yet) learned. Plain-language, for players and
 * for judges.
 */

import Link from 'next/link';
import { useEffect, useState } from 'react';

import Nav from '@/components/Nav';
import Scorecard from '@/components/Scorecard';
import { analyticsApi, learningApi, versionsApi, type Analytics, type LearningSummary, type ModelVersion } from '@/lib/api';
import { pct } from '@/lib/viz';

function Step({
  n,
  title,
  stat,
  statLabel,
  children,
}: {
  n: number;
  title: string;
  stat?: string | number;
  statLabel?: string;
  children: React.ReactNode;
}) {
  return (
    <li className="panel relative p-4 sm:p-5">
      <div className="flex items-start gap-4">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent text-sm font-black text-ink-950">
          {n}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-lg font-bold">{title}</h3>
            {stat !== undefined && (
              <p className="text-right">
                <span className="num text-2xl font-black text-accent">{stat}</span>
                {statLabel && <span className="ml-1.5 text-xs text-chalk-dim">{statLabel}</span>}
              </p>
            )}
          </div>
          <div className="mt-1.5 space-y-2 text-sm leading-relaxed text-chalk-dim">{children}</div>
        </div>
      </div>
    </li>
  );
}

function Bar({ value, label }: { value: number; label: string }) {
  return (
    <div>
      <div className="flex justify-between text-xs text-chalk-dim">
        <span>{label}</span>
        <span className="num">{pct(value)}</span>
      </div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-ink-800">
        <div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(100, value * 100)}%` }} />
      </div>
    </div>
  );
}

function VersionList({ versions }: { versions: ModelVersion[] }) {
  return (
    <ul className="mt-2 space-y-1.5">
      {versions.map((v) => (
        <li key={v.name} className="flex flex-wrap items-baseline gap-2 rounded-lg bg-ink-950/50 px-3 py-2">
          <span className="num font-bold text-chalk">{v.name}</span>
          {v.is_current && <span className="chip border-truth/60 text-truth">live</span>}
          <span className="text-xs">{v.note}</span>
          {v.n_train > 0 && <span className="ml-auto text-xs text-chalk-faint">{v.n_train} training examples</span>}
        </li>
      ))}
    </ul>
  );
}

export default function Learn() {
  const [a, setA] = useState<Analytics | null>(null);
  const [verifiers, setVerifiers] = useState<ModelVersion[]>([]);
  const [meters, setMeters] = useState<ModelVersion[]>([]);
  const [learning, setLearning] = useState<LearningSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      Promise.all([analyticsApi.get('real'), versionsApi.verifier(), versionsApi.meter(), learningApi.get()])
        .then(([an, v, m, l]) => {
          setA(an);
          setLearning(l);
          setVerifiers(v.versions);
          setMeters(m.versions.filter((x) => x.name === 'stub' || /^v\d+$/.test(x.name)));
        })
        .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
    load();
    const id = setInterval(load, 15_000);
    return () => clearInterval(id);
  }, []);

  const r = a?.review;
  const ev = a?.evaluation;
  // Only edit types with a few lies behind them: 2/2 = "100%" says almost nothing.
  const hardest = (a?.verifier_failures ?? []).filter((f) => f.n >= 3).slice(0, 4);
  const patchedVersions = verifiers.filter((v) => v.train_data === 'human' && v.name !== 'v1-human');

  return (
    <>
      <Nav />
      <main className="mx-auto w-full max-w-3xl px-4 pb-20 pt-8">
        <p className="label">How it learns</p>
        <h1 className="mt-1 text-4xl font-black tracking-tight">Every lie you sneak past teaches the fact-checker</h1>
        <p className="mt-3 text-pretty text-chalk-dim">
          The AI here is a <strong className="text-chalk">search-backed fact-checker</strong>: it looks up news
          articles and decides whether they support a headline. It’s good at the obvious stuff. Your job is to find
          what it misreads — and every time you do, that becomes a lesson. Here’s the loop, with live numbers from
          this game.
        </p>
        {error && <p className="mt-4 text-sm text-danger">{error}</p>}

        {learning && <Scorecard data={learning} />}

        <ol className="mt-8 space-y-3">
          <Step n={1} title="You write a lie" stat={a?.totals.attempts ?? '—'} statLabel="attempts logged">
            <p>
              You change up to three words of a real headline to make it false. Everything is logged: the edit, what
              the first-glance meter said as you typed, how long you took.
            </p>
          </Step>

          <Step n={2} title="A judge checks it’s a real lie" stat={r?.judge_valid ?? '—'} statLabel="judge-valid lies">
            <p>
              An AI judge reads your edit twice, with two differently worded instructions, and both must agree it’s
              actually false. It also rejects edits that are too pedantic (“the” → “a”) or too vague (“may”,
              “reportedly”) — otherwise the fact-checker would be “learning” from lies that aren’t really lies.
            </p>
          </Step>

          <Step
            n={3}
            title="The fact-checker looks it up"
            stat={a?.totals.exploits ?? '—'}
            statLabel="lies it missed"
          >
            <p>
              It searches our corpus of scraped news articles, reads the three most relevant passages, and rules
              SUPPORTED, REFUTED or NOT ENOUGH INFO. Refuted means you’re caught. Supported means it misread the
              evidence — a genuine failure, and the most valuable thing this game collects.
            </p>
            {hardest.length > 0 && (
              <div className="space-y-2 pt-1">
                <p className="text-xs font-semibold uppercase tracking-wider text-chalk-faint">
                  What it misses most so far
                </p>
                {hardest.map((f) => (
                  <Bar key={f.edit_type} value={f.failure_rate.value ?? 0} label={`${f.edit_type} (${f.n} lies)`} />
                ))}
                <p className="text-xs text-chalk-faint">
                  Small samples so far — the <Link className="underline" href="/lab">Lab</Link> shows each with a
                  confidence interval.
                </p>
              </div>
            )}
          </Step>

          <Step
            n={4}
            title="A human double-checks it"
            stat={r ? `${r.approved}/${r.target_before_patch_day}` : '—'}
            statLabel="approved toward the first retrain"
          >
            <p>
              Before anything trains the fact-checker, a person reviews each lie it missed and approves it or throws
              it out. That keeps bad data out, and tells us how often the AI judge gets it wrong
              {r?.judge_precision != null ? ` — so far reviewers agreed with the judge ${pct(r.judge_precision)} of the time` : ''}.
            </p>
            {r && <Bar value={r.approved / r.target_before_patch_day} label="Progress to the first patch day" />}
          </Step>

          <Step
            n={5}
            title="Patch day: the fact-checker retrains"
            stat={a?.totals.patched ?? '—'}
            statLabel="of your tricks patched"
          >
            <p>
              Approved lies become training examples: each one paired with the true headline it came from, on the
              same evidence, so the model learns exactly where the line between true and false falls. A new version
              only goes live if it catches more held-out lies <em>without</em> starting to flag true headlines. When
              it catches one of your old tricks, you get a “patched” notice — time to find a new one.
            </p>
            {patchedVersions.length === 0 ? (
              <p className="text-xs text-chalk-faint">
                No patch day yet — the fact-checker is still the off-the-shelf version (v0).
              </p>
            ) : (
              <VersionList versions={patchedVersions} />
            )}
          </Step>

          <Step n={6} title="We test whether people actually teach it more">
            <p>
              The real question: is data from human players better than lies an AI could write itself? We train
              three copies of the fact-checker the same way, on the same number of examples — one on your lies, one
              on AI-written lies about the same headlines, one on a mix — and test them all on lies from headlines
              none of them saw.
            </p>
            {ev ? (
              <div className="space-y-2 pt-1">
                {['v0', 'v1-synthetic', 'v1-human', 'v1-combined'].filter((m) => ev.models[m]).map((m) => (
                  <Bar key={m} value={ev.models[m].held_out_exploits.overall.value ?? 0} label={`${m}: held-out lies caught`} />
                ))}
                <p className="text-xs text-chalk-faint">
                  {ev.dev_data ? 'Test run on unreviewed data — not a result. ' : ''}Full results with confidence
                  intervals are on the <Link className="underline" href="/lab">Lab</Link> page.
                </p>
              </div>
            ) : (
              <p className="text-xs text-chalk-faint">Not run yet — it needs approved lies first.</p>
            )}
          </Step>
        </ol>

        <section className="panel mt-8 p-4 sm:p-5">
          <h2 className="text-lg font-bold">Two AIs, two jobs</h2>
          <div className="mt-3 grid gap-3 text-sm text-chalk-dim sm:grid-cols-2">
            <div className="rounded-xl bg-ink-950/50 p-3">
              <p className="font-semibold text-chalk">The first-glance meter</p>
              <p className="mt-1">
                A small, fast model that reads your edit against the source article as you type. It’s a hint for game
                feel — it never decides anything.
              </p>
              <VersionList versions={meters} />
            </div>
            <div className="rounded-xl bg-ink-950/50 p-3">
              <p className="font-semibold text-chalk">The fact-checker</p>
              <p className="mt-1">
                A bigger model that runs on submit, searches the evidence and makes the call. This is the one that
                learns from you.
              </p>
              <VersionList versions={verifiers.filter((v) => v.train_data !== 'synthetic' && v.train_data !== 'combined')} />
            </div>
          </div>
        </section>

        <section className="mt-8 text-sm text-chalk-dim">
          <h2 className="text-lg font-bold text-chalk">The honest small print</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>It only knows the articles we’ve scraped — it isn’t searching the whole web.</li>
            <li>
              Steps 1–3 count every attempt ruled by the real AI judge (test data from the stand-in judge is left
              out); steps 4–6 use only human-approved lies. Early on, all of it is small and noisy.
            </li>
            <li>If the experiment shows human lies don’t help more than AI-written ones, we’ll say so.</li>
            <li>Everything you write is stored as labelled, made-up data and never published.</li>
          </ul>
        </section>
      </main>
    </>
  );
}
