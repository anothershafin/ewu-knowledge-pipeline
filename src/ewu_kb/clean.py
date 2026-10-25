from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict

from .common import config, read_jsonl, record, write_jsonl


def repeated_margins(pages, fraction=0.3, margin=2):
    counts = Counter()
    for page in pages:
        lines = [line.strip() for line in page["text"].splitlines() if line.strip()]
        counts.update(set(lines[:margin] + lines[-margin:]))
    return {line for line, count in counts.items() if count > len(pages) * fraction and count > 1}


def clean_text(text, repeated=()):
    stats = Counter()
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        reason = "repeated_margin" if stripped in repeated else (
            "page_number" if re.fullmatch(r"(?:\d{1,4}|Page\s+\d+\s+of\s+\d+)", stripped, re.I) else None)
        if reason:
            stats[reason] += len(line) + 1
        else:
            kept.append(line)
    text = "\n".join(kept)
    stats["hyphen_joins"] = len(re.findall(r"(?<=[a-z])-\s*\n\s*(?=[a-z])", text))
    protected = {"full-time", "part-time", "well-being", "non-credit", "self-assessment", "credit-hour"}
    def join_word(match):
        compound = match[1] + "-" + match[2]
        return compound if compound in protected else match[1] + match[2]
    text = re.sub(r"\b([a-z]+)-[ \t]*\n[ \t]*([a-z]+)\b", join_word, text)
    text = unicodedata.normalize("NFKC", text).translate(str.maketrans({
        "“": '"', "”": '"', "’": "'", "‘": "'", "•": "-", "\u00a0": " ", "\u00ad": ""}))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, stats


def run():
    rows = read_jsonl("data/interim/pages.jsonl")
    grouped = defaultdict(list)
    for row in rows:
        if row["kind"] == "pdf":
            grouped[row["doc_id"]].append(row)
    settings = config()["cleaning"]
    repeated = {sid: repeated_margins(items, settings["repeated_fraction"], settings["margin_lines"])
                for sid, items in grouped.items()}
    totals, losses = Counter(), []
    for row in rows:
        before = len(row["text"])
        text, stats = clean_text(row["text"], repeated.get(row["doc_id"], set()))
        totals.update(stats)
        loss = 1 - len(text) / max(before, 1)
        if loss > settings["loss_warning"]:
            losses.append({"doc_id": row["doc_id"], "page": row["page"], "block": row["block"],
                           "loss_fraction": round(loss, 3)})
        row.update(text=text, original_chars=before)
    write_jsonl("data/interim/cleaned.jsonl", rows)
    record("clean", {"rules": dict(totals), "large_losses": losses,
                     "rule_units": {"repeated_margin": "characters removed", "page_number": "characters removed", "hyphen_joins": "end-of-line joins"},
                     "before_chars": sum(r["original_chars"] for r in rows),
                     "after_chars": sum(len(r["text"]) for r in rows)})
