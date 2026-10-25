from __future__ import annotations

import json

from .common import ROOT, config, device, read_jsonl, record, revision, sha, write_json


def collection_name(key, size):
    return f"ewu_kb_{key}_{size}"


def client():
    import chromadb
    from chromadb.config import Settings
    return chromadb.PersistentClient(path=str(ROOT / "data/chroma"), settings=Settings(anonymized_telemetry=False))


def load_model(key):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(config()["models"][key]["name"], revision=revision(key), device=device())


def corpus_fingerprint(rows, key, size):
    return sha(json.dumps({"key": key, "size": size, "revision": revision(key), "rows": rows}, sort_keys=True))


def run(key="bge", size=300):
    import numpy as np
    rows = read_jsonl(f"data/processed/chunks_{size}.jsonl")
    if not rows or not all(r.get("pii_filtered") for r in rows):
        raise ValueError("Missing privacy-filtered chunks")
    digest = corpus_fingerprint(rows, key, size)
    store = client()
    name = collection_name(key, size)
    collection = store.get_or_create_collection(name, metadata={"hnsw:space": "cosine"}, embedding_function=None)
    lock_path = ROOT / f"data/processed/index_{key}_{size}.json"
    if lock_path.exists():
        old = json.loads(lock_path.read_text())
        if old["fingerprint"] == digest and collection.count() == len(rows):
            ids = set(collection.get(include=[])["ids"])
            if ids == {r["chunk_id"] for r in rows}:
                print(f"{name}: unchanged, verified {len(rows)} vectors", flush=True)
                return
    model = load_model(key)
    for row in rows:
        if len(model.tokenizer.encode(row["text"], add_special_tokens=True)) > model.max_seq_length:
            raise ValueError("Embedding would silently truncate a chunk")
    vectors = model.encode([r["text"] for r in rows], batch_size=config()["embedding"]["batch_size"],
                           normalize_embeddings=True, show_progress_bar=True, convert_to_numpy=True)
    assert np.isfinite(vectors).all()
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4)
    old_ids = set(collection.get(include=[])["ids"])
    live_ids = {r["chunk_id"] for r in rows}
    stale = sorted(old_ids - live_ids)
    if stale:
        collection.delete(ids=stale)
    for start in range(0, len(rows), 128):
        batch = rows[start:start + 128]
        collection.upsert(ids=[r["chunk_id"] for r in batch], documents=[r["text"] for r in batch],
                          embeddings=vectors[start:start + len(batch)].tolist(),
                          metadatas=[{k: v for k, v in r.items() if k != "text" and v is not None} for r in batch])
    assert collection.count() == len(rows)
    result = {"collection": name, "chunks": len(rows), "vectors": collection.count(), "dimensions": vectors.shape[1],
              "fingerprint": digest, "model": config()["models"][key]["name"], "revision": revision(key),
              "device": device(), "nominal_chunk_size": size}
    write_json(f"data/processed/index_{key}_{size}.json", result)
    record(f"embed_{key}_{size}", result)
