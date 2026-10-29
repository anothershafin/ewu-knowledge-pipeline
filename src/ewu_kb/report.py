from __future__ import annotations

import html
import json

from .common import ROOT, load_stats, now, read_csv, write_json


def table(rows):
    if not rows:
        return '<p class="muted">No records.</p>'
    fields = list(rows[0])
    return '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{html.escape(str(k))}</th>' for k in fields) + '</tr></thead><tbody>' + ''.join(
        '<tr>' + ''.join(f'<td>{html.escape(str(row.get(k, "")))}</td>' for k in fields) + '</tr>' for row in rows) + '</tbody></table></div>'


def run():
    import matplotlib.pyplot as plt
    collect, extract, clean, structure, pii, graph, evaluation = [load_stats(s) for s in (
        "collect", "extract", "clean", "structure", "pii", "graph", "evaluate")]
    chunk = load_stats("chunk_300")
    curation = load_stats("annotate")
    by_topic = chunk.get("by_topic", {})
    if by_topic:
        fig, ax = plt.subplots(figsize=(10, 6))
        labels, values = zip(*sorted(by_topic.items(), key=lambda p: p[1]))
        ax.barh(labels, values, color="#2563eb")
        ax.set_xlabel("Redacted chunks")
        ax.set_title("Corpus coverage by automatic topic label")
        fig.tight_layout()
        fig.savefig(ROOT / "reports/figures/topics.png", dpi=150)
        plt.close(fig)
    retrieval = evaluation.get("retrieval", {})
    privacy_evaluation = evaluation.get("pii", {})
    topic_evaluation = evaluation.get("annotation", {})
    def percentage(value):
        return f"{value:.1%}" if value is not None else "not defined"
    if retrieval.get("status") == "complete":
        rows = retrieval["experiments"]
        fig, ax = plt.subplots(figsize=(8, 5))
        labels = [f"{r['model']} / {r['nominal_size']}\n(max {min(r['nominal_size'], chunk.get('effective_cap', r['nominal_size']))} tokens)" for r in rows]
        bars = ax.bar(labels, [r["Recall@5"] for r in rows], color="#2563eb")
        ax.bar_label(bars, labels=[f"{round(r['Recall@5'] * r['n'])}/{r['n']}\n{r['Recall@5']:.1%}" for r in rows], padding=4)
        ax.set(ylim=(0, 1), ylabel="Recall@5 (question hit rate)", title="Frozen-question retrieval evaluation")
        fig.tight_layout()
        fig.savefig(ROOT / "reports/figures/retrieval.png", dpi=150)
        plt.close(fig)
    cards = [("Sources", collect.get("successful", "pending")), ("Extracted units", extract.get("units", "pending")),
             ("Sections", structure.get("sections", "pending")), ("Chunks", chunk.get("chunks", "pending")),
             ("Course records", structure.get("courses", "pending")), ("Redactions", pii.get("redactions", "pending"))]
    evaluation_complete = all(evaluation.get(key, {}).get("status") == "complete" for key in ("annotation", "pii", "retrieval"))
    evaluation_note = ("Topic-label, PII-reference and frozen-question evaluations are complete. Interpret the results with the preparation, review, sampling and tuning limitations below."
                       if evaluation_complete else "Some reference annotations or frozen source answers are still pending. Completed results below state how their references were prepared and reviewed.")
    sections = []
    summaries = {
        "Extraction and cleaning": f"{extract.get('units', 'Pending')} extracted units; {len(extract.get('empty_sources_quarantined', []))} empty source panel(s) quarantined. {clean.get('before_chars', 0):,} → {clean.get('after_chars', 0):,} characters after cleaning.",
        "Structure and version checks": f"{structure.get('sections', 'Pending')} sections; {structure.get('courses', 'pending')} source-specific course records; {len(structure.get('compared_rules', []))} rule facts compared and {len(structure.get('candidate_conflicts', []))} discrepancies flagged.",
        "Privacy filtering": f"{pii.get('redactions', 'Pending')} redactions. Span metrics and reference-review details appear in the PII evaluation.",
        "Student-search curation": f"{curation.get('excluded_sections', 'Pending')} personnel or bibliography sections excluded from search, plus {chunk.get('roster_like_passages_excluded', 0)} passages that were mostly redacted names. They remain local for the PII audit.",
        "Annotation quality": (f"Agreement {percentage(topic_evaluation.get('agreement'))} on {topic_evaluation.get('n')} scorable passages from the {topic_evaluation.get('raw_n')} reviewed entries. Exclusions and review provenance are recorded below."
                               if topic_evaluation.get('status') == 'complete' else topic_evaluation.get('status', 'Pending labels')),
        "PII evaluation": ((f"Current detector (with name-boundary repair): exact-span precision {percentage(privacy_evaluation['current_detector']['all']['precision'])}; recall {percentage(privacy_evaluation['current_detector']['all']['recall'])}. " if privacy_evaluation.get('current_detector') else "")
                           + f"Original ingestion snapshot: precision {percentage(privacy_evaluation.get('all', {}).get('precision'))}; recall {percentage(privacy_evaluation.get('all', {}).get('recall'))}. Both are scored against the same prepared reference on the same pages, so the repaired result is not a held-out estimate. Missed names still limit anonymization; preparation details are recorded below."
                           if privacy_evaluation.get('status') == 'complete' else privacy_evaluation.get('status', 'Pending span labels')),
        "Retrieval evaluation": retrieval.get('status', 'Pending frozen source answers'),
        "Prerequisite graph checks": f"{graph.get('nodes', 'Pending')} nodes and {graph.get('edges', 'pending')} edges; {len(graph.get('cycles', []))} cycle(s); {len(graph.get('unresolved', []))} unresolved reference(s)."
    }
    for title, stage in (("Extraction and cleaning", {"extraction": extract, "cleaning": clean}),
                         ("Structure and version checks", structure), ("Student-search curation", curation), ("Privacy filtering", pii),
                         ("Annotation quality", evaluation.get("annotation", {})),
                         ("PII evaluation", evaluation.get("pii", {})), ("Retrieval evaluation", retrieval),
                         ("Prerequisite graph checks", graph)):
        extra = table([{"Model": r["model"], "Nominal tokens": r["nominal_size"],
                        "Max content tokens": min(r["nominal_size"], chunk.get("effective_cap", r["nominal_size"])),
                        "Questions": r["n"], "Recall@1": percentage(r["Recall@1"]),
                        "Recall@5": percentage(r["Recall@5"]), "MRR@20": f"{r['MRR']:.4f}"}
                       for r in retrieval["experiments"]]) if title == "Retrieval evaluation" and retrieval.get("experiments") else ""
        sections.append(f'<section><h2>{title}</h2><p>{html.escape(summaries[title])}</p>{extra}<details><summary>Inspect measurements and checks</summary><pre>{html.escape(json.dumps(stage, indent=2, ensure_ascii=False))}</pre></details></section>')
    manifest_rows = [{"Source": r["id"], "HTTP": r["status"], "Size (KB)": round(int(r["bytes"]) / 1024, 1),
                      "Retrieved (Dhaka)": r["retrieved_at"], "SHA256 prefix": r["sha256"][:16]}
                     for r in read_csv("reports/manifest.csv")]
    images = ''.join(f'<section><h2>{title}</h2><a href="figures/{filename}" aria-label="Open full-size figure"><img src="figures/{filename}" alt="{alt}"></a><p class="muted">Select the figure to view it at full size.</p></section>'
                     for filename, title, alt in (("topics.png", "Topic coverage", "Chunks by automatic topic"),
                                                  ("prerequisite_graph.png", "CSE prerequisite references", "Directed prerequisite reference graph"),
                                                  ("retrieval.png", "Frozen-question evaluation", "Recall at five by model and chunk setting"))
                     if (ROOT / "reports/figures" / filename).exists())
    body = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>EWU Knowledge Pipeline | Quality report</title>
<style>:root{{color-scheme:light}}*{{box-sizing:border-box}}body{{margin:0;background:#f1f5f9;color:#172033;font:16px/1.6 system-ui,sans-serif}}main{{max-width:1180px;margin:auto;padding:40px 24px}}h1{{font-size:38px;line-height:1.15;letter-spacing:-1px}}h2{{font-size:23px}}.eyebrow{{color:#2563eb;font-weight:700}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}.card,section{{background:white;border:1px solid #dbe3ed;border-radius:12px;padding:24px;margin:20px 0}}.card strong{{display:block;font-size:32px}}.notice{{background:#fff7df;border-left:4px solid #d97706;padding:20px;border-radius:6px}}.muted{{color:#536174}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;background:#f8fafc;padding:18px;border-radius:6px}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;min-width:720px;font-size:13px}}th,td{{padding:12px;text-align:left;border-bottom:1px solid #e2e8f0;vertical-align:top;overflow-wrap:anywhere;max-width:450px}}th{{background:#eaf0f8}}img{{max-width:100%;height:auto}}a{{color:#1d4ed8}}@media(max-width:650px){{.cards{{grid-template-columns:repeat(2,1fr)}}h1{{font-size:29px}}main{{padding:24px 14px}}section{{padding:16px}}}}</style></head><body><main>
<p class="eyebrow">PUBLIC DOCUMENTS · TRACEABLE SOURCES · MEASURED QUALITY</p><h1>EWU Knowledge Base Pipeline</h1><p class="muted">Independent research project · generated {now()}</p>
<p>A reproducible data layer for institutional search: collection, structured extraction, privacy filtering, semantic retrieval and prerequisite references.</p>
<div class="notice"><strong>Evaluation status</strong><br>{evaluation_note} Automated extraction and graph counts are descriptive checks. Rule discrepancies require official effective-date review.</div>
<div class="cards">{''.join(f'<div class="card">{label}<strong>{value}</strong></div>' for label, value in cards)}</div>
<section><h2>Source manifest</h2><p><a href="manifest.csv">Full manifest with official URLs and complete checksums</a></p>{table(manifest_rows)}</section>
{''.join(sections)}
{images}
<section><h2>Limitations and provenance</h2><p>Web retrieval dates do not establish policy effective dates. PDF page numbers are physical PDF pages. Regex and English NER may miss personal data; redaction is not a guarantee of anonymization. The nominal 300-token experiment uses a shared content cap of 254 to respect MiniLM's default input limit. No chatbot or generated answer is included.</p><p>Source materials remain local and are not redistributed. See the manifest, model revision lock and run records for reproducibility. This project is not affiliated with East West University.</p></section>
</main></body></html>'''
    (ROOT / "reports/quality_report.html").write_text(body, encoding="utf-8")
    summary = {"generated_at": now(), "collection": collect, "structure": structure, "chunks": chunk,
               "pii": pii, "graph": graph, "evaluation": evaluation}
    write_json("reports/summary.json", summary)
    print("reports/quality_report.html generated")
