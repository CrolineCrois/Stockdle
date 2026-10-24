'use client';

/**
 * The editor: a plain text field (works with every phone keyboard), with the
 * edited headline echoed underneath and the changed words highlighted, plus a
 * word-change counter against the limit.
 */

import { useLayoutEffect, useMemo, useRef } from 'react';

import { wordDiff } from '@/lib/diff';

export default function HeadlineEditor({
  original,
  value,
  maxWords,
  disabled,
  onChange,
  onSubmit,
}: {
  original: string;
  value: string;
  maxWords: number;
  disabled: boolean;
  onChange: (v: string) => void;
  onSubmit: () => void;
}) {
  const { tokens, changes } = useMemo(() => wordDiff(original, value), [original, value]);
  const over = changes > maxWords;
  const box = useRef<HTMLTextAreaElement>(null);

  // Grow to fit: long headlines wrap to three or four lines on a phone.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  return (
    <div>
      <label htmlFor="edit" className="label">
        Your version
      </label>
      <textarea
        id="edit"
        ref={box}
        value={value}
        disabled={disabled}
        rows={2}
        maxLength={300}
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
        onChange={(e) => onChange(e.target.value.replace(/\n/g, ' '))}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            onSubmit();
          }
        }}
        className="mt-2 w-full resize-none rounded-xl border border-ink-700 bg-ink-950/70 px-4 py-3 text-lg font-semibold leading-snug outline-none transition focus:border-accent/60 disabled:opacity-60"
      />
      <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
        <p className="min-w-0 flex-1 text-sm leading-relaxed text-chalk-dim">
          {tokens.map((t, i) => (
            <span key={i} className={t.changed ? 'rounded bg-accent/20 px-0.5 font-semibold text-accent' : ''}>
              {t.word}{' '}
            </span>
          ))}
        </p>
        <span className={`chip ${over ? 'border-danger/60 text-danger' : changes > 0 ? 'text-chalk' : ''}`}>
          {changes}/{maxWords} words changed
        </span>
      </div>
    </div>
  );
}
