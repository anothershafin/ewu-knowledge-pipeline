from collections import Counter
import re

from .common import config, read_jsonl, record, write_jsonl

TOPICS = ["admission", "registration", "fees_refunds", "grading_cgpa", "probation_dismissal", "retake",
          "attendance", "graduation", "scholarship", "conduct_discipline", "plagiarism_ai", "grievance",
          "course_info", "calendar", "online_classes", "other"]


def label(text, category="other", rules=None):
    rules = rules if rules is not None else config()["annotation"]["keywords"]
    lower = text.lower()
    scores = {topic: sum(lower.count(word.lower()) for word in words) for topic, words in rules.items()}
    best = max(scores, key=scores.get)
    if scores[best]:
        return best
    return {"fees": "fees_refunds", "conduct": "conduct_discipline", "rules": "other",
            "bulletin": "other"}.get(category, category if category in TOPICS else "other")


def run():
    rows = read_jsonl("data/processed/documents.jsonl")
    for row in rows:
        course_path = bool(re.search(r"\b[A-Z]{2,4}\s*[- ]?\s*\d{3}\b", row["section_path"]))
        row["topic"] = ("course_info" if course_path else
                        label(row["section_path"] + "\n" + row["text"], row["category"]))
        exclusions = config()["curation"]["excluded_bulletin_paths"]
        if course_path:
            exclusions = [word for word in exclusions if word in ("[person]", "reference book", "references", "bibliography")]
        excluded = next((word for word in exclusions if word in row["section_path"].lower()), None) if row["doc_id"] == "S1" else None
        row["index_eligible"] = excluded is None
        row["curation_reason"] = "excluded_personnel_or_bibliography: " + excluded if excluded else "student_knowledge"
    write_jsonl("data/processed/documents.jsonl", rows)
    record("annotate", {"sections": len(rows), "topics": dict(Counter(r["topic"] for r in rows)),
                        "index_eligible_sections": sum(r["index_eligible"] for r in rows),
                        "excluded_sections": sum(not r["index_eligible"] for r in rows),
                        "human_agreement": "pending human annotation"})
