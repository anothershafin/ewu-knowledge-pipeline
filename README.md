# EWU Knowledge Base Pipeline

A reproducible knowledge engineering pipeline for East West University's public academic documents. It collects and structures sources, filters personal information, indexes passages for semantic search and exports a course-prerequisite reference graph. Search returns cited passages; it does not generate answers.

**Independent research project. Not affiliated with East West University.** University documents retain their original rights and are not redistributed in this repository.

## Current build status

The automated build, four indexes, integration checks and executed walkthrough are complete. **Independent human annotation and retrieval scoring remain pending.** No accuracy or privacy-recall claim is made yet.

| Measured artifact | Count |
|---|---:|
| Collected public source URLs | 17 |
| Sources with usable content | 16 |
| PDF pages (bulletin + four policies) | 556 |
| Structured sections | 3,107 |
| Sections excluded from student search | 563 |
| Curated chunks, 200-token setting | 3,222 |
| Curated chunks, nominal 300 / effective 254 setting | 2,920 |
| Detected body redaction events | 2,556 |
| CSE catalogue courses | 46 |
| Current prerequisite graph nodes / edges | 48 / 40 |
| Explicit source-rule comparisons / differences | 26 / 19 |
| Passing fixture tests | 14 |

The admissions FAQ URL currently returns an empty main content panel and is quarantined. The graph includes two unresolved reference nodes. Counts describe this snapshot and automated processing; they are not correctness estimates. See [the quality report](reports/quality_report.html), [integration checks](reports/integration_checks.json) and [model integrity checks](reports/model_integrity.json). GitHub Actions is configured; remote CI has not been run yet.

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

See [eval/README.md](eval/README.md). Human labels, spans and source answers are intentionally blank until reviewed. Freeze the 40-question set before inspecting retrieval results; the primary comparison uses no gold topic filters or source preference bonus. Report Recall@1, Recall@5 (question hit rate) and MRR@20. Never substitute detector predictions for human annotations.

The plan's nominal 300-token setting is capped at **254 content tokens** because MiniLM defaults to 256 including special tokens. Both model tokenizers validate every passage; secondary splits prevent silent truncation. The two actual settings are at most 200 and 254 tokens. Keep this difference visible when interpreting results.

## Privacy, scope and limitations

- Only configured public HTTPS sources under `ewubd.edu` are collected. No portal access or login. Collection stops on unresolved robots restrictions.
- Raw PDFs, HTML, full extracted text, Chroma data, model caches and private annotation pages are Git-ignored. Only manifests, aggregate reports, code and a small explicitly reviewed redacted sample are eligible for publication.
- Names use `dslim/bert-base-NER`; email, Bangladesh phone and ID patterns use regexes. NER confidence and allowlists are configurable. Automated detection can miss personal information. A SHA256 hash in the private log avoids directly recording values, but is not strong anonymization for guessable values.
- Personnel rosters and bibliography sections from the bulletin are retained locally for the PII audit and excluded from student search using explicit heading rules. A development inspection found an undetected roster name; that finding motivated the exclusion. The exclusion is not a guarantee that all remaining personal information has been detected.
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
