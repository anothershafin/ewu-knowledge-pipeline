"""Read-only integration checks over actual local artifacts."""
from __future__ import annotations

import json
import subprocess

from .common import ROOT, config, load_stats, now, read_csv, read_jsonl, sha, write_json


def run():
    from .embed_store import client, collection_name
    manifest = read_csv("data/processed/manifest.csv")
    assert len(manifest) == 17
    for row in manifest:
        ext = "pdf" if "pdf" in row["content_type"].lower() else "html"
        assert sha(ROOT / f"data/raw/{row['id']}.{ext}") == row["sha256"]
    documents = read_jsonl("data/processed/documents.jsonl")
    assert documents and all(r["pii_filtered"] for r in documents)
    eligible = {r["section_id"] for r in documents if r.get("index_eligible", True)}
    checked = []
    store = client()
    for size in config()["chunking"]["sizes"]:
        chunks = read_jsonl(f"data/processed/chunks_{size}.jsonl")
        assert len({r["chunk_id"] for r in chunks}) == len(chunks)
        assert all(r["pii_filtered"] and r["pii_fingerprint"] for r in chunks)
        assert all(r["section_id"] in eligible for r in chunks)
        assert all((r["page_start"] and r["page_end"]) or (r["block_start"] and r["block_end"]) for r in chunks)
        for key in ("bge", "minilm"):
            collection = store.get_collection(collection_name(key, size), embedding_function=None)
            assert collection.count() == len(chunks)
            ids = set(collection.get(include=[])["ids"])
            assert ids == {r["chunk_id"] for r in chunks}
            checked.append({"model": key, "nominal_size": size, "chunks": len(chunks), "vectors": collection.count()})
    tests = subprocess.run([__import__('sys').executable, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True)
    assert tests.returncode == 0, tests.stdout + tests.stderr
    ignored_paths = ["data/raw/S1.pdf", "data/processed/documents.jsonl", ".env-gpu/python.exe",
                     "work/pii_review_pages.jsonl", ".cache/huggingface/hub"]
    ignored = subprocess.run(["git", "check-ignore", *ignored_paths], cwd=ROOT, capture_output=True, text=True)
    assert set(ignored.stdout.splitlines()) == set(ignored_paths)
    model_checks = []
    locks = json.loads((ROOT / "configs/model_revisions.json").read_text())
    for key, item in locks.items():
        if "safetensors_sha256" not in item:
            continue
        path = ROOT / ".cache/huggingface/hub" / ("models--" + item["name"].replace("/", "--")) / "snapshots" / item["revision"] / "model.safetensors"
        assert path.stat().st_size == item["safetensors_bytes"]
        assert sha(path) == item["safetensors_sha256"]
        model_checks.append({"key": key, **item, "verified": True})
    write_json("reports/model_integrity.json", model_checks)
    summary = {"at": now(), "status": "passed", "manifest_checksums": len(manifest),
               "redacted_sections": len(documents), "indexes": checked, "fixture_tests": tests.stdout.strip(),
               "excluded_private_paths": ignored_paths, "empty_sources": load_stats("extract").get("empty_sources_quarantined", []),
               "human_evaluation_status": load_stats("evaluate"), "limitations": "Automated checks do not establish PII recall or retrieval accuracy."}
    write_json("reports/integration_checks.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "human_evaluation_status"}, indent=2))
