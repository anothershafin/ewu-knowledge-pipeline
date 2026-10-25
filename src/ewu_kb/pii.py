from __future__ import annotations

import json
import re
from collections import Counter

from .common import ROOT, config, device, read_jsonl, record, revision, semantic_code_sha, sha, write_csv, write_jsonl

PATTERNS = {
    "EMAIL": re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "PHONE": re.compile(r"(?<!\w)(?:(?:\+?88[\s-]?)?01[3-9](?:[\s-]?\d){8}|(?:\+?880[\s-]?[2-9]|0[2-9])(?:[\s-]?\d){7,10})(?!\w)"),
    "ID": re.compile(r"(?i)(?<=\bID:)\s*\d[\d-]{5,18}\b|(?<=\bID )\d[\d-]{5,18}\b|\b\d{4}-\d{1,2}-\d{2}-\d{3}\b")
}


def regex_entities(text):
    return [{"start": m.start(), "end": m.end(), "type": kind, "detector": "regex", "score": 1.0}
            for kind, pattern in PATTERNS.items() for m in pattern.finditer(text)]


def resolve_spans(text, entities, allowlist=()):
    # Prioritize regex identifiers, then longer spans; emit non-overlapping spans.
    accepted = []
    protected = [(m.start(), m.end()) for word in allowlist if word.strip()
                 for m in re.finditer(re.escape(word.strip()), text, re.I)]
    for entity in sorted(entities, key=lambda e: (e["detector"] != "regex", -(e["end"] - e["start"]))):
        start, end = entity["start"], entity["end"]
        if start < 0 or end > len(text) or end <= start:
            continue
        if entity["type"] == "PERSON" and any(a <= start and end <= b for a, b in protected):
            continue
        if not any(start < x["end"] and end > x["start"] for x in accepted):
            accepted.append(entity)
    return sorted(accepted, key=lambda e: e["start"])


def redact(text, entities):
    for entity in reversed(entities):
        text = text[:entity["start"]] + f"[{entity['type']}]" + text[entity["end"]:]
    return text


def run():
    from transformers import AutoModelForTokenClassification, AutoTokenizer, pipeline
    chosen = device()
    settings = config()["models"]["ner"]
    rev = revision("ner")
    allowlist = (ROOT / "configs/pii_allowlist.txt").read_text(encoding="utf-8").splitlines()
    tokenizer = AutoTokenizer.from_pretrained(settings["name"], revision=rev)
    model = AutoModelForTokenClassification.from_pretrained(settings["name"], revision=rev, use_safetensors=True)
    detector = pipeline("ner", model=model, tokenizer=tokenizer, aggregation_strategy="simple",
                        device=0 if chosen == "cuda" else -1)
    fingerprint = sha(json.dumps({"revision": rev, "settings": settings, "allowlist": allowlist,
                                 "code": semantic_code_sha(ROOT / "src/ewu_kb/pii.py")}, sort_keys=True))
    cached = {r["key"]: r for r in read_jsonl("data/interim/pii_cache.jsonl")}
    documents = read_jsonl("data/interim/documents_unredacted.jsonl")
    logs, predictions, cache = [], [], []
    count = 0
    for document in documents:
        for fragment in document["fragments"]:
            raw = fragment["text"]
            key = sha(fingerprint + raw)
            if key in cached:
                entities = cached[key]["entities"]
            else:
                entities = regex_entities(raw)
                for found in detector(raw, stride=64, batch_size=16):
                    if found["entity_group"] == "PER" and found["score"] >= settings["threshold"]:
                        entities.append({"start": found["start"], "end": found["end"], "type": "PERSON",
                                         "detector": "ner", "score": float(found["score"])})
                entities = resolve_spans(raw, entities, allowlist)
                cached[key] = {"key": key, "entities": entities}
            cache.append(cached[key])
            for entity in entities:
                logs.append({"doc_id": document["doc_id"], "page": fragment["page"], "block": fragment["block"],
                             "section_id": document["section_id"], "type": entity["type"],
                             "offset": entity["start"], "end": entity["end"], "detector": entity["detector"],
                             "score": entity["score"], "value_sha256": sha(raw[entity["start"]:entity["end"]])})
            predictions.append({"doc_id": document["doc_id"], "page": fragment["page"], "block": fragment["block"],
                                "section_id": document["section_id"], "text_sha256": sha(raw), "entities": entities})
            fragment["text"] = redact(raw, entities)
            count += 1
            if count % 100 == 0:
                print(f"PII fragments processed: {count}", flush=True)
                write_jsonl("data/interim/pii_cache.jsonl", list(cached.values()))
        document["text"] = "\n\n".join(f["text"] for f in document["fragments"])
        # Section headings may themselves contain person names.
        heading_entities = regex_entities(document["section_path"])
        for found in detector(document["section_path"]):
            if found["entity_group"] == "PER" and found["score"] >= settings["threshold"]:
                heading_entities.append({"start": found["start"], "end": found["end"], "type": "PERSON", "detector": "ner", "score": float(found["score"])})
        document["section_path"] = redact(document["section_path"], resolve_spans(document["section_path"], heading_entities, allowlist))
        document["pii_filtered"] = True
        document["pii_fingerprint"] = fingerprint
    write_jsonl("data/interim/pii_cache.jsonl", list(cached.values()))
    write_jsonl("data/processed/documents.jsonl", documents)
    write_jsonl("data/interim/pii_predictions.jsonl", predictions)
    write_csv("data/processed/pii_log.csv", logs, ["doc_id", "page", "block", "section_id", "type", "offset", "end", "detector", "score", "value_sha256"])
    record("pii", {"redactions": len(logs), "by_type": dict(Counter(x["type"] for x in logs)),
                   "by_detector": dict(Counter(x["detector"] for x in logs)), "fragments": count,
                   "fingerprint": fingerprint, "threshold": settings["threshold"], "device": chosen,
                   "precision_recall": "pending human annotation; detection is not a guarantee of anonymization"})
