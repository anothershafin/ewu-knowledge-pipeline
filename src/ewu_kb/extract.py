from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from .common import ROOT, read_csv, record, sources, write_jsonl


COURSE = re.compile(r"\b([A-Z]{2,4})\s?(\d{3}[A-Z]?)\s*[:\-]\s*(.+)")


def html_blocks(payload, sid):
    soup = BeautifulSoup(payload, "html.parser")
    for item in soup.select("script, style, nav, footer, header, noscript, .breadcrumb, .breadcrumbs"):
        item.decompose()
    # Selectors are checked against actual source structure during collection.
    for item in soup.select(".kingster-navigation, .kingster-mobile-menu, .sidebar, aside, form"):
        item.decompose()
    candidates = soup.select("main, article, .page-content-section, .page-content, .entry-content, .content-area, #main-content")
    content = max(candidates, key=lambda t: len(t.get_text()), default=soup.body or soup)
    columns = content.select(".col-md-8")
    roots = [content]
    if columns:
        primary = max(columns, key=lambda t: len(t.get_text()))
        # Some official pages place a second full-width table below the main
        # column. Keep this article supplement without including the sidebar.
        roots = [primary] + [tag for tag in content.select(".bottom-body")
                             if tag is not primary and primary not in tag.parents
                             and not any(parent in content.select(".bottom-body") for parent in tag.parents)]
    rows = []
    for tag in [tag for root in roots for tag in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table", "summary"])]:
        if tag.find_parent(["table", "p", "li"]):
            continue
        text = tag.get_text(" ", strip=True)
        if not text:
            continue
        anchor = tag.get("id") or (tag.parent.get("id") if isinstance(tag.parent, Tag) else None)
        rows.append({"doc_id": sid, "page": None, "block": len(rows) + 1, "kind": tag.name,
                     "text": text, "anchor": anchor or "", "spans": [], "table": (
                         [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                          for tr in tag.find_all("tr")] if tag.name == "table" else [])})
    # Some department pages use div text nodes rather than paragraphs.
    if sum(len(r["text"]) for r in rows) < 300:
        text = "\n\n".join(root.get_text("\n", strip=True) for root in roots)
        rows = [{"doc_id": sid, "page": None, "block": 1, "kind": "div", "text": text,
                 "anchor": "", "spans": [], "table": []}]
    return rows


def pdf_pages(path, sid):
    try:
        import fitz
    except ImportError:
        return poppler_pages(path, sid)
    result = []
    with fitz.open(path) as document:
        for index, page in enumerate(document):
            spans = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        spans.append({"text": span["text"], "size": round(span["size"], 2),
                                      "bold": bool(span["flags"] & 16), "bbox": list(span["bbox"])})
            result.append({"doc_id": sid, "page": index + 1, "block": None, "kind": "pdf",
                           "text": page.get_text(sort=True), "spans": spans, "anchor": "", "table": []})
    return result


def poppler_pages(path, sid):
    """Documented extraction fallback while PyMuPDF is unavailable; font heights are estimates."""
    import subprocess
    output = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"], check=True, capture_output=True).stdout
    pages = output.decode("utf-8").split("\f")
    if not pages[-1].strip():
        pages.pop()
    rows = []
    for index, text in enumerate(pages, 1):
        rows.append({"doc_id": sid, "page": index, "block": None, "kind": "pdf", "text": text,
                     "spans": [], "anchor": "", "table": [], "backend": "pdftotext-fallback-no-font-metadata"})
    return rows


def run():
    manifest = {r["id"]: r for r in read_csv("data/processed/manifest.csv")}
    rows, counts, scanned, empty = [], {}, [], []
    for source in sources():
        sid = source["id"]
        if manifest.get(sid, {}).get("status") != "200":
            raise RuntimeError(f"Missing successful input {sid}")
        path = ROOT / f"data/raw/{sid}.{source['type']}"
        extracted = pdf_pages(path, sid) if source["type"] == "pdf" else html_blocks(path.read_bytes(), sid)
        if not extracted or not any(r["text"].strip() for r in extracted):
            empty.append(sid)
            counts[sid] = 0
            continue
        counts[sid] = len(extracted)
        for row in extracted:
            if row["kind"] == "pdf" and len(row["text"].strip()) < 40:
                scanned.append({"doc_id": sid, "page": row["page"]})
        rows.extend(extracted)
    write_jsonl("data/interim/pages.jsonl", rows)
    record("extract", {"units_by_source": counts, "units": len(rows), "possibly_scanned": scanned,
                       "empty_sources_quarantined": empty, "status": "needs_review" if empty else "complete",
                       "fallback_units": sum("backend" in r for r in rows)})
