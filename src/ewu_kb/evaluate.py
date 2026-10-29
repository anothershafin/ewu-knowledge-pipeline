from __future__ import annotations

import json
from collections import Counter

from .common import ROOT, read_csv, read_jsonl, record, sha, write_csv, write_json


def retrieval_metrics(ranked_relevance):
    if not ranked_relevance:
        return {"n": 0, "Recall@1": None, "Recall@5": None, "MRR": None}
    n = len(ranked_relevance)
    return {"n": n, "Recall@1": sum(bool(r[:1] and r[0]) for r in ranked_relevance) / n,
            "Recall@5": sum(any(r[:5]) for r in ranked_relevance) / n,
            "MRR": sum(next((1 / (i + 1) for i, hit in enumerate(r) if hit), 0) for r in ranked_relevance) / n}


def span_metrics(gold, predicted):
    # Exact character-span and type agreement; duplicated predictions cannot count twice.
    gold, predicted = set(gold), set(predicted)
    tp = len(gold & predicted)
    return {"tp": tp, "fp": len(predicted - gold), "fn": len(gold - predicted),
            "precision": tp / len(predicted) if predicted else None,
            "recall": tp / len(gold) if gold else None}


def question_reference_review(rows):
    human = sum(r.get("reviewed") == "yes" and bool(r.get("reviewer"))
                and not r["reviewer"].strip().casefold().startswith(("codex", "assistant")) for r in rows)
    return {"questions": len(rows), "independent_human_reviewed_questions": human,
            "independent_human_review": bool(rows) and human == len(rows),
            "preparation": "prepared on behalf of the project owner" if human < len(rows) else "reviewer-labeled reference"}


def freeze_questions():
    from .annotate import TOPICS
    rows = read_csv("eval/questions.csv")
    documents = read_jsonl("data/processed/documents.jsonl")
    known = {d["doc_id"] for d in documents}
    if len(rows) != 40 or len({r["qid"] for r in rows}) != 40:
        raise ValueError("Exactly 40 uniquely identified questions required")
    for row in rows:
        if row.get("reviewed") != "yes" or not row.get("reviewer"):
            raise ValueError("Every question needs a completed source review and the actual reviewer identity")
        if not row.get("expected_doc") or not (row.get("expected_page") or row.get("expected_section")):
            raise ValueError("Each question needs an expected document and PDF page or exact section")
        if row.get("topic") not in TOPICS or any(sid not in known for sid in row["expected_doc"].split("|")):
            raise ValueError("Question topic or expected document is invalid or unavailable in the snapshot")
        accepted = [d for d in documents if d["doc_id"] in row["expected_doc"].split("|")]
        if row.get("expected_section_id"):
            accepted_ids = set(row["expected_section_id"].split("|"))
            if not accepted_ids <= {d["section_id"] for d in accepted}:
                raise ValueError("Expected section ID is not present in the selected source")
            accepted = [d for d in accepted if d["section_id"] in accepted_ids]
        if row.get("expected_page"):
            for page in row["expected_page"].split("|"):
                if not page.isdigit() or not any(d["page_start"] and d["page_start"] <= int(page) <= d["page_end"] for d in accepted):
                    raise ValueError("Expected PDF page is not present in the selected source")
        elif not any(row["expected_section"].casefold() in d["section_path"].casefold() for d in accepted):
            raise ValueError("Expected section is not present in the selected source")
    target = ROOT / "eval/frozen/questions.csv"
    if target.exists():
        if sha(target) != sha(ROOT / "eval/questions.csv"):
            raise ValueError("Frozen questions differ; preserve the original evaluation")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((ROOT / "eval/questions.csv").read_bytes())
    write_json("eval/frozen/questions.lock.json", {"schema_version": 2, "sha256": sha(target), "rows": 40,
                                                  "corpus_sha256": sha(ROOT / "data/processed/chunks.jsonl"),
                                                  "source_manifest_sha256": sha(ROOT / "data/processed/manifest.csv"),
                                                  "reference_review": question_reference_review(rows),
                                                  "rule": "Frozen before retrieval evaluation; do not tune on this set"})


def scorable_topic_rows(rows, exclusions):
    known = {r["chunk_id"] for r in rows}
    if any(r.get("chunk_id") not in known or not r.get("reason", "").strip() for r in exclusions):
        raise ValueError("Topic exclusions require a known chunk and a recorded data-quality reason")
    excluded = {r["chunk_id"] for r in exclusions}
    selected = [r for r in rows if r["chunk_id"] not in excluded]
    if not selected:
        raise ValueError("No scorable topic passages remain")
    return selected


def annotation_results():
    from .annotate import TOPICS
    rows = read_csv("eval/annotation_sample.csv")
    if len(rows) != 100 or any(r.get("human_topic") not in TOPICS or not r.get("reviewer") for r in rows):
        return {"status": "pending human annotation", "completed": sum(bool(r.get("human_topic")) for r in rows), "required": 100}
    decisions = ROOT / "work/topic_label_exclusions.json"
    exclusions = json.loads(decisions.read_text(encoding="utf-8"))["excluded"] if decisions.exists() else []
    selected = scorable_topic_rows(rows, exclusions)
    result = {"status": "complete", "n": len(selected), "raw_n": len(rows), "excluded": exclusions,
              "agreement": sum(r["rule_topic"] == r["human_topic"] for r in selected) / len(selected),
              "raw_agreement_including_flagged_fragments": sum(r["rule_topic"] == r["human_topic"] for r in rows) / len(rows)}
    result["confusion"] = [{"human": a, "rule": b, "count": n}
                           for (a, b), n in sorted(Counter((r["human_topic"], r["rule_topic"]) for r in selected).items())]
    result["note"] = "Descriptive agreement on a review sample. If rules are tuned on it, agreement is not held-out accuracy."
    provenance = ROOT / "work/topic_annotation_provenance.json"
    if provenance.exists():
        details = json.loads(provenance.read_text(encoding="utf-8"))
        if sha(ROOT / "eval/annotation_sample.csv") != details["annotation_sha256"]:
            raise ValueError("Topic reference changed after its provenance was recorded")
        result["reference_review"] = details
    return result


def pii_reference_review(pages, annotations):
    """Distinguish completed preparation from independent human verification."""
    def by_assistant(row):
        return row.get("reviewer", "").strip().casefold().startswith(("codex", "assistant"))

    human_pages = sum(r.get("reviewed") == "yes" and bool(r.get("reviewer")) and not by_assistant(r)
                      for r in pages)
    return {"pages": len(pages), "independent_human_reviewed_pages": human_pages,
            "independent_human_review": bool(pages) and human_pages == len(pages),
            "assistant_prepared_spans": sum(by_assistant(r) for r in annotations),
            "preparation": "prepared on behalf of the project owner" if any(by_assistant(r) for r in pages + annotations)
                           else "reviewer-labeled reference"}


def pii_results():
    pages = read_csv("eval/pii_pages.csv")
    annotations = read_csv("eval/pii_annotations.csv")
    if not pages or any(r.get("reviewed") != "yes" or not r.get("reviewer") for r in pages):
        return {"status": "pending human annotation", "pages": len(pages),
                "completed": sum(r.get("reviewed") == "yes" for r in pages)}
    selected = {r["sample_id"] for r in pages}
    originals = {r["sample_id"]: r["text"] for r in read_jsonl("work/pii_review_pages.jsonl")}
    for page in pages:
        if page["sample_id"] not in originals or sha(originals[page["sample_id"]]) != page["text_sha256"]:
            raise ValueError("PII review source changed; preserve the original text and offsets")
    gold = set()
    for row in annotations:
        sid = row.get("sample_id")
        if sid not in selected or row.get("type") not in ("PERSON", "EMAIL", "PHONE", "ID") or not row.get("reviewer"):
            raise ValueError("PII annotation needs a known sample, valid type and reviewer")
        if not row.get("start", "").isdigit() or not row.get("end", "").isdigit():
            raise ValueError("PII start/end offsets must be nonnegative integers")
        start, end = int(row["start"]), int(row["end"])
        if not 0 <= start < end <= len(originals[sid]):
            raise ValueError(f"PII span is outside sample {sid}")
        gold.add((sid, start, end, row["type"]))
    predictions = read_jsonl("work/pii_review_predictions.jsonl")
    pred = {(r["sample_id"], e["start"], e["end"], e["type"]) for r in predictions for e in r["entities"]}
    review = pii_reference_review(pages, annotations)
    review["source_pages_sha256"] = sha(ROOT / "work/pii_review_pages.jsonl")
    review["predictions_sha256"] = sha(ROOT / "work/pii_review_predictions.jsonl")
    result = {"status": "complete", "reference_review": review,
              "all": span_metrics(gold, pred), "by_type": {}}
    for kind in ("PERSON", "EMAIL", "PHONE", "ID"):
        result["by_type"][kind] = span_metrics({x for x in gold if x[3] == kind}, {x for x in pred if x[3] == kind})
    result["note"] = "Exact-span metrics on a deliberately mixed sample, not a population estimate. Empty denominators are null."
    if not review["independent_human_review"]:
        result["note"] += " Reference entries were prepared on behalf of the project owner; independent human verification is pending. These scores measure agreement with that reference."
    return result


def relevant(result, expected):
    if result["doc_id"] not in expected["expected_doc"].split("|"):
        return False
    if expected.get("expected_section_id") and result.get("section_id") not in expected["expected_section_id"].split("|"):
        return False
    page = expected.get("expected_page", "")
    if page:
        if not result.get("page_start") or not result.get("page_end"):
            return False
        return any(result["page_start"] <= int(p) <= result["page_end"] for p in page.split("|"))
    return expected["expected_section"].casefold() in result["section_path"].casefold()


def run():
    result = {"annotation": annotation_results(), "pii": pii_results(), "retrieval": {"status": "pending frozen source-reviewed question set"}}
    path = ROOT / "eval/frozen/questions.csv"
    if path.exists():
        from .search import Searcher
        questions = read_csv("eval/frozen/questions.csv")
        lock = json.loads((ROOT / "eval/frozen/questions.lock.json").read_text())
        if sha(path) != lock["sha256"]:
            raise ValueError("Question set changed after freeze")
        if lock.get("corpus_sha256") and sha(ROOT / "data/processed/chunks.jsonl") != lock["corpus_sha256"]:
            raise ValueError("Retrieval corpus changed after question freeze; preserve and version the evaluation")
        experiments, per_question = [], []
        for key in ("bge", "minilm"):
            for size in (200, 300):
                searcher = Searcher(key, size)
                hits = []
                for question in questions:
                    # Primary model comparison uses raw semantic rank, no topic gold or version boost.
                    found = searcher.search(question["question"], 20, prefer_current=False)
                    labels = [relevant(r, question) for r in found]
                    hits.append(labels)
                    per_question.append({"qid": question["qid"], "model": key, "nominal_size": size,
                                         "first_relevant_rank": next((i + 1 for i, h in enumerate(labels) if h), ""),
                                         "retrieved_ids": json.dumps([r["chunk_id"] for r in found])})
                experiments.append({"model": key, "nominal_size": size, **retrieval_metrics(hits)})
                del searcher
        write_csv("reports/retrieval_results.csv", experiments, ["model", "nominal_size", "n", "Recall@1", "Recall@5", "MRR"])
        write_csv("data/processed/retrieval_per_question.csv", per_question,
                  ["qid", "model", "nominal_size", "first_relevant_rank", "retrieved_ids"])
        result["retrieval"] = {"status": "complete", "question_sha256": lock["sha256"], "experiments": experiments,
                               "reference_review": lock.get("reference_review", {"preparation": "not recorded"}),
                               "metric_definition": "Recall@k is question hit rate (any accepted source locator, including exact section ID when supplied). MRR is truncated at 20. Locator hits do not measure generated-answer completeness."}
    record("evaluate", result)
    return result
