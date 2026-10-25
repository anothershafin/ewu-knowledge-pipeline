from __future__ import annotations

from .common import config, read_csv
from .embed_store import client, collection_name, load_model


class Searcher:
    def __init__(self, key="bge", size=300):
        self.key, self.size = key, size
        self.model = load_model(key)
        self.collection = client().get_collection(collection_name(key, size), embedding_function=None)

    def search(self, question, top=5, topic=None, document=None, version=None, prefer_current=True):
        conditions = [{field: value} for field, value in (("topic", topic), ("doc_id", document),
                                                        ("source_version", version)) if value]
        where = {"$and": conditions} if len(conditions) > 1 else (conditions[0] if conditions else None)
        query = config()["models"][self.key]["query_prefix"] + question
        if len(self.model.tokenizer.encode(query, add_special_tokens=True)) > self.model.max_seq_length:
            raise ValueError("Question exceeds the model's input limit; please shorten it.")
        vector = self.model.encode([query], normalize_embeddings=True)
        if not self.collection.count():
            return []
        result = self.collection.query(query_embeddings=vector.tolist(), where=where,
                                       n_results=min(self.collection.count(), top * config()["search"]["candidate_multiplier"]),
                                       include=["documents", "metadatas", "distances"])
        conflicts = read_csv("data/processed/conflicts.csv")
        rows = []
        for cid, text, meta, distance in zip(result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]):
            raw_score = 1 - distance
            bonus = config()["search"]["current_source_bonus"] if prefer_current and meta["source_version"].startswith("web-") else 0
            note = ""
            if conflicts and meta["topic"] in ("probation_dismissal", "grading_cgpa"):
                note = "Potential version discrepancy requires checking official effective dates."
            rows.append({"chunk_id": cid, "text": text, **meta, "similarity": raw_score,
                         "ranking_score": raw_score + bonus, "conflict_note": note})
        return sorted(rows, key=lambda r: (-r["ranking_score"], r["chunk_id"]))[:top]


def run(question, top=5, topic=None, key="bge", size=300, document=None, version=None):
    rows = Searcher(key, size).search(question, top, topic, document, version)
    for index, row in enumerate(rows, 1):
        if row.get("page_start"):
            location = f"PDF page {row['page_start']}-{row['page_end']}"
            link = row["source_url"] + f"#page={row['page_start']}"
        else:
            location = f"HTML blocks {row.get('block_start')}-{row.get('block_end')}"
            link = row["source_url"]
        print(f"\n{index}. cosine={row['similarity']:.4f} rank={row['ranking_score']:.4f} | {row['doc_id']} | {row['source_version']}")
        print(f"{row['section_path']} | {location}\n{link}\n{row['text'][:650]}")
        if row["conflict_note"]:
            print(row["conflict_note"])
    return rows
