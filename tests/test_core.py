import pytest

from ewu_kb.clean import clean_text, repeated_margins
from ewu_kb.pii import redact, regex_entities, resolve_spans
from ewu_kb.structure import parse_course
from ewu_kb.evaluate import relevant, retrieval_metrics, span_metrics
from ewu_kb.graph import build_graph, query


def test_cleaning_preserves_meaning():
    pages = [{"text": f"EWU Bulletin\nDifferent content {n}\n{n}"} for n in range(1, 5)]
    repeated = repeated_margins(pages)
    assert "EWU Bulletin" in repeated
    text, _ = clean_text("EWU Bulletin\nregis-\ntration full-time\nA unique line\n27", repeated)
    assert text == "registration full-time\nA unique line"
    assert clean_text("full-\ntime and regis-\ntration")[0] == "full-time and registration"


def test_course_parser_and_none():
    course = parse_course("CSE106: Discrete Mathematics\nCredits: 3\nPrerequisite: CSE103 Structured Programming", "C1", "b4")
    assert course["code"] == "CSE106"
    assert course["title"] == "Discrete Mathematics"
    assert course["prerequisites"] == '["CSE103"]'
    assert course["credits_total"] == "3"
    no_prereq = parse_course("CSE103: Structured Programming\nPrerequisite: None", "C1", "b1")
    assert no_prereq["prerequisites"] == "[]"
    assert no_prereq["prerequisite_status"] == "explicit_none"


def test_course_codes_joined_to_titles_and_credit_tables():
    course = parse_course("CSE106: Discrete Mathematics\nTheory Laboratory Total Credit Hours 3 0 3\nPrerequisite: CSE103Structured Programming", "C1", "b4")
    assert course["prerequisites"] == '["CSE103"]'
    assert course["credits_total"] == "3"
    assert parse_course("CSE103 Credit Hours and Teaching Scheme:", "C1", "") is None


def test_rule_extraction_distinguishes_undergraduate_and_graduate():
    from ewu_kb.structure import extract_rules
    text = "Student whose CGPA will be between 1 and 2.25 after the first two semesters. Graduate CGPA is 2.60. 75% to less than 80% A 3.75"
    facts = extract_rules([{"doc_id": "W1", "page": None, "block": 4, "text": text}])
    pairs = {r["rule"]: r["value"] for r in facts}
    assert pairs["undergraduate_probation_upper_cgpa"] == "2.25"
    assert pairs["grade_point_A"] == "3.75"


def test_html_sibling_headings_do_not_become_ancestors():
    from ewu_kb.structure import build_sections
    rows = {"W1": [{"kind": kind, "text": text, "page": None, "block": i, "anchor": "", "spans": []}
                    for i, (kind, text) in enumerate([("h1", "Rules"), ("h3", "Grades"),
                                                      ("p", "Grade details"), ("h3", "Probation"),
                                                      ("p", "Probation details")], 1)]}
    result = build_sections(rows, {"W1": {"category": "rules", "url": "https://example.org", "version": "web-test"}})
    probation = next(s for s in result if "Probation details" in s["text"])
    assert probation["section_path"] == "rules > Rules > Probation"


def test_html_full_width_fee_supplement_is_not_lost_with_sidebar():
    from ewu_kb.extract import html_blocks
    payload = ('<main><div class="col-md-8"><h2>Tuition</h2><p>' + 'Course fee details. ' * 30 +
               '</p></div><aside><p>Unrelated navigation</p></aside>'
               '<div class="col-md-12"><div class="bottom-body"><h3>Other fees</h3>'
               '<table><tr><td>Admission fee</td><td>25000</td></tr></table>'
               '</div></div></main>')
    rows = html_blocks(payload, "W3")
    text = " ".join(r["text"] for r in rows)
    assert "Admission fee 25000" in text
    assert "Unrelated navigation" not in text
    assert sum(r["kind"] == "table" for r in rows) == 1


def test_pdf_degree_credit_table_does_not_inherit_previous_course_heading():
    from ewu_kb.structure import build_sections
    title = "Credit Distribution and Courses for BS. In Applied Statistics"
    row = {"kind": "pdf", "page": 168, "block": None, "anchor": "", "spans": [
        {"text": title, "size": 10, "bold": True},
        {"text": "Credit", "size": 10, "bold": True},
        {"text": "Hours", "size": 10, "bold": True}],
        "text": "PHY107: General Physics\n\n" + title + "\nMinimum 127 credits\nCredit\nHours\nTotal 127"}
    result = build_sections({"S1": [row]}, {"S1": {"category": "bulletin", "url": "https://example.org", "version": "2019"}})
    table = next(s for s in result if "Total 127" in s["text"])
    assert table["section_path"] == "bulletin > " + title
    assert "Minimum 127 credits" in table["text"]
    assert not any(s["text"].strip() in ("Credit", "Hours") for s in result)


def test_pii_rules_do_not_redact_course_codes_or_years():
    text = "Test test@example.org +8801712345678 01712-345678 02-55668200 ID:2026-1-60-001 CSE103 2019"
    spans = resolve_spans(text, regex_entities(text))
    result = redact(text, spans)
    assert "test@example.org" not in result
    assert "01712-345678" not in result
    assert "02-55668200" not in result
    assert "2026-1-60-001" not in result
    assert "CSE103 2019" in result


def test_allowlist_applies_to_persons_and_overlap_is_resolved():
    text = "East West University test@example.org"
    candidates = [{"start": 0, "end": 20, "type": "PERSON", "detector": "ner", "score": .99}]
    candidates += regex_entities(text)
    spans = resolve_spans(text, candidates, ["East West University"])
    assert redact(text, spans) == "East West University [EMAIL]"
    partial = [{"start": 0, "end": 4, "type": "PERSON", "detector": "ner", "score": .99}]
    assert resolve_spans(text, partial, ["East West University"]) == []


def test_known_retrieval_metrics():
    result = retrieval_metrics([[False, True], [True], [False] * 5])
    assert result["Recall@1"] == pytest.approx(1 / 3)
    assert result["Recall@5"] == pytest.approx(2 / 3)
    assert result["MRR"] == .5
    assert retrieval_metrics([])["MRR"] is None


def test_exact_span_metrics():
    result = span_metrics({("p", 1, 4, "PERSON")}, {("p", 1, 4, "PERSON"), ("p", 8, 12, "EMAIL")})
    assert result["precision"] == .5 and result["recall"] == 1
    assert span_metrics([], [])["precision"] is None


def test_delegated_preparation_is_not_independent_human_verification():
    from ewu_kb.evaluate import pii_reference_review
    pages = [{"reviewed": "yes", "reviewer": "AI-assisted (on behalf of Reviewer)"},
             {"reviewed": "yes", "reviewer": "Reviewer"}]
    annotations = [{"reviewer": "Reviewer"}, {"reviewer": "AI-assisted (on behalf of Reviewer)"}]
    review = pii_reference_review(pages, annotations)
    assert not review["independent_human_review"]
    assert review["independent_human_reviewed_pages"] == 1
    assert review["assistant_prepared_spans"] == 1
    # A later explicit page review can establish human verification while retaining
    # the history of who prepared the original spans.
    pages[0]["reviewer"] = "Reviewer"
    assert pii_reference_review(pages, annotations)["independent_human_review"]
    assert not pii_reference_review([], [])["independent_human_review"]


def test_page_relevance_requires_source_and_locator():
    result = {"doc_id": "S1", "page_start": 10, "page_end": 12, "section_path": "rules > grades"}
    assert relevant(result, {"expected_doc": "S1", "expected_page": "11"})
    assert not relevant(result, {"expected_doc": "W1", "expected_page": "11"})
    assert not relevant(result, {"expected_doc": "S1", "expected_page": "13"})


def test_duplicate_html_headings_require_the_correct_section_id():
    expected = {"expected_doc": "W5", "expected_section": "calendar > Undergraduate",
                "expected_section_id": "undergraduate-2026"}
    result = {"doc_id": "W5", "section_path": "calendar > Undergraduate", "section_id": "undergraduate-2025"}
    assert not relevant(result, expected)
    result["section_id"] = "undergraduate-2026"
    assert relevant(result, expected)
    expected["expected_section_id"] += "|undergraduate-2024"
    result["section_id"] = "undergraduate-2024"
    assert relevant(result, expected)


def test_delegated_question_review_keeps_actual_provenance():
    from ewu_kb.evaluate import question_reference_review
    rows = [{"reviewed": "yes", "reviewer": "AI-assisted (on behalf of Reviewer)"}]
    assert not question_reference_review(rows)["independent_human_review"]
    rows[0]["reviewer"] = "Reviewer"
    assert question_reference_review(rows)["independent_human_review"]


def test_topic_quality_exclusions_cannot_discard_unknown_or_unexplained_rows():
    from ewu_kb.evaluate import scorable_topic_rows
    rows = [{"chunk_id": "passage"}, {"chunk_id": "header"}]
    assert scorable_topic_rows(rows, [{"chunk_id": "header", "reason": "Detached table header without context"}]) == rows[:1]
    with pytest.raises(ValueError, match="known chunk"):
        scorable_topic_rows(rows, [{"chunk_id": "unknown", "reason": "Unknown identifier"}])
    with pytest.raises(ValueError, match="recorded data-quality reason"):
        scorable_topic_rows(rows, [{"chunk_id": "header", "reason": ""}])


def test_graph_ancestors_and_cycle():
    import networkx as nx
    graph = nx.DiGraph([("A", "B"), ("B", "C"), ("A", "D")])
    for n in graph:
        graph.nodes[n]["title"] = n
    assert query(graph, "C") == ["A", "B"]
    assert query(graph, "A", "unlocks") == ["B", "C", "D"]
    graph.add_edge("B", "A")
    with pytest.raises(ValueError, match="cycles"):
        query(graph, "C")


class TinyTokenizer:
    def __call__(self, text, **kwargs):
        import re
        offsets = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
        return {"offset_mapping": offsets}

    def encode(self, text, add_special_tokens=False):
        return list(range(len(text.split()) + (2 if add_special_tokens else 0)))


def test_chunk_boundaries_page_provenance_and_stable_ids():
    from ewu_kb.chunk import make_chunks
    base = {"doc_id": "S1", "source_version": "v1", "source_url": "https://example.org",
            "topic": "other", "pii_filtered": True, "pii_fingerprint": "abc"}
    documents = [{**base, "section_id": "a", "section_path": "First", "fragments": [
        {"page": 1, "block": None, "text": "one two three four"},
        {"page": 2, "block": None, "text": "five six seven eight"}]},
        {**base, "section_id": "b", "section_path": "Second", "fragments": [
            {"page": 3, "block": None, "text": "nine ten eleven twelve"}]}]
    a = make_chunks(documents, TinyTokenizer(), 5, 1)
    b = make_chunks(documents, TinyTokenizer(), 5, 1)
    assert a == b
    assert all(r["page_start"] and r["page_end"] for r in a)
    assert all(not ("eight" in r["text"] and "nine" in r["text"]) for r in a)
    assert any(r["page_start"] == 1 and r["page_end"] == 2 for r in a)


def test_unfiltered_input_is_rejected():
    from ewu_kb.chunk import make_chunks
    with pytest.raises(ValueError, match="unfiltered"):
        make_chunks([{"pii_filtered": False}], TinyTokenizer(), 5, 1)
    assert make_chunks([{"pii_filtered": True, "index_eligible": False}], TinyTokenizer(), 5, 1) == []


def test_detector_cache_hash_ignores_formatting_but_tracks_code(tmp_path):
    from ewu_kb.common import semantic_code_sha
    path = tmp_path / "code.py"
    path.write_text("x = 1\n")
    first = semantic_code_sha(path)
    path.write_text("# formatting\nx=1\n\n")
    assert first == semantic_code_sha(path)
    path.write_text("x=2\n")
    assert first != semantic_code_sha(path)


def _person(text, fragment, occurrence=0):
    start = -1
    for _ in range(occurrence + 1):
        start = text.index(fragment, start + 1)
    return {"start": start, "end": start + len(fragment), "type": "PERSON", "detector": "ner", "score": .95}


def test_person_fragments_expand_to_whole_names():
    from ewu_kb.pii import repair_person_spans
    text = "Committee: Mr. Abul Kalam Rahim Member Secretary"
    spans = repair_person_spans(text, [_person(text, "Ka"), _person(text, "him")])
    assert [text[s["start"]:s["end"]] for s in spans] == ["Abul Kalam Rahim"]
    assert redact(text, spans) == "Committee: Mr. [PERSON] Member Secretary"


def test_honorific_and_initials_are_kept_with_the_name():
    from ewu_kb.pii import repair_person_spans
    text = "Chairperson Dr. Md. Karim Uddin, Department of Physics"
    spans = repair_person_spans(text, [_person(text, "Kar")])
    assert text[spans[0]["start"]:spans[0]["end"]] == "Md. Karim Uddin"


def test_technical_eponyms_are_not_personal_data():
    from ewu_kb.pii import repair_person_spans
    text = "Apply Norton's theorem, a Voronoi diagram and the Laplace transform."
    candidates = [_person(text, "Nor"), _person(text, "V"), _person(text, "Laplace")]
    assert repair_person_spans(text, candidates) == []


def test_name_completion_stops_at_role_words():
    from ewu_kb.pii import repair_person_spans
    text = "Ms. Nasrin Akter Chairperson"
    spans = repair_person_spans(text, [_person(text, "Nasrin")])
    assert text[spans[0]["start"]:spans[0]["end"]] == "Nasrin Akter"
    assert redact(text, resolve_spans(text, spans)) == "Ms. [PERSON] Chairperson"


def test_roster_like_passages_are_excluded_from_search():
    from ewu_kb.chunk import make_chunks, roster_like
    roster = "Members: Mr. [PERSON] Member, Ms. [PERSON] Member, Dr. [PERSON] Member, Mr. [PERSON] Secretary"
    policy = "A student may submit a grievance in writing. The committee chaired by [PERSON] reviews it within ten days."
    assert roster_like(roster) and not roster_like(policy)
    base = {"doc_id": "P4", "source_version": "v1", "source_url": "https://example.org", "topic": "grievance",
            "pii_filtered": True, "pii_fingerprint": "abc"}
    documents = [{**base, "section_id": "r", "section_path": "Members", "fragments": [{"page": 1, "block": None, "text": roster}]},
                 {**base, "section_id": "p", "section_path": "Procedure", "fragments": [{"page": 2, "block": None, "text": policy}]}]
    stats = {}
    rows = make_chunks(documents, TinyTokenizer(), 50, 5, roster_filter={"min_tags": 4, "min_density": 4.0}, stats=stats)
    assert [r["section_id"] for r in rows] == ["p"]
    assert stats["roster_like_passages_excluded"] == 1


def test_roster_filter_does_not_remove_course_descriptions():
    from ewu_kb.chunk import make_chunks
    text = "Theorists: [PERSON], [PERSON], [PERSON] and [PERSON] on social change"
    document = {"doc_id": "S1", "source_version": "v1", "source_url": "https://example.org", "topic": "course_info",
                "pii_filtered": True, "pii_fingerprint": "abc", "section_id": "c", "section_path": "SOC 101",
                "fragments": [{"page": 1, "block": None, "text": text}]}
    rows = make_chunks([document], TinyTokenizer(), 50, 5, roster_filter={"min_tags": 4, "min_density": 4.0})
    assert len(rows) == 1
