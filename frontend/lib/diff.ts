/**
 * Word-level diff, mirroring backend/app/diffing.py closely enough for instant
 * on-screen highlighting. The server's count is the one that is enforced.
 */

export interface Token {
  word: string;
  changed: boolean;
}

const EDGE = /^[^\w$£€%]+|[^\w$£€%]+$/g;
export const norm = (w: string) => w.replace(EDGE, '').toLowerCase();
const words = (s: string) => s.split(/\s+/).filter(Boolean);

/** Longest-common-subsequence table over normalised words. */
function lcs(a: string[], b: string[]): number[][] {
  const t = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i -= 1)
    for (let j = b.length - 1; j >= 0; j -= 1)
      t[i][j] = a[i] === b[j] ? t[i + 1][j + 1] + 1 : Math.max(t[i + 1][j], t[i][j + 1]);
  return t;
}

/** The edited headline as tokens, with changed words marked, plus the change count. */
export function wordDiff(original: string, edited: string): { tokens: Token[]; changes: number } {
  const a = words(original);
  const b = words(edited);
  const na = a.map(norm);
  const nb = b.map(norm);
  const t = lcs(na, nb);
  const tokens: Token[] = [];
  let removed = 0;
  let added = 0;
  let changes = 0;
  const flush = () => {
    changes += Math.max(removed, added);
    removed = 0;
    added = 0;
  };
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && na[i] === nb[j]) {
      flush();
      tokens.push({ word: b[j], changed: false });
      i += 1;
      j += 1;
    } else if (j < b.length && (i >= a.length || t[i][j + 1] >= t[i + 1][j])) {
      if (nb[j]) added += 1;
      tokens.push({ word: b[j], changed: Boolean(nb[j]) });
      j += 1;
    } else {
      if (na[i]) removed += 1;
      i += 1;
    }
  }
  flush();
  return { tokens, changes };
}
