"""Prepare local annotation work without inventing human answers."""
from __future__ import annotations

import html
import json
from collections import defaultdict

from .common import ROOT, config, read_jsonl, rng, sha, write_csv, write_json, write_jsonl

QUESTIONS = [
    ("probation_dismissal", "What happens when an undergraduate student's CGPA falls below the probation threshold?"),
    ("probation_dismissal", "How many semesters can a student remain on academic probation?"),
    ("probation_dismissal", "What conditions lead to academic dismissal?"),
    ("grading_cgpa", "What grade points correspond to an A grade?"),
    ("grading_cgpa", "How is cumulative grade point average calculated?"),
    ("grading_cgpa", "When can a student receive an incomplete grade?"),
    ("retake", "Which courses may a student retake?"),
    ("retake", "How does retaking a course affect the CGPA?"),
    ("registration", "What is the add and drop procedure?"),
    ("registration", "How can a student request a leave of absence?"),
    ("registration", "What is the role of the academic adviser in course registration?"),
    ("fees_refunds", "What is the current tuition fee per credit for CSE?"),
    ("fees_refunds", "What admission fee is charged to undergraduate students?"),
    ("fees_refunds", "What is the policy on tuition refunds after withdrawal?"),
    ("scholarship", "What academic performance is required for a merit scholarship?"),
    ("scholarship", "What financial assistance is available for students?"),
    ("scholarship", "What conditions must be met to continue a tuition waiver?"),
    ("admission", "What are the undergraduate admission eligibility requirements?"),
    ("admission", "What documents are needed for admission?"),
    ("admission", "When is the undergraduate application deadline?"),
    ("attendance", "What attendance is required to sit for the final examination?"),
    ("attendance", "What are the consequences of insufficient class attendance?"),
    ("graduation", "What minimum CGPA is required for an undergraduate degree?"),
    ("graduation", "How many credits are required for the CSE undergraduate degree?"),
    ("course_info", "What is the prerequisite for CSE106 Discrete Mathematics?"),
    ("course_info", "What topics are covered in Structured Programming?"),
    ("course_info", "Which courses are required before Data Structures?"),
    ("course_info", "What elective courses are available in the CSE programme?"),
    ("course_info", "How are theory and laboratory credits listed for CSE courses?"),
    ("plagiarism_ai", "How does the university define plagiarism?"),
    ("plagiarism_ai", "What penalties apply to plagiarism?"),
    ("plagiarism_ai", "What does the policy say about using artificial intelligence in coursework?"),
    ("plagiarism_ai", "What responsibilities do students have when using generative AI?"),
    ("conduct_discipline", "What behaviour is treated as disciplinary misconduct?"),
    ("conduct_discipline", "How are disciplinary matters investigated?"),
    ("grievance", "How can a student submit a grievance?"),
    ("grievance", "Who handles a student grievance under the official policy?"),
    ("calendar", "When do undergraduate classes begin in the published semester calendar?"),
    ("calendar", "What is the last day to drop a course in the published calendar?"),
    ("online_classes", "What guidance does the university provide for attending online classes?"),
]


def run():
    random = rng()
    chunks = read_jsonl("data/processed/chunks.jsonl")
    if len(chunks) < 100:
        raise ValueError("Need at least 100 chunks for annotation sample")
    snapshot = ROOT / "work/review_snapshot.json"
    previous = {}
    if snapshot.exists():
        previous = json.loads(snapshot.read_text())
        if previous["chunks_sha256"] != sha(ROOT / "data/processed/chunks.jsonl"):
            raise ValueError("Corpus changed after review preparation. Preserve and version the existing review files before creating a new sample.")
    if not (ROOT / "eval/annotation_sample.csv").exists():
        sample = random.sample(sorted(chunks, key=lambda r: r["chunk_id"]), 100)
        rows = [{"chunk_id": r["chunk_id"], "rule_topic": r["topic"], "human_topic": "", "reviewer": "",
                 "doc_id": r["doc_id"], "page_start": r["page_start"], "section_path": r["section_path"], "text": r["text"]}
                for r in sample]
        write_csv("eval/annotation_sample.csv", rows, rows[0].keys())
    if not (ROOT / "eval/questions.csv").exists():
        rows = [{"qid": f"Q{i:02}", "question": q, "topic": t, "expected_doc": "", "expected_page": "",
                 "expected_section": "", "reviewed": "", "reviewer": "", "notes": ""}
                for i, (t, q) in enumerate(QUESTIONS, 1)]
        write_csv("eval/questions.csv", rows, rows[0].keys())
    # Store unredacted review pages only in ignored local work; sampling includes faculty-rich pages.
    documents = read_jsonl("data/interim/documents_unredacted.jsonl")
    grouped = defaultdict(list)
    for doc in documents:
        for f in doc["fragments"]:
            if f["page"]:
                grouped[(doc["doc_id"], f["page"])].append((doc["section_id"], f))
    if not (ROOT / "eval/pii_pages.csv").exists():
        candidates = sorted(grouped)
        faculty = [key for key in candidates if "faculty" in " ".join(f["text"] for _, f in grouped[key]).lower()]
        n = config()["annotation"]["pii_pages"]
        selected = random.sample(faculty, min(n // 2, len(faculty)))
        selected += random.sample([key for key in candidates if key not in selected], n - len(selected))
        predictions = {(p["section_id"], p["page"], p["block"], p["text_sha256"]): p["entities"]
                       for p in read_jsonl("data/interim/pii_predictions.jsonl")}
        page_rows, private, pred_rows = [], [], []
        for index, key in enumerate(selected, 1):
            text, entities = "", []
            for section_id, f in grouped[key]:
                offset = len(text)
                for entity in predictions.get((section_id, f["page"], f["block"], sha(f["text"])), []):
                    entities.append({**entity, "start": entity["start"] + offset, "end": entity["end"] + offset})
                text += f["text"] + "\n\n"
            sid = f"P{index:02}"
            page_rows.append({"sample_id": sid, "doc_id": key[0], "page": key[1],
                              "text_sha256": sha(text), "reviewed": "", "reviewer": ""})
            private.append({"sample_id": sid, "doc_id": key[0], "page": key[1], "text": text})
            pred_rows.append({"sample_id": sid, "entities": entities})
        write_csv("eval/pii_pages.csv", page_rows, page_rows[0].keys())
        write_csv("eval/pii_annotations.csv", [], ["sample_id", "start", "end", "type", "reviewer", "notes"])
        write_jsonl("work/pii_review_pages.jsonl", private)
        write_jsonl("work/pii_review_predictions.jsonl", pred_rows)
        # Browser-independent local HTML uses only textContent-safe escaped text.
        panels = []
        for p in private:
            panels.append(f'<section><h2>{p["sample_id"]}: {p["doc_id"]}, PDF page {p["page"]}</h2>'
                          '<p>Select a name, email, phone or ID. The selection offsets appear below.</p>'
                          f'<pre data-id="{p["sample_id"]}">{html.escape(p["text"])}</pre></section>')
        html_text = '''<!doctype html><meta charset="utf-8"><title>Local PII annotation helper</title>
<style>body{max-width:1000px;margin:40px auto;font:16px system-ui;background:#f8fafc;color:#172033}pre{white-space:pre-wrap;background:white;padding:24px;border:1px solid #cbd5e1;line-height:1.7}aside{position:sticky;top:0;background:#dbeafe;padding:16px}section{margin:40px 0}</style>
<h1>Private PII annotation helper</h1><p>Mark all PII independently. Offsets are Python Unicode character offsets in the displayed source. Do not publish this file.</p>
<aside id="selection">Select text inside a source page.</aside>
''' + "".join(panels) + '''<script>document.addEventListener('mouseup',()=>{const s=window.getSelection();if(!s.rangeCount||!s.toString())return;const r=s.getRangeAt(0);let p=r.startContainer.parentElement.closest('pre');if(!p||!p.contains(r.endContainer))return;const a=r.cloneRange();a.selectNodeContents(p);a.setEnd(r.startContainer,r.startOffset);const start=Array.from(a.toString()).length;const end=start+Array.from(s.toString()).length;document.querySelector('#selection').textContent=`sample_id=${p.dataset.id}, start=${start}, end=${end}, selected=${s.toString()}`;});</script>'''
        (ROOT / "work/pii_review.html").write_text(html_text, encoding="utf-8")
    write_json("work/review_snapshot.json", {**previous, "chunks_sha256": sha(ROOT / "data/processed/chunks.jsonl"),
                                            "documents_sha256": sha(ROOT / "data/interim/documents_unredacted.jsonl")})
    print("Manual annotation files prepared. No human labels or gold answers have been filled.")
