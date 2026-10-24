"""Rule-based false variants of true headlines, 1-3 word changes each.

Only the phase-1 stub detector trains on these. The real v0 detector trains on
LLM-made fakes (phase 2), and later versions on judge-verified human exploits.
"""

from __future__ import annotations

import random
import re

from app.lexicon import ANTONYMS, NEGATIONS, is_entity, is_number

AUXILIARIES = {"is", "are", "was", "were", "will", "has", "have", "had", "can", "could",
               "would", "should", "may", "must"}


def _bump_number(word: str, rng: random.Random) -> str | None:
    m = re.search(r"\d+(?:[.,]\d+)?", word)
    if not m:
        return None
    raw = m.group(0).replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    new = value * rng.choice([2, 3, 0.5, 10]) if value > 3 else value + rng.choice([2, 5, 10])
    text = f"{new:,.0f}" if "." not in raw else f"{new:.1f}"
    return word[:m.start()] + text + word[m.end():]


def make_fakes(text: str, entity_pool: list[str], rng: random.Random,
               max_fakes: int = 2) -> list[tuple[str, str]]:
    """Return up to ``max_fakes`` (fake_headline, edit_type) pairs."""
    words = text.split()
    options: list[tuple[str, str]] = []

    for i, w in enumerate(words):
        core = w.strip(".,:;'\"").lower()
        if is_number(w.strip(".,:;'\"")):
            new = _bump_number(w, rng)
            if new and new != w:
                options.append((" ".join(words[:i] + [new] + words[i + 1:]), "number change"))
        if core in ANTONYMS:
            swapped = w.lower().replace(core, ANTONYMS[core])
            if w[0].isupper():
                swapped = swapped[0].upper() + swapped[1:]
            options.append((" ".join(words[:i] + [swapped] + words[i + 1:]), "negation"))
        if core in AUXILIARIES and i + 1 < len(words) and words[i + 1].lower() != "not":
            options.append((" ".join(words[:i + 1] + ["not"] + words[i + 1:]), "negation"))
        if core in NEGATIONS and core in {"not", "no", "never"}:
            options.append((" ".join(words[:i] + words[i + 1:]), "negation"))
        if i > 0 and is_entity(w) and entity_pool:
            other = rng.choice(entity_pool)
            if other.lower() != core:
                tail = w[len(w.rstrip(".,:;'\"")):]
                options.append((" ".join(words[:i] + [other + tail] + words[i + 1:]),
                                 "entity swap"))

    rng.shuffle(options)
    seen, out = {text}, []
    for fake, kind in options:
        if fake not in seen:
            seen.add(fake)
            out.append((fake, kind))
        if len(out) >= max_fakes:
            break
    return out


def entity_pool(headlines: list[str]) -> list[str]:
    pool = {w.strip(".,:;'\"") for h in headlines for w in h.split()[1:]
            if is_entity(w.strip(".,:;'\"")) and w.strip(".,:;'\"").isalpha()}
    return sorted(pool)
