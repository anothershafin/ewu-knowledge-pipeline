from __future__ import annotations

from collections import Counter

from .common import ROOT, config, read_jsonl, record, revision, sha, write_jsonl


def windows(text, tokenizer, size, overlap):
    encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, truncation=False)
    offsets = encoded["offset_mapping"]
    if not offsets:
        return
    step = size - overlap
    if step <= 0:
        raise ValueError("Overlap must be smaller than chunk size")
    for first in range(0, len(offsets), step):
        last = min(first + size, len(offsets))
        start, end = offsets[first][0], offsets[last - 1][1]
        yield start, end, text[start:end]
        if last == len(offsets):
            break


def make_chunks(documents, tokenizer, size, overlap, validators=()):
    rows, seen = [], set()
    for document in documents:
        if not document.get("pii_filtered"):
            raise ValueError("Refusing to chunk an unfiltered document")
        if not document.get("index_eligible", True):
            continue
        text, boundaries, cursor = "", [], 0
        for fragment in document["fragments"]:
            if text:
                text += "\n\n"
                cursor += 2
            text += fragment["text"]
            boundaries.append((cursor, cursor + len(fragment["text"]), fragment))
            cursor += len(fragment["text"])
        for start, end, value in windows(text, tokenizer, size, overlap):
            # A secondary tokenizer can tokenize differently. Split again, never truncate.
            pieces = [(start, end, value)]
            for validator, limit in validators:
                revised = []
                for p_start, p_end, p_text in pieces:
                    if len(validator.encode(p_text, add_special_tokens=False)) <= limit:
                        revised.append((p_start, p_end, p_text))
                    else:
                        for v_start, v_end, v_text in windows(p_text, validator, limit, min(overlap, limit // 4)):
                            revised.append((p_start + v_start, p_start + v_end, v_text))
                pieces = revised
            for begin, finish, passage in pieces:
                # Deduplicate within source/version so independent source citations survive.
                key = sha(document["doc_id"] + document["source_version"] + passage)
                if key in seen:
                    continue
                seen.add(key)
                fragments = [f for a, b, f in boundaries if a < finish and b > begin]
                pages = [f["page"] for f in fragments if f["page"]]
                blocks = [f["block"] for f in fragments if f["block"]]
                rows.append({"chunk_id": key[:32], "doc_id": document["doc_id"],
                             "section_id": document["section_id"], "section_path": document["section_path"],
                             "page_start": min(pages) if pages else None, "page_end": max(pages) if pages else None,
                             "block_start": min(blocks) if blocks else None, "block_end": max(blocks) if blocks else None,
                             "topic": document["topic"], "source_version": document["source_version"],
                             "source_url": document["source_url"], "text": passage,
                             "n_tokens": len(tokenizer.encode(passage, add_special_tokens=False)),
                             "nominal_chunk_size": size, "pii_filtered": True,
                             "pii_fingerprint": document["pii_fingerprint"]})
    return rows


def run(size=300):
    from transformers import AutoTokenizer
    settings = config()
    tokenizers = {key: AutoTokenizer.from_pretrained(settings["models"][key]["name"], revision=revision(key))
                  for key in ("bge", "minilm")}
    cap = min(size, settings["chunking"]["shared_content_cap"])
    rows = make_chunks(read_jsonl("data/processed/documents.jsonl"), tokenizers["bge"], cap,
                       settings["chunking"]["overlap"], [(tokenizers["minilm"], cap)])
    if not rows:
        raise ValueError("No chunks produced")
    for row in rows:
        row["nominal_chunk_size"] = size
        row["effective_token_cap"] = cap
    write_jsonl(f"data/processed/chunks_{size}.jsonl", rows)
    if size == 300:
        write_jsonl("data/processed/chunks.jsonl", rows)
    for row in rows:
        for tokenizer in tokenizers.values():
            assert len(tokenizer.encode(row["text"], add_special_tokens=True)) <= 256
    record(f"chunk_{size}", {"chunks": len(rows), "nominal_size": size, "effective_cap": cap,
                              "max_bge_tokens": max(r["n_tokens"] for r in rows),
                              "by_topic": dict(Counter(r["topic"] for r in rows)),
                              "by_source": dict(Counter(r["doc_id"] for r in rows))})
