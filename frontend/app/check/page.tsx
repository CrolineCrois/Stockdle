'use client';

/**
 * Check a post: paste the text of a post or headline, get each factual claim
 * checked against news evidence. Verdicts are about claims and evidence, never
 * about the post or its author. Nothing is stored unless the person sends
 * feedback.
 */

import { useState } from 'react';

import Nav from '@/components/Nav';
import { checkApi, type CheckClaim, type CheckFeedback, type CheckResult } from '@/lib/api';
import { readPlayer } from '@/lib/player';

const VERDICT: Record<CheckClaim['verdict'], { label: string; tone: string; blurb: string }> = {
  refuted: {
    label: 'Evidence contradicts this',
    tone: 'border-danger/60 bg-danger/10 text-danger',
    blurb: 'At least one news passage says something different.',
  },
  supported: {
    label: 'Evidence supports this',
    tone: 'border-truth/60 bg-truth/10 text-truth',
    blurb: 'A news passage says the same thing.',
  },
  nei: {
    label: 'Not enough evidence',
    tone: 'border-ink-600 bg-ink-800/40 text-chalk-dim',
    blurb: 'Nothing found settles it either way. That is not the same as false.',
  },
};

const SECOND: Record<string, string> = { refuted: 'contradicted', supported: 'supported', nei: 'not enough evidence' };

const EXAMPLE =
  'BREAKING: Police arrested over 500 protesters in Paris today as marches spread across France. Honestly the government should be ashamed.';

const FEEDBACK: [CheckFeedback, string][] = [
  ['right', 'Looks right'],
  ['wrong_true', 'Wrong — it’s actually true'],
  ['wrong_false', 'Wrong — it’s actually false'],
  ['unsure', 'Not sure'],
];

function ClaimCard({ c }: { c: CheckClaim }) {
  const v = VERDICT[c.verdict];
  return (
    <article className="panel p-4 sm:p-5">
      <p className="text-xs font-semibold uppercase tracking-wider text-chalk-faint">Claim</p>
      <p className="mt-1 text-lg font-semibold leading-snug">{c.claim}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className={`chip font-bold ${v.tone}`}>{v.label}</span>
        <span className="text-xs text-chalk-dim">{v.blurb}</span>
      </div>
      {c.trained_model && c.trained_verdict && (
        <p className="mt-2 text-xs text-chalk-faint">
          Second opinion from <span className="num">{c.trained_model}</span> (trained on player lies):{' '}
          {SECOND[c.trained_verdict] ?? c.trained_verdict}
        </p>
      )}
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-chalk-dim">Evidence it read ({c.passages.length})</summary>
        <ul className="mt-2 space-y-2">
          {c.passages.map((p, i) => (
            <li
              key={i}
              className={`rounded-lg border p-2 ${p.decisive ? 'border-accent/50' : 'border-ink-700'} ${
                p.on_topic ? 'text-chalk-dim' : 'text-chalk-faint opacity-70'
              }`}
            >
              <p>{p.text}</p>
              <p className="mt-1 flex flex-wrap gap-x-2 text-[11px] text-chalk-faint">
                <span>{p.source || 'news'}</span>
                <span>· {p.kind === 'fresh' ? 'fresh from Google News' : 'from the game’s articles'}</span>
                <span className="num">
                  · supports {Math.round((p.probs.supported ?? 0) * 100)}% · contradicts{' '}
                  {Math.round((p.probs.refuted ?? 0) * 100)}%
                </span>
                {p.decisive && <span className="text-accent">· deciding passage</span>}
                {!p.on_topic && <span>· different story — not used</span>}
                {p.url && (
                  <a href={p.url} target="_blank" rel="noreferrer noopener" className="underline">
                    open
                  </a>
                )}
              </p>
            </li>
          ))}
        </ul>
      </details>
    </article>
  );
}

export default function CheckPage() {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CheckResult | null>(null);
  const [checkedText, setCheckedText] = useState('');
  const [sent, setSent] = useState<CheckFeedback | null>(null);

  const run = async () => {
    const t = text.trim();
    if (t.length < 10) {
      setError('Paste a little more text — at least one full sentence.');
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    setSent(null);
    try {
      setResult(await checkApi.check(t));
      setCheckedText(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not check that.');
    } finally {
      setBusy(false);
    }
  };

  const feedback = async (f: CheckFeedback) => {
    if (!result) return;
    try {
      await checkApi.feedback(checkedText, result, f, '', readPlayer()?.player_id);
      setSent(f);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not send feedback.');
    }
  };

  return (
    <>
      <Nav />
      <main className="mx-auto w-full max-w-3xl space-y-4 px-4 pb-16 pt-8">
        <div>
          <p className="label">Check a post</p>
          <h1 className="mt-1 text-3xl font-black tracking-tight">Is this claim backed by the news?</h1>
          <p className="mt-2 text-sm text-chalk-dim">
            Paste the text of a post, a tweet or a headline. The checker pulls out its factual claims, searches news
            coverage, and says whether the evidence supports or contradicts each one. It judges claims, not people,
            and it can be wrong — read the evidence.
          </p>
        </div>

        <section className="panel space-y-3 p-4 sm:p-5">
          <label htmlFor="post-text" className="text-xs font-semibold uppercase tracking-wider text-chalk-faint">
            Post text
          </label>
          <textarea
            id="post-text"
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, 1200))}
            rows={5}
            placeholder="Paste the text here (not a link — links aren't fetched)."
            className="w-full rounded-lg border border-ink-700 bg-ink-950/70 px-3 py-2 text-sm text-chalk outline-none focus:border-accent/60"
          />
          <div className="flex flex-wrap items-center gap-3">
            <button type="button" className="btn-primary" disabled={busy} onClick={() => void run()}>
              {busy ? 'Checking…' : 'Check it'}
            </button>
            <button type="button" className="btn-ghost" disabled={busy} onClick={() => setText(EXAMPLE)}>
              Try an example
            </button>
            <span className="num ml-auto text-xs text-chalk-faint">{text.length}/1200</span>
          </div>
          <p className="text-xs text-chalk-faint">
            Not stored: your text is checked and forgotten, unless you send feedback below.
          </p>
          {error && <p className="text-sm text-danger">{error}</p>}
        </section>

        {busy && <p className="text-center text-sm text-chalk-dim">Pulling out claims and searching the news…</p>}

        {result && (
          <>
            {result.claims.length === 0 && (
              <p className="panel p-5 text-sm text-chalk-dim">
                No checkable factual claims found. {result.note}
              </p>
            )}
            {result.claims.map((c, i) => (
              <ClaimCard key={i} c={c} />
            ))}
            {result.claims.length > 0 && result.note && (
              <p className="text-xs text-chalk-faint">{result.note}</p>
            )}
            <p className="text-xs text-chalk-faint">
              Verdicts from <span className="num">{result.model}</span>, the general-purpose fact-checker.
              {result.fresh ? ' Evidence includes fresh Google News headlines.' : ''}
            </p>

            <section className="panel p-4 sm:p-5">
              <p className="font-semibold">Did it get this right?</p>
              <p className="mt-1 text-xs text-chalk-dim">
                Sending feedback stores this text and the result so we can improve the checker.
              </p>
              {sent ? (
                <p className="mt-3 text-sm text-truth">Thanks — saved.</p>
              ) : (
                <div className="mt-3 flex flex-wrap gap-2">
                  {FEEDBACK.map(([f, label]) => (
                    <button key={f} type="button" className="chip" onClick={() => void feedback(f)}>
                      {label}
                    </button>
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </>
  );
}
