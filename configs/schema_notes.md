# Data contracts

All JSON Lines files are UTF-8, one object per line. All CSVs have headers. A source ID refers to `sources.yaml`. Physical PDF page numbers start at 1. HTML pages use null page fields and 1-based block locators. Dates are ISO 8601 with the Asia/Dhaka offset. Empty fields represent missing values, not zero.

| Artifact | Contract |
|---|---|
| manifest.csv | One source snapshot: id, URL/final URL, retrieval timestamp, HTTP status, byte count, SHA256, content type and error |
| pages.jsonl | PDF page or HTML block: doc_id, page/block, kind, text, font spans, table cells, anchor |
| documents.jsonl | Redacted section: section_id, section_path, source/version, physical page range, ordered source fragments, text, topic, pii_filtered and detector fingerprint |
| courses.csv | One code per source edition: title, theory/lab/total credits, JSON prerequisite-code list, original prerequisite expression, parse status, locator and alternatives flag |
| prereq_edges.csv | Source-specific prerequisite mention: prerequisite → course, source, locator, relation kind |
| rule_facts.jsonl | Explicit rule fact, source and page/block locator; no surrounding unrelated numbers |
| conflicts.csv | A specific rule with differing source values, source locators and an effective-date verification warning |
| pii_log.csv | Redaction with fragment-relative character offsets, type, detector, score and hashed value; no original value |
| chunks.jsonl | Stable ID, doc/section/version/URL, PDF pages or HTML blocks, topic, redacted text, token count and detector fingerprint |
| run_record.json | Timestamp, interpreter, package/model versions, model commit revisions, configuration, input and source-code hashes |

PII offsets refer to original fragment strings. Private review offsets refer to the exact concatenated review-page text and its checksum. Chunk identifiers hash source ID, source edition and redacted passage; duplicate text within one source/edition keeps its first citation. The index fingerprint covers all metadata and text, so locator or label changes invalidate index reuse.

Section records also carry `index_eligible` and `curation_reason`. Explicit personnel-roster and bibliography heading rules exclude those bulletin sections from student search while retaining them for the private redaction audit. Course-code paths supply a course-topic hint; a course such as corporate governance is not excluded merely because of its subject.

Raw sources and unredacted intermediate sections remain in ignored local storage. Only privacy-filtered sections are accepted for chunking, and only privacy-filtered chunks are accepted for indexing. The flags prove that the detector ran, not that its recall is perfect.
