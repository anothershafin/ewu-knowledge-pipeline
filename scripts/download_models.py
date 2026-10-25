"""Cache only inference files for the three pinned public models; no GPU work."""
import sys
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ewu_kb.common import config, revision, setup_paths  # noqa: E402

setup_paths()
from huggingface_hub import snapshot_download  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--keys", nargs="+", choices=["ner", "bge", "minilm"], default=["ner", "bge", "minilm"])
args = parser.parse_args()
models = [(key, config()["models"][key]["name"], revision(key)) for key in args.keys]


def download(item):
    key, model, commit = item
    print(f"Downloading {key}: {model} @ {commit}", flush=True)
    snapshot_download(repo_id=model, revision=commit,
                      allow_patterns=["*.json", "*.txt", "*.safetensors", "1_Pooling/*"],
                      ignore_patterns=["onnx/*", "openvino/*", "*.onnx", "*.bin", "*.h5"], max_workers=3)
    print(f"{key} cache complete", flush=True)


with ThreadPoolExecutor(max_workers=3) as pool:
    list(pool.map(download, models))
