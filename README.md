# EWU Knowledge Base Pipeline

A reproducible knowledge engineering pipeline for East West University's public academic documents. It collects and structures sources, filters personal information, indexes passages for semantic search and exports a course-prerequisite reference graph. Search returns cited passages; it does not generate answers.

**Independent research project. Not affiliated with East West University.** University documents retain their original rights and are not redistributed in this repository.

## Current build status

The automated build, four indexes and source-reference evaluation are complete locally. **BGE-small retrieved an accepted source in its top five results for 34 of 40 frozen questions (85%) at both chunk settings.** After a name-boundary repair, person-name redaction reaches 47.2% exact-span precision and 42.9% recall on the 24-page reference, up from 17.5% and 21.4%. The topic sample was labeled by the project owner and adjudicated with assistance; the PII and retrieval references were prepared with AI assistance on the owner's behalf. These are small, source-specific measurements, with review provenance and limitations reported explicitly.

| Measured artifact | Count |
|---|---:|
| Collected public source URLs | 17 |
| Sources with usable content | 16 |
| PDF pages (bulletin + four policies) | 556 |
| Structured sections | 3,071 |
| Sections excluded from student search | 599 |
| Roster-like passages excluded from search (200 / 300 setting) | 12 / 8 |
| Curated chunks, 200-token setting | 3,146 |
| Curated chunks, nominal 300 / effective 254 setting | 2,842 |
| Detected body redaction events | 1,796 |
| CSE catalogue courses | 46 |
| Current prerequisite graph nodes / edges | 48 / 40 |
| Explicit source-rule comparisons / differences | 26 / 19 |
| Passing fixture tests | 26 |

The admissions FAQ URL returns an empty main content panel in this snapshot and is quarantined. The graph includes two unresolved reference nodes. Counts describe the snapshot and automated processing; they are not correctness estimates. See [the quality report](reports/quality_report.html), [integration checks](reports/integration_checks.json) and [model integrity checks](reports/model_integrity.json). [GitHub Actions](https://github.com/anothershafin/ewu-knowledge-pipeline/actions/workflows/checks.yml) verifies the fixture tests on Linux without model weights or source downloads; the [first published check passed](https://github.com/anothershafin/ewu-knowledge-pipeline/actions/runs/40816690858).

## What it demonstrates

- Cached, rate-limited collection with robots checks, timestamps and SHA256 manifests.
- PDF page and font metadata extraction; HTML headings, lists, tables and FAQ structure.
- Cleaning counts and suspicious-loss warnings, section paths and page-level provenance.
- Course and prerequisite parsing with source editions kept separate and unresolved references exposed.
- Regex and Hugging Face Transformers person-name detection before chunking or vector indexing.
- Rule-based topic labels and a genuine manual annotation workflow.
- Normalized embeddings from BGE-small and MiniLM in persistent Chroma collections.
- A fixed-question retrieval protocol; automatic quality report and NetworkX/Neo4j exports.

## Setup on Windows

Use Python 3.12. Everything runs in an isolated project environment; no global Python packages are changed. Allow at least 10 GB for a fresh CUDA environment, models and data; an environment copied from other research work can be larger. All caches and temporary model files stay in `.cache/`.

| Purpose | Published model | License |
|---|---|---|
| Main embeddings | [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) | MIT |
| Comparison embeddings | [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | Apache 2.0 |
| Person-name detection | [dslim/bert-base-NER](https://huggingface.co/dslim/bert-base-NER) | MIT |

The English NER model was trained on CoNLL-2003. Its published benchmark scores do not measure privacy detection on these university documents; the local human span review is essential.

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1 run-all
```

The setup script installs a CUDA 12.8 PyTorch build for the RTX 50 series. Pass `-Python C:\path\to\python.exe` to supply a Python 3.12 executable. For CPU use, pass `-Cpu` and change `device: cpu` in `configs/pipeline.yaml`. GPU commands refuse to run outside this project's `.env-gpu` environment. `scripts/run.ps1` always selects that interpreter. The local build uses an isolated copy of a Python 3.12 environment with PyTorch 2.11.0+cu128; its GPU multiplication check passed on the RTX 5060 Ti. Fresh installations should use the recorded dependency lock for matching package versions.

## Stages

Each stage can be run independently with `scripts/run.ps1 <command>`:

| Command | Output |
|---|---|
| `collect` | Local source cache and manifest; one request per three seconds, both EWU domains checked |
| `extract` | Physical PDF pages/font spans or HTML blocks |
| `clean` | Normalized text, repeated-margin removal and loss flags |
| `structure` | Sections, course records, prerequisite references and rule discrepancy candidates |
| `pii` | Redacted sections, hashed audit log and local detector predictions |
| `annotate` | Fixed-taxonomy topic labels |
| `chunk --size 300` | Source-linked redacted passage records (also supports 200) |
| `embed --model bge --size 300` | Persistent Chroma index (also `minilm`, and size 200) |
| `review` | 100 topic-label tasks, 24 PII pages, 40 unanswered draft questions |
| `freeze-questions` | Immutable lock for human-reviewed gold questions |
| `evaluate` | Annotation, PII and retrieval metrics, or explicit pending states |
| `graph` | Directed reference graph, source-linked CSV and Neo4j import script |
| `report` | `reports/quality_report.html`, figures and machine-readable summary |
| `validate` | Actual input checksums, privacy flags, source locators, index IDs/counts, model hashes and fixture tests |

`run-all` executes the complete automated sequence, both models and both chunk sizes, and prepares manual review without filling in human answers. Collection reuses a checksum-verified cache; indexing verifies corpus and model fingerprints before skipping unchanged collections. Run records capture package versions, code hashes, model revisions, configuration and input checksums.

## Search and graph examples

```powershell
.\scripts\run.ps1 search 'What happens if my CGPA falls below 2.25?' --top 5 --topic probation_dismissal
.\scripts\run.ps1 search 'What is the plagiarism policy?' --document P1
.\scripts\run.ps1 prereqs CSE400
.\scripts\run.ps1 unlocks CSE103
```

Search reports cosine similarity separately from the small configured preference for current web snapshots. A retrieval timestamp is not a policy effective date. Discrepancy warnings ask users to verify the official rule. PDF citations use physical PDF page numbers; HTML citations include source URL, section and block range.

Prerequisite graph edges point from prerequisite to course. The current CSE catalogue supplies the main graph; bulletin records remain available separately. Unresolved codes are visibly marked. OR alternatives and non-course conditions remain in `prerequisite_expression`; the graph lists dependency references rather than a guaranteed degree-advising plan.

To use Neo4j, copy `graph/nodes.csv` and `graph/edges.csv` into its import directory and execute `graph/import.cypher` using Neo4j Browser or `cypher-shell`. Running a Neo4j server is optional.

## Evaluation and honest reporting

See [eval/README.md](eval/README.md) and the published [40-question reference](eval/benchmark_questions.csv). The reference was checked directly against saved official sources and frozen before any search results were inspected. The primary comparison uses no gold topic filters or source preference bonus. Recall@k is the question hit rate for an accepted source locator; it does not measure the completeness of a generated answer. MRR is truncated at 20.

| Model | Nominal / maximum content tokens | Recall@1 | Recall@5 | MRR@20 |
|---|---:|---:|---:|---:|
| BGE-small | 200 / 200 | 50.0% | 85.0% | 0.6425 |
| BGE-small | 300 / 254 | 47.5% | 85.0% | 0.6390 |
| MiniLM | 200 / 200 | 47.5% | 82.5% | 0.6173 |
| MiniLM | 300 / 254 | 52.5% | 82.5% | 0.6491 |

Topic agreement is **91/99 (91.9%)** on scorable passages. All 100 original entries are retained; one detached table-column header was documented as unscorable before scoring. Raw agreement including that fragment is 92/100. The sample is dominated by course descriptions, one original label received assistance, and four corrections were explicitly approved by the owner; aggregate agreement is not accuracy across all 16 topics.

The preserved 24-page PII reference contains 98 person-name occurrences (one selected by the owner, 97 prepared on his behalf).

| Person-name detection | Exact-span precision | Exact-span recall |
|---|---:|---:|
| Original ingestion snapshot | 17.5% (21/120) | 21.4% (21/98) |
| Current detector, with name-boundary repair | **47.2%** (42/89) | **42.9%** (42/98) |

The original detector often tagged only part of a name, leaving fragments such as `[PERSON]hi Uddin` in the text, and it tagged technical eponyms such as theorem names. The repair grows each detected span to whole words, completes names after honorifics, merges touching fragments and leaves eponyms such as "Norton's theorem" untouched. These are general boundary rules, not thresholds fitted to the sample, but the reference had been inspected before the repair, so the second row is not a held-out estimate. Most remaining misses are names the NER model never detects. The rebuilt search corpus has no name fragments attached to tags. No full email, phone or student-ID instances occur in this reference, so their precision/recall is undefined. Independent human verification of the complete PII and retrieval references remains pending.

After freezing, the corpus was rebuilt once more for the PII repair (corpus version v3). The 40 frozen questions use document and page/section locators rather than chunk IDs, so they were left unchanged; every locator was re-validated against the new corpus before scoring, and the earlier corpus and results are preserved locally. Corpus repairs were completed before retrieval-reference freezing: the fee extractor now retains full-width fee supplements, and PDF credit-distribution tables no longer inherit an unrelated course heading. Completed topic/PII references retain their original source snapshot; retrieval uses the repaired corpus. The calendar index contains schedule links, so two unsupported class-start/drop-date drafts were replaced with calendar-listing questions before scoring. No tuning was performed on retrieval outcomes.

The plan's nominal 300-token setting is capped at **254 content tokens** because MiniLM defaults to 256 including special tokens. Both model tokenizers validate every passage; secondary splits prevent silent truncation. The two actual settings are at most 200 and 254 tokens. Keep this difference visible when interpreting results.

## Privacy, scope and limitations

- Only configured public HTTPS sources under `ewubd.edu` are collected. No portal access or login. Collection stops on unresolved robots restrictions.
- Raw PDFs, HTML, full extracted text, Chroma data, model caches and private annotation pages are Git-ignored. Published materials include code, manifests, aggregate reports, a source-locator benchmark without source-page reproductions, and one explicitly reviewed redacted sample.
- Names use `dslim/bert-base-NER`; email, Bangladesh phone and ID patterns use regexes. NER confidence and allowlists are configurable. Automated detection can miss personal information. A SHA256 hash in the private log avoids directly recording values, but is not strong anonymization for guessable values.
- Personnel rosters and bibliography sections from the bulletin are retained locally for the PII audit and excluded from student search using explicit heading rules. Any non-course passage that is mostly redacted names (at least 4 tags and 4 per 100 words) is also excluded. A development inspection found an undetected roster name; that finding motivated the exclusion. The exclusion is not a guarantee that all remaining personal information has been detected.
- Version checks extract specific probation thresholds, dismissal cutoffs, letter-grade points and score bounds, and retake facts. Each discrepancy includes source locators. Differences need confirmation against official effective dates; the pipeline does not infer dates from retrieval time.
- English text extraction is supported. Scanned-page flags are reported; OCR and Bangla processing are future work. PDF layout/heading errors and incomplete course entries are exposed through checks and remain reviewable.
- Model revisions are pinned on first use in `configs/model_revisions.json`. Model licenses remain separate from the MIT license for original project code.

## Tests

```powershell
.\.env-gpu\python.exe -m pytest -q
```

Fixture tests cover cleaning, parser semantics, PII patterns, span metrics, page relevance, graph traversal and cycles, chunk provenance and stability. CI runs these without real university downloads or model weights. Full local checks also verify no input truncation, normalized vectors and matching Chroma counts.

## Project layout

`src/ewu_kb/` contains pipeline stages; `configs/` defines sources/models/thresholds; ignored `data/` contains local artifacts; `eval/` documents manual review; `graph/` contains importable records; `reports/` contains aggregate quality outputs; `notebooks/` provides a walkthrough.
