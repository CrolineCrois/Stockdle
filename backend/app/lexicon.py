"""Small word lists shared by the mock judge, the rule-based fake generator and
the stub detector. Deliberately short: these are development stand-ins, not
the real thing (that is the Claude judge and the DistilBERT detector).
"""

from __future__ import annotations

import re

NUMBER = re.compile(r"^[$£€]?\d[\d,.]*%?$|^(one|two|three|four|five|six|seven|eight|nine|ten|"
                    r"dozens?|hundreds?|thousands?|millions?|billions?|half|double|triple)$",
                    re.IGNORECASE)

NEGATIONS = {"not", "no", "never", "none", "nobody", "without", "denies", "deny", "denied",
             "rejects", "reject", "rejected", "refuses", "refused", "fails", "failed",
             "halts", "halted", "cancels", "cancelled", "canceled", "blocks", "blocked"}

# Each pair works in both directions.
ANTONYM_PAIRS = [
    ("rise", "fall"), ("rises", "falls"), ("rose", "fell"), ("up", "down"),
    ("increase", "decrease"), ("increases", "decreases"), ("higher", "lower"),
    ("win", "lose"), ("wins", "loses"), ("won", "lost"), ("gain", "loss"),
    ("approve", "reject"), ("approves", "rejects"), ("approved", "rejected"),
    ("accept", "refuse"), ("accepts", "refuses"), ("more", "fewer"), ("more", "less"),
    ("first", "last"), ("before", "after"), ("open", "close"), ("opens", "closes"),
    ("boost", "cut"), ("boosts", "cuts"), ("support", "oppose"), ("backs", "opposes"),
    ("ally", "rival"), ("allies", "rivals"), ("arrested", "released"), ("guilty", "innocent"),
    ("record", "lowest"), ("surge", "slump"), ("soars", "plunges"), ("ends", "extends"),
]
ANTONYMS: dict[str, str] = {}
for _a, _b in ANTONYM_PAIRS:
    ANTONYMS.setdefault(_a, _b)
    ANTONYMS.setdefault(_b, _a)

CAUSAL = {"because", "after", "due", "causes", "caused", "blames", "blamed", "sparks",
          "sparked", "triggers", "triggered", "leads", "led", "over", "amid", "following"}

ABSURD = {"aliens", "alien", "unicorn", "unicorns", "zombie", "zombies", "wizard", "dragons",
          "dragon", "dinosaur", "dinosaurs", "ghost", "ghosts", "telepathy", "teleport"}


def is_number(word: str) -> bool:
    return bool(NUMBER.match(word))


def is_entity(word: str) -> bool:
    """A crude proper-noun test: capitalised and not a sentence-ish function word."""
    return len(word) > 1 and word[0].isupper() and word.lower() not in {
        "the", "a", "an", "in", "on", "of", "to", "and", "for", "as", "at", "by", "with"}
