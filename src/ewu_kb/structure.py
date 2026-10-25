from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

from .common import now, read_csv, read_jsonl, record, sha, sources, write_csv, write_jsonl

CODE = r"[A-Z]{2,4}\s?\d{3}"
ENTRY = re.compile(rf"^\s*({CODE})\s*(?::|[-–—]|\s{{1,}})\s*([A-Z][^\n]{{3,100}})")
PREREQ = re.compile(r"pre[- ]?requisites?\s*[:\-]?\s*(.*)", re.I)


def course_codes(text):
    return list(dict.fromkeys(re.sub(r"\s", "", value) for value in re.findall(CODE, text)))


def parse_course(text, source, locator):
    match = ENTRY.search(text)
    if not match:
        return None
    code, title = re.sub(r"\s", "", match[1]), match[2].strip()
    if title.lower().startswith(("credit hours", "credit hour", "course outcomes", "course objectives")):
        return None
    title = re.split(r"\s+(?:Credit|Prerequisite|Theory|Lab(?:oratory)?)\b", title, flags=re.I)[0].strip(" :,-")
    prerequisite = PREREQ.search(text)
    expression = prerequisite[1].split("\n")[0].strip() if prerequisite else ""
    expression = re.split(r"(?:Course Objectives|Objectives|Course Outcomes|Contents|CO1)\b", expression, flags=re.I)[0].strip()
    codes = course_codes(expression)
    credit = re.search(r"(?:Credits?(?:\s+Hours?)?|Total)\s*[:=]?\s*(\d(?:\.\d+)?)", text, re.I)
    theory = re.search(r"Theory\s*[:=]?\s*(\d(?:\.\d+)?)", text, re.I)
    lab = re.search(r"Lab(?:oratory)?\s*[:=]?\s*(\d(?:\.\d+)?)", text, re.I)
    scheme = re.search(r"Theory\s+Laboratory\s+Total\s+Credit Hours\s+(\d(?:\.\d+)?)\s+(\d(?:\.\d+)?)\s+(\d(?:\.\d+)?)", text, re.I)
    return {"code": code, "title": title, "credits_theory": scheme[1] if scheme else (theory[1] if theory else ""),
            "credits_lab": scheme[2] if scheme else (lab[1] if lab else ""),
            "credits_total": scheme[3] if scheme else (credit[1] if credit else ""),
            "prerequisites": json.dumps(codes), "prerequisite_expression": expression,
            "prerequisite_status": "explicit_none" if expression.lower() in ("none", "nil", "n/a", "no") else (
                "parsed" if codes else "unresolved"), "source": source, "locator": str(locator),
            "has_alternatives": bool(re.search(r"\bor\b", expression, re.I))}


def pdf_segments(row):
    """Detect headings from font metadata, retaining every source text line."""
    spans = row["spans"]
    sizes = Counter(round(s["size"]) for s in spans if s["text"].strip())
    body_size = sizes.most_common(1)[0][0] if sizes else 10
    headings = {}
    for span in spans:
        value = re.sub(r"\s+", " ", span["text"]).strip()
        if (4 < len(value) < 130 and not value.endswith((".", ",", ";"))
                and (span["size"] >= body_size + 1.5 or span["bold"])):
            headings[value] = 1 if span["size"] >= body_size + 4 else (2 if span["size"] >= body_size + 2 else 3)
    result, buffer, heading = [], [], ""
    for line in row["text"].splitlines():
        normal = line.strip()
        if normal in headings and len(normal.split()) < 18:
            if buffer:
                result.append((heading, "\n".join(buffer), headings.get(heading, 3)))
                buffer = []
            heading = normal
        buffer.append(line)
    if buffer:
        result.append((heading, "\n".join(buffer), headings.get(heading, 3)))
    return result


def build_sections(rows, metadata):
    sections = []
    for sid, pages in rows.items():
        source = metadata[sid]
        path = [source["category"]]
        heading_stack = []
        current = None
        for row in pages:
            fragments = pdf_segments(row) if row["kind"] == "pdf" else [("", row["text"], 1)]
            if row["kind"].startswith("h") and row["kind"][1:].isdigit():
                level = max(1, int(row["kind"][1:]))
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, row["text"]))
                path = [source["category"]] + [text for _, text in heading_stack]
                current = None
            elif row["kind"] in ("p", "summary") and row["text"].rstrip().endswith("?"):
                path = [source["category"], row["text"]]
                heading_stack = [(1, row["text"])]
                current = None
            for heading, text, level in fragments:
                if not text.strip():
                    continue
                if heading:
                    while heading_stack and heading_stack[-1][0] >= level:
                        heading_stack.pop()
                    heading_stack.append((level, heading))
                    path = [source["category"]] + [value for _, value in heading_stack]
                    current = None
                # Course entries form independent sections, including HTML p headings.
                if ENTRY.match(text) and parse_course(text, sid, "") and sid in ("C1", "S1"):
                    path = [source["category"], text.splitlines()[0][:140]]
                    heading_stack = [(1, text.splitlines()[0][:140])]
                    current = None
                if current is None:
                    current = {"doc_id": sid, "section_path": " > ".join(path),
                               "source_version": source.get("version", "web-" + now()[:7]),
                               "source_url": source["url"], "category": source["category"], "fragments": []}
                    sections.append(current)
                current["fragments"].append({"page": row["page"], "block": row["block"],
                                              "anchor": row["anchor"], "text": text})
        for section in [s for s in sections if s["doc_id"] == sid]:
            section["text"] = "\n\n".join(f["text"] for f in section["fragments"])
            nums = [f["page"] for f in section["fragments"] if f["page"]]
            section.update(page_start=min(nums) if nums else None, page_end=max(nums) if nums else None,
                           section_id=sha(sid + section["section_path"] + section["text"])[:24])
    return sections


def extract_rules(rows):
    facts = []
    for row in rows:
        if row["doc_id"] not in ("S1", "W1"):
            continue
        text = re.sub(r"\s+", " ", row["text"])
        def add(rule, value):
            facts.append({"rule": rule, "source": row["doc_id"], "page": row["page"], "block": row["block"], "value": str(value)})
        match = re.search(r"CGPA will be between (\d+(?:\.\d+)?) and (\d+(?:\.\d+)?)", text, re.I)
        if match:
            add("undergraduate_probation_upper_cgpa", f"{float(match[2]):.2f}")
        match = re.search(r"raise their CGPA to at least (\d+(?:\.\d+)?) after the probation", text, re.I)
        if match:
            add("undergraduate_probation_recovery_cgpa", f"{float(match[1]):.2f}")
        match = re.search(r"CGPA falls below (\d+(?:\.\d+)?) after the first two", text, re.I)
        if match:
            add("automatic_dismissal_cgpa", f"{float(match[1]):.2f}")
        if re.search(r"retake a particular course only once", text, re.I):
            add("non_f_retake_count", "1")
        if re.search(r"Retake the same any number of times", text, re.I):
            add("f_grade_retake_limit", "unlimited_within_graduation_time_limit")
        if re.search(r"grades obtained in the last attempt of the course", text, re.I):
            add("retake_cgpa_basis", "last_attempt")
        grading = re.compile(r"((?:\d+(?:\.\d+)?%?\s*(?:to less than|-\s*below|-)\s*\d+(?:\.\d+)?%?)|(?:\d+%?\s+and\s+above)|(?:(?:Less than|below)\s+\d+%?))\s+([ABCDF][+-]?)\s+([0-4]\.\d+)", re.I)
        for match in grading.finditer(text):
            grade = match[2].upper()
            add(f"grade_point_{grade}", f"{float(match[3]):.2f}")
            limits = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", match[1])]
            add(f"score_bounds_{grade}", json.dumps(limits))
    return facts


def run():
    flat = read_jsonl("data/interim/cleaned.jsonl")
    grouped = defaultdict(list)
    for row in flat:
        grouped[row["doc_id"]].append(row)
    manifest = {r["id"]: r for r in read_csv("data/processed/manifest.csv")}
    metadata = {s["id"]: {**s, "version": s.get("version", "web-" + manifest[s["id"]]["retrieved_at"][:7])} for s in sources()}
    sections = build_sections(grouped, metadata)
    write_jsonl("data/interim/documents_unredacted.jsonl", sections)
    # Course entries are scanned as a whole to keep prerequisites attached to headings.
    courses = []
    for sid in ("C1", "S1"):
        text_parts = []
        for row in grouped[sid]:
            for line in row["text"].splitlines():
                if ENTRY.match(line) and parse_course(line, sid, ""):
                    text_parts.append((line, row["page"] or row["anchor"] or f"block-{row['block']}"))
                elif text_parts:
                    old, locator = text_parts[-1]
                    text_parts[-1] = (old + "\n" + line, locator)
        for text, locator in text_parts:
            course = parse_course(text, sid, locator)
            if course:
                courses.append(course)
    # Retain source-specific records rather than merge incompatible editions silently.
    unique = {(c["source"], c["code"]): c for c in courses}
    courses = list(unique.values())
    write_csv("data/processed/courses.csv", courses, ["code", "title", "credits_theory", "credits_lab",
              "credits_total", "prerequisites", "prerequisite_expression", "prerequisite_status", "source",
              "locator", "has_alternatives"])
    edges = [{"from_course": p, "to_course": c["code"], "source": c["source"], "locator": c["locator"],
              "relation": "alternative" if c["has_alternatives"] else "prerequisite"}
             for c in courses for p in json.loads(c["prerequisites"])]
    write_csv("data/processed/prereq_edges.csv", edges, ["from_course", "to_course", "source", "locator", "relation"])
    known = {c["code"] for c in courses}
    dangling = sorted({e["from_course"] for e in edges} - known)
    rules = extract_rules(flat)
    write_jsonl("data/processed/rule_facts.jsonl", rules)
    conflicts = []
    compared, unmatched = [], []
    for rule in sorted({r["rule"] for r in rules}):
        old = [r for r in rules if r["rule"] == rule and r["source"] == "S1"]
        current = [r for r in rules if r["rule"] == rule and r["source"] == "W1"]
        bulletin, web = sorted({r["value"] for r in old}), sorted({r["value"] for r in current})
        if not bulletin or not web:
            unmatched.append(rule)
            continue
        compared.append(rule)
        if bulletin != web:
            conflicts.append({"rule": rule, "bulletin_value": " | ".join(bulletin), "web_value": " | ".join(web),
                              "bulletin_page": json.dumps(sorted({r["page"] for r in old if r["page"]})),
                              "web_url": metadata["W1"]["url"], "status": "extracted_discrepancy_verify_effective_date"})
    write_csv("data/processed/conflicts.csv", conflicts,
              ["rule", "bulletin_value", "web_value", "bulletin_page", "web_url", "status"])
    record("structure", {"sections": len(sections), "sections_by_source": dict(Counter(s["doc_id"] for s in sections)),
                         "courses": len(courses), "courses_by_source": dict(Counter(c["source"] for c in courses)),
                         "edges": len(edges), "dangling_references": dangling,
                         "unresolved_prerequisites": sum(c["prerequisite_status"] == "unresolved" for c in courses),
                         "candidate_conflicts": conflicts,
                         "compared_rules": compared, "unmatched_rules": unmatched,
                         "conflict_coverage": "Explicit undergraduate probation thresholds, dismissal, grade points/score bounds and retake facts; effective dates require human review."})
