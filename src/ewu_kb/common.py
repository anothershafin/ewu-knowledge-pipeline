from __future__ import annotations

import csv
import ast
import hashlib
import importlib.metadata
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parents[2]


def setup_paths():
    for folder in ("data/raw", "data/interim", "data/processed", "data/samples", "reports/figures",
                   "work", "logs", "eval", "graph", ".cache/huggingface", ".cache/tmp"):
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(ROOT / ".cache/huggingface")
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(ROOT / ".cache/huggingface/hub")
    os.environ["MPLCONFIGDIR"] = str(ROOT / ".cache/matplotlib")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ["TEMP"] = str(ROOT / ".cache/tmp")
    os.environ["TMP"] = str(ROOT / ".cache/tmp")


def config():
    return yaml.safe_load((ROOT / "configs/pipeline.yaml").read_text(encoding="utf-8"))


def sources():
    return yaml.safe_load((ROOT / "configs/sources.yaml").read_text(encoding="utf-8"))["sources"]


def now():
    return datetime.now(ZoneInfo("Asia/Dhaka")).isoformat()


def sha(value):
    if isinstance(value, Path):
        value = value.read_bytes()
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def semantic_code_sha(path):
    return sha(ast.dump(ast.parse(path.read_text(encoding="utf-8")), include_attributes=False))


def read_jsonl(path):
    p = ROOT / path
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.exists() else []


def write_jsonl(path, rows):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    tmp.replace(p)


def read_csv(path):
    p = ROOT / path
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows, fields):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(p)


def write_json(path, value):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def record(stage, details):
    write_json(f"data/processed/{stage}_stats.json", details)


def load_stats(stage):
    p = ROOT / f"data/processed/{stage}_stats.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"status": "pending"}


def run_record(stage):
    packages = {}
    for name in ("torch", "transformers", "sentence-transformers", "chromadb", "PyMuPDF", "requests"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    value = {"at": now(), "stage": stage, "python": sys.version, "executable": sys.executable,
             "settings": config(), "packages": packages,
             "inputs": {r["id"]: r["sha256"] for r in read_csv("data/processed/manifest.csv")}}
    lock = ROOT / "configs/model_revisions.json"
    if lock.exists():
        value["model_revisions"] = json.loads(lock.read_text(encoding="utf-8"))
    value["source_code_sha256"] = {str(p.relative_to(ROOT)): sha(p) for p in (ROOT / "src").rglob("*.py")}
    write_json("data/processed/run_record.json", value)
    write_json(f"work/runs/{datetime.now().strftime('%Y%m%dT%H%M%S%f')}_{stage}.json", value)


def rng():
    return random.Random(config()["seed"])


def device():
    import torch
    chosen = config()["device"]
    if chosen == "cuda":
        if Path(sys.prefix).resolve() != (ROOT / ".env-gpu").resolve():
            raise RuntimeError("GPU runs must use this project's .env-gpu Python.")
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but unavailable; set device: cpu explicitly if needed.")
    return chosen


def revision(key):
    from huggingface_hub import HfApi
    path = ROOT / "configs/model_revisions.json"
    locked = json.loads(path.read_text()) if path.exists() else {}
    name = config()["models"][key]["name"]
    if key not in locked or locked[key]["name"] != name:
        info = HfApi().model_info(name, files_metadata=True)
        weights = next((item for item in info.siblings if item.rfilename == "model.safetensors"), None)
        if not weights or not weights.lfs:
            raise RuntimeError("Expected safetensors weights and publisher checksum are unavailable")
        locked[key] = {"name": name, "revision": info.sha, "safetensors_sha256": weights.lfs.sha256,
                       "safetensors_bytes": weights.size}
        write_json("configs/model_revisions.json", locked)
    return locked[key]["revision"]
