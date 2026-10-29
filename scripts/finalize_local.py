"""Execute the cached-data walkthrough and record the actual dependency closure."""
from __future__ import annotations

import importlib.metadata as metadata
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ewu_kb.common import load_stats, now, setup_paths, write_json  # noqa: E402


def main():
    setup_paths()
    import nbformat
    from nbclient import NotebookClient
    from jupyter_client import KernelManager
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    import tomllib

    if Path(sys.prefix).resolve() != (ROOT / ".env-gpu").resolve():
        raise RuntimeError("Use the dedicated environment")
    validation = ROOT / "reports/integration_checks.json"
    if not validation.exists() or json.loads(validation.read_text())["status"] != "passed":
        raise RuntimeError("Actual integration checks must pass first")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    queue = [(Requirement(r), ("",)) for r in project["dependencies"] + project["optional-dependencies"]["dev"]]
    visited, pins = set(), {}
    while queue:
        req, parent_extras = queue.pop()
        if req.marker and not any(req.marker.evaluate({"extra": extra}) for extra in parent_extras):
            continue
        name = canonicalize_name(req.name)
        visit_key = (name, tuple(sorted(req.extras)))
        if visit_key in visited:
            continue
        visited.add(visit_key)
        dist = metadata.distribution(req.name)
        pins[dist.metadata["Name"]] = dist.version
        queue.extend((Requirement(r), ("", *sorted(req.extras))) for r in dist.requires or [])
    text = "# Windows Python 3.12 dependency snapshot; generated from the tested project closure.\n"
    text += "--extra-index-url https://download.pytorch.org/whl/cu128\n"
    text += "\n".join(f"{name}=={version}" for name, version in sorted(pins.items(), key=lambda p: p[0].lower())) + "\n"
    (ROOT / "requirements-windows.lock.txt").write_text(text, encoding="utf-8")
    path = ROOT / "notebooks/01_walkthrough.ipynb"
    notebook = nbformat.read(path, as_version=4)
    manager = KernelManager(kernel_name="python3")
    manager.kernel_spec.argv = [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"]
    client = NotebookClient(notebook, km=manager, timeout=300, resources={"metadata": {"path": str(ROOT)}})
    client.execute()
    nbformat.write(notebook, path)
    stats = {stage: load_stats(stage) for stage in ("collect", "extract", "structure", "pii", "chunk_200", "chunk_300", "graph", "evaluate")}
    evaluation_complete = all(stats["evaluate"].get(key, {}).get("status") == "complete" for key in ("annotation", "pii", "retrieval"))
    human_evaluation_complete = evaluation_complete and all(
        stats["evaluate"].get(stage, {}).get("reference_review", {}).get("independent_human_review", False)
        for stage in ("pii", "retrieval"))
    write_json("reports/local_completion.json", {"at": now(), "notebook_executed": True,
                                               "dependency_pins": len(pins), "reference_evaluation": "complete" if evaluation_complete else "pending",
                                               "human_evaluation": "complete" if human_evaluation_complete else "pending",
                                               "automated_stages": "complete", "statistics": stats})
    print(f"Walkthrough executed; {len(pins)} Windows dependency pins recorded.")


if __name__ == "__main__":
    main()
