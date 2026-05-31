"""Wispr-style text cleanup for transcripts (offline, pure-Python).

Whisper already returns punctuated, capitalized text, so the live path uses
``polish_whisper()`` — the light touch Whisper does NOT do itself: filler-word
removal ("um/uh") and backtrack self-corrections ("scratch that", "2 actually
3"), plus spacing/casing tidy-up.

The heavier helpers (``smart_format``, spoken-punctuation, numbered-list and
truecasing functions) date from the earlier raw-CTC pipeline that produced
lowercase, unpunctuated text. They're kept for the ``--file`` path and unit
tests, and as a deterministic fallback, but the tray app runs ``polish_whisper``.

Everything here is plain string work — no model, no network, nothing leaves the
machine.
"""

from __future__ import annotations

import re
from typing import Callable

# ── Filler words removed wholesale ───────────────────────────────
_FILLERS = {"um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "hmm", "mhm", "mm"}
_FILLER_RE = re.compile(r"\b(?:" + "|".join(_FILLERS) + r")\b", re.IGNORECASE)

# ── Backtrack: "scratch that" / "delete that" retracts what was just said ──
# Sentence-scoped, mirroring how Wispr behaves:
#   - trigger with nothing before it in its sentence  -> retracts the PREVIOUS
#     sentence ("...ship today. Scratch that. Ship tomorrow." -> "Ship tomorrow.")
#   - trigger mid-sentence -> retracts only the fragment before it, same sentence
#     ("Send to Bob, scratch that, send to Alice" -> "send to Alice")
_TRIGGER_RE = re.compile(
    r"\b(?:scratch|delete|strike|ignore|forget|disregard)\s+that\b",
    re.IGNORECASE,
)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _apply_backtrack(text: str) -> str:
    out: list[str] = []
    for sent in _SENT_SPLIT.split(text.strip()):
        m = _TRIGGER_RE.search(sent)
        if not m:
            out.append(sent)
            continue
        before = sent[: m.start()].strip(" ,.;:!?-")
        after = sent[m.end():].strip(" ,.;:!?-")
        if not before and out:
            out.pop()  # nothing before the trigger -> drop the previous sentence
        if after:
            out.append(after)  # keep whatever came after the correction
    return " ".join(p for p in out if p).strip()
# Single-token correction: "<a> actually <b>" -> "<b>", gated to numeric cases so
# normal speech ("I actually love this") is left untouched.
_CORRECTION_RE = re.compile(
    r"\b(\w+)\s+(?:actually|i mean|no wait|or rather)\s+(\w+)\b",
    re.IGNORECASE,
)

# ── Spoken punctuation by name (longest phrases first) ───────────
_PUNCT_MAP: list[tuple[str, str]] = [
    (r"\bnew paragraph\b", "\n\n"),
    (r"\bnew line\b", "\n"),
    (r"\bnewline\b", "\n"),
    (r"\bfull stop\b", "."),
    (r"\bperiod\b", "."),
    (r"\bcomma\b", ","),
    (r"\bquestion mark\b", "?"),
    (r"\bexclamation (?:mark|point)\b", "!"),
    (r"\bsemicolon\b", ";"),
    (r"\bcolon\b", ":"),
    (r"\bellipsis\b", "…"),
    (r"\bopen paren(?:thesis)?\b", "("),
    (r"\bclose paren(?:thesis)?\b", ")"),
]

# ── Numbered lists: cue word then "one ... two ... [three ...]" ──
_LIST_RE = re.compile(
    r"\b(are|is|following|these|steps|goals)\b[:,]?\s+"
    r"one\s+(.+?)\s+two\s+(.+?)"
    r"(?:\s+three\s+(.+?))?(?:\s+four\s+(.+?))?(?:\s+five\s+(.+?))?$",
    re.IGNORECASE,
)

_I_RE = re.compile(r"\bi\b")
_I_CONTRACTION_RE = re.compile(r"\bi('(?:m|ll|ve|d|re))\b", re.IGNORECASE)


def pre_clean(text: str) -> str:
    """Filler removal + backtrack. Returns lowercase, unpunctuated, model-safe text."""
    t = (text or "").strip()
    if not t:
        return ""
    t = _apply_backtrack(t)

    def _corr(m: re.Match) -> str:
        a, b = m.group(1), m.group(2)
        return b if (a.isdigit() or b.isdigit()) else m.group(0)

    t = _CORRECTION_RE.sub(_corr, t)
    t = _FILLER_RE.sub("", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def apply_spoken_punctuation(text: str) -> str:
    t = text
    for pat, rep in _PUNCT_MAP:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)
    return _fix_spacing(t)


def _fix_spacing(t: str) -> str:
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)               # no space before closers
    t = re.sub(r"\(\s+", "(", t)                          # no space after (
    t = re.sub(r"\s+\)", ")", t)                          # no space before )
    t = re.sub(r"([,;:!?])(?=[^\s])", r"\1 ", t)          # ensure space after
    t = re.sub(r"\.(?=[A-Za-z])", ". ", t)               # space after . (not 3.14)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    return t.strip()


def format_lists(text: str) -> str:
    """Convert a spoken enumeration into a numbered list (conservative)."""

    def _build(m: re.Match) -> str:
        cue = m.group(1)
        segs = [g for g in m.groups()[1:] if g]
        items = []
        for i, seg in enumerate(segs, 1):
            seg = seg.strip().rstrip(".,;:")
            seg = (seg[:1].upper() + seg[1:]) if seg else seg
            items.append(f"{i}. {seg}")
        return f"{cue}:\n" + "\n".join(items)

    return _LIST_RE.sub(_build, text, count=1)


def fix_capitalization(text: str) -> str:
    t = _I_RE.sub("I", text)
    t = _I_CONTRACTION_RE.sub(lambda m: "I" + m.group(1).lower(), t)
    t = re.sub(r"^(\s*)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)
    t = re.sub(
        r"([.!?]\s+|\n+)([a-z])",
        lambda m: m.group(1) + m.group(2).upper(),
        t,
    )
    return t


def format_offline(text: str) -> str:
    """Deterministic-only pipeline for when the neural model isn't available."""
    t = apply_spoken_punctuation(text)
    t = fix_capitalization(t)
    if t and t[-1] not in ".!?…":
        t += "."
    return t


def polish_whisper(text: str, remove_fillers: bool = True,
                   chat_mode: bool = False) -> str:
    """Light cleanup for Whisper output, which is already punctuated/capitalized.

    Adds the two Wispr behaviors Whisper does NOT do — filler removal and
    backtrack self-corrections — then tidies spacing/casing. Deliberately does
    NOT run spoken-punctuation or list regexes (those are for the legacy
    unpunctuated path and would false-positive on real words like "period").
    """
    t = (text or "").strip()
    if not t:
        return ""
    if remove_fillers:
        t = pre_clean(t)  # filler words + "scratch that" / "2 actually 3"
    # Filler removal can orphan a comma ("Um, so" -> ", so"); clean that up.
    t = re.sub(r"^[\s,]+", "", t)
    t = re.sub(r"\s+,", ",", t)
    t = re.sub(r"\s{2,}", " ", t)
    t = fix_capitalization(t)
    if t and t[-1] not in ".!?…":
        t += "."
    if chat_mode:
        t = re.sub(r"\.\s*$", "", t)
    return t.strip()


def smart_format(
    raw: str,
    punctuate_fn: Callable[[str], str] | None = None,
    chat_mode: bool = False,
) -> str:
    """Full Wispr-style pipeline. ``punctuate_fn`` adds neural punctuation/casing;
    pass ``None`` for the deterministic fallback."""
    cleaned = pre_clean(raw)
    if not cleaned:
        return ""

    listed = format_lists(cleaned)
    if listed != cleaned:
        # Already structured — don't run a sentence punctuator over a list.
        out = fix_capitalization(apply_spoken_punctuation(listed))
    elif punctuate_fn is not None:
        out = punctuate_fn(cleaned)
        out = fix_capitalization(apply_spoken_punctuation(out))
    else:
        out = format_offline(cleaned)

    if chat_mode:
        out = re.sub(r"\.\s*$", "", out)  # casual apps drop the trailing period
    return out.strip()
