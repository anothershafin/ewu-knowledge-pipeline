"""Rebuild the search corpus after the PII name-boundary repair, keeping every reference intact.

Steps: preserve the current corpus and results, re-run redaction and everything downstream,
re-check the preserved PII review pages with the current detector, record a new corpus version,
then evaluate, report, validate and refresh the walkthrough. Completed topic labels, PII
reference spans and the frozen question set are never modified.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ewu_kb.common import now, read_csv, read_jsonl, setup_paths, sha, write_json  # noqa: E402

LABEL = "v3: PII name-boundary repair and roster filter (2026-10-29)"
BACKUP = ROOT / "work/corpus_before_pii_repair_2026-10-29"
STATUS = "work/pii_repair_rebuild_status.json"


def stage(args, completed):
    write_json(STATUS, {"updated_at": now(), "status": "running", "stage": args, "completed": completed})
    print(f"\n=== {' '.join(args)} ===", flush=True)
    result = subprocess.run([sys.executable, "-X", "utf8", "-m", "ewu_kb.cli", *args], cwd=ROOT)
    if result.returncode:
        write_json(STATUS, {"updated_at": now(), "status": "failed", "stage": args,
                            "exit_code": result.returncode, "completed": completed})
        raise SystemExit(result.returncode)
    completed.append(args)


def preserve():
    if BACKUP.exists():
        print(f"Backup already present, keeping it: {BACKUP}")
        return
    BACKUP.mkdir(parents=True)
    for rel in ("data/processed/documents.jsonl", "data/processed/chunks.jsonl", "data/processed/chunks_200.jsonl",
                "data/processed/chunks_300.jsonl", "data/processed/pii_log.csv", "data/processed/pii_stats.json",
                "data/processed/chunk_200_stats.json", "data/processed/chunk_300_stats.json",
                "data/processed/evaluate_stats.json", "data/processed/retrieval_per_question.csv",
                "reports/retrieval_results.csv", "reports/summary.json", "README.md"):
        source = ROOT / rel
        if source.exists():
            target = BACKUP / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    print(f"Previous corpus and results preserved in {BACKUP}")


def record_version():
    from ewu_kb.evaluate import check_question_locators
    questions = read_csv("eval/frozen/questions.csv")
    check_question_locators(questions, read_jsonl("data/processed/documents.jsonl"))
    path = ROOT / "work/corpus_versions.json"
    versions = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    history = versions.get("history", [])
    if versions.get("previous"):
        history.append(versions["previous"])
    versions = {
        "versioning_date_dhaka": now()[:10],
        "current": {"label": LABEL,
                    "chunks_sha256": sha(ROOT / "data/processed/chunks.jsonl"),
                    "documents_sha256": sha(ROOT / "data/processed/documents.jsonl"),
                    "retrieval_questions_revalidated": True,
                    "changes": ["Detected person spans grow to whole words and complete names",
                                "Touching name fragments merge into one tag",
                                "Technical eponyms (theorem, law, diagram ...) are no longer redacted",
                                "Passages that are mostly redacted names are excluded from search",
                                "Three more personnel headings excluded from search"],
                    "preserved_snapshot": str(BACKUP.relative_to(ROOT))},
        "previous": versions.get("current", {}),
        "history": history,
    }
    write_json("work/corpus_versions.json", versions)
    print("Corpus version recorded; all 40 frozen question locators re-validated.")


def main():
    setup_paths()
    if Path(sys.prefix).resolve() != (ROOT / ".env-gpu").resolve():
        raise RuntimeError("Run this with .env-gpu\\python.exe")
    preserve()
    completed = []
    for args in (["pii"], ["annotate"], ["chunk", "--size", "200"], ["chunk", "--size", "300"],
                 ["embed", "--model", "bge", "--size", "200"], ["embed", "--model", "bge", "--size", "300"],
                 ["embed", "--model", "minilm", "--size", "200"], ["embed", "--model", "minilm", "--size", "300"],
                 ["pii-recheck"]):
        stage(args, completed)
    record_version()
    for args in (["evaluate"], ["report"], ["validate"]):
        stage(args, completed)
    finish = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/finalize_local.py")], cwd=ROOT)
    if finish.returncode:
        write_json(STATUS, {"updated_at": now(), "status": "failed", "stage": ["finalize_local"], "completed": completed})
        raise SystemExit(finish.returncode)
    write_json(STATUS, {"updated_at": now(), "status": "complete", "completed": completed})
    evaluation = json.loads((ROOT / "data/processed/evaluate_stats.json").read_text(encoding="utf-8"))
    pii = evaluation.get("pii", {})
    print("\nDone.")
    print("PII original snapshot:", json.dumps(pii.get("all")))
    print("PII current detector: ", json.dumps(pii.get("current_detector", {}).get("all")))
    for row in evaluation.get("retrieval", {}).get("experiments", []):
        print("Retrieval", row)


if __name__ == "__main__":
    main()
