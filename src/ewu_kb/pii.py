from __future__ import annotations

import json
import re
from collections import Counter

from .common import ROOT, config, device, now, read_jsonl, record, revision, semantic_code_sha, sha, write_csv, write_json, write_jsonl

PATTERNS = {
    "EMAIL": re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "PHONE": re.compile(r"(?<!\w)(?:(?:\+?88[\s-]?)?01[3-9](?:[\s-]?\d){8}|(?:\+?880[\s-]?[2-9]|0[2-9])(?:[\s-]?\d){7,10})(?!\w)"),
    "ID": re.compile(r"(?i)(?<=\bID:)\s*\d[\d-]{5,18}\b|(?<=\bID )\d[\d-]{5,18}\b|\b\d{4}-\d{1,2}-\d{2}-\d{3}\b")
}


def regex_entities(text):
    return [{"start": m.start(), "end": m.end(), "type": kind, "detector": "regex", "score": 1.0}
            for kind, pattern in PATTERNS.items() for m in pattern.finditer(text)]


# Name repair rules (added after corpus-wide inspection of fragmented tags such as
# "[PERSON]venin's theorem" and "Mr. [PERSON]hi Uddin"). They are general boundary
# rules, not thresholds tuned on the evaluation sample.
HONORIFIC = re.compile(r"(?:\b(?:Mr|Mrs|Ms|Miss|Dr|Prof|Professor|Engr|Begum|Sir|Madam)\.?)((?:[ ]+(?:[A-Z][\w'\u2019-]*\.?|[A-Z]\.))+)[ ]*$")
NAME_TOKEN = re.compile(r"[ ]{1,2}([A-Z][a-z][\w'\u2019-]*|[A-Z]\.)")
# Capitalised words that usually follow a name but are not part of it.
NOT_NAME = {
    "the", "and", "of", "in", "for", "at", "on", "to", "by", "with", "from",
    "chairperson", "chairman", "chair", "member", "members", "secretary", "professor", "lecturer",
    "department", "dean", "registrar", "director", "coordinator", "adviser", "advisor", "head",
    "assistant", "associate", "senior", "deputy", "officer", "controller", "treasurer", "vice",
    "chancellor", "pro", "president", "university", "scholarship", "fund", "award", "trust",
    "foundation", "hall", "building", "road", "bangladesh", "dhaka", "east", "west", "faculty",
    "school", "office", "committee", "board", "edition", "press", "publishers", "publication",
    "publications", "theorem", "law", "equation", "chapter", "volume", "vol", "part", "unit",
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "mathematics", "engineering", "science", "studies",
}
# Technical eponyms are public terms, not personal data (Thevenin's theorem, Voronoi diagram).
EPONYM = re.compile(r"^(?:['\u2019]s|s['\u2019])?[ -]+(?:theorems?|laws?|equations?|formulae?|formulas|series|rules?|"
                    r"principles?|diagrams?|transforms?|transformations?|methods?|algorithms?|inequalit(?:y|ies)|"
                    r"tests?|distributions?|functions?|effects?|constants?|integrals?|criteri(?:on|a)|lemmas?|"
                    r"conjectures?|numbers?|triangles?|circuits?|bridges?|polynomials?|expansions?|"
                    r"extrapolation|interpolation|approximations?|models?|cycles?|codes?|filters?|"
                    r"identity|identities|matrix|matrices|space|spaces|condition|conditions)\b", re.I)


def expand_to_words(text, start, end):
    """Grow a detected span to whole words so no name fragment survives redaction."""
    while start > 0 and text[start - 1].isalnum():
        start -= 1
    while end < len(text) and text[end].isalnum():
        end += 1
    return start, end


def complete_name(text, start, end):
    """Add name tokens after an honorific and directly following capitalised name words."""
    line_start = text.rfind("\n", 0, start) + 1
    honorific = HONORIFIC.search(text[line_start:start])
    if honorific:
        run = honorific.group(1)
        start = line_start + honorific.start(1) + (len(run) - len(run.lstrip()))
    for _ in range(3):
        following = NAME_TOKEN.match(text, end)
        if not following or following.group(1).rstrip(".").casefold() in NOT_NAME:
            break
        end = following.end(1)
    return start, end


def repair_person_spans(text, entities):
    """Expand to word boundaries, complete names, merge touching parts and drop eponyms."""
    people, others = [], []
    for entity in entities:
        if entity["type"] != "PERSON":
            others.append(entity)
            continue
        start, end = expand_to_words(text, entity["start"], entity["end"])
        start, end = complete_name(text, start, end)
        people.append({**entity, "start": start, "end": end})
    merged = []
    for entity in sorted(people, key=lambda e: (e["start"], -e["end"])):
        if merged and re.fullmatch(r"[ .\-]{0,3}", text[merged[-1]["end"]:entity["start"]] or "") \
                and entity["start"] >= merged[-1]["start"]:
            last = merged[-1]
            merged[-1] = {**last, "end": max(last["end"], entity["end"]), "score": max(last["score"], entity["score"])}
        elif merged and entity["start"] < merged[-1]["end"]:
            last = merged[-1]
            merged[-1] = {**last, "end": max(last["end"], entity["end"]), "score": max(last["score"], entity["score"])}
        else:
            merged.append(entity)
    kept = [e for e in merged if not EPONYM.match(text[e["end"]:])]
    return others + kept


def detect(text, detector, threshold, allowlist=()):
    """Regex identifiers plus repaired NER person spans for one text fragment."""
    entities = regex_entities(text)
    people = [{"start": found["start"], "end": found["end"], "type": "PERSON", "detector": "ner",
               "score": float(found["score"])}
              for found in detector(text, stride=64, batch_size=16)
              if found["entity_group"] == "PER" and found["score"] >= threshold]
    return resolve_spans(text, entities + repair_person_spans(text, people), allowlist)


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


def load_detector():
    from transformers import AutoModelForTokenClassification, AutoTokenizer, pipeline
    chosen = device()
    settings = config()["models"]["ner"]
    rev = revision("ner")
    allowlist = (ROOT / "configs/pii_allowlist.txt").read_text(encoding="utf-8").splitlines()
    tokenizer = AutoTokenizer.from_pretrained(settings["name"], revision=rev)
    model = AutoModelForTokenClassification.from_pretrained(settings["name"], revision=rev, use_safetensors=True)
    detector = pipeline("ner", model=model, tokenizer=tokenizer, aggregation_strategy="simple",
                        device=0 if chosen == "cuda" else -1)
    return detector, settings, rev, allowlist, chosen


def recheck_review_pages():
    """Re-run the current detector on the preserved PII review pages, fragment by fragment.

    The original prediction snapshot (work/pii_review_predictions.jsonl) is never modified.
    Current predictions go to work/pii_review_predictions_current.jsonl so both can be reported.
    """
    from collections import defaultdict
    pages = read_jsonl("work/pii_review_pages.jsonl")
    if not pages:
        raise ValueError("No preserved PII review pages found")
    grouped = defaultdict(list)
    for document in read_jsonl("data/interim/documents_unredacted.jsonl"):
        for fragment in document["fragments"]:
            if fragment["page"]:
                grouped[(document["doc_id"], fragment["page"])].append(fragment["text"])
    detector, settings, rev, allowlist, chosen = load_detector()
    rows = []
    for page in pages:
        fragments = grouped[(page["doc_id"], page["page"])]
        if "".join(f + "\n\n" for f in fragments) != page["text"]:
            raise ValueError(f"Review page {page['sample_id']} no longer matches the extracted fragments")
        entities, offset = [], 0
        for fragment in fragments:
            for entity in detect(fragment, detector, settings["threshold"], allowlist):
                entities.append({**entity, "start": entity["start"] + offset, "end": entity["end"] + offset})
            offset += len(fragment) + 2
        rows.append({"sample_id": page["sample_id"], "entities": entities})
    write_jsonl("work/pii_review_predictions_current.jsonl", rows)
    write_json("work/pii_review_predictions_current.meta.json", {
        "generated_at": now(), "model_revision": rev, "threshold": settings["threshold"], "device": chosen,
        "pii_code_sha256": semantic_code_sha(ROOT / "src/ewu_kb/pii.py"),
        "source_pages_sha256": sha(ROOT / "work/pii_review_pages.jsonl"),
        "note": "Current detector on the same preserved review pages. Not a held-out estimate."})
    print(f"Current detector predictions written for {len(rows)} review pages.")


def run():
    detector, settings, rev, allowlist, chosen = load_detector()
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
                entities = detect(raw, detector, settings["threshold"], allowlist)
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
        heading = document["section_path"]
        document["section_path"] = redact(heading, detect(heading, detector, settings["threshold"], allowlist))
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
