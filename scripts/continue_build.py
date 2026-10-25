"""Run remaining automated stages in the dedicated environment, with durable checkpoints."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ewu_kb.common import now, setup_paths, write_json  # noqa: E402


def main():
    setup_paths()
    if Path(sys.prefix).resolve() != (ROOT / ".env-gpu").resolve():
        raise RuntimeError("Use the dedicated .env-gpu interpreter")
    stages = [["extract"], ["clean"], ["structure"], ["pii"], ["annotate"],
              ["chunk", "--size", "200"], ["chunk", "--size", "300"],
              ["embed", "--model", "bge", "--size", "200"],
              ["embed", "--model", "bge", "--size", "300"],
              ["embed", "--model", "minilm", "--size", "200"],
              ["embed", "--model", "minilm", "--size", "300"],
              ["review"], ["graph"], ["evaluate"], ["report"], ["validate"]]
    completed = []
    for args in stages:
        write_json("work/build_status.json", {"updated_at": now(), "status": "running", "stage": args, "completed": completed})
        print(f"\nStarting: {' '.join(args)}", flush=True)
        result = subprocess.run([sys.executable, "-X", "utf8", "-m", "ewu_kb.cli", *args], cwd=ROOT)
        if result.returncode:
            write_json("work/build_status.json", {"updated_at": now(), "status": "failed", "stage": args,
                                                 "exit_code": result.returncode, "completed": completed})
            raise SystemExit(result.returncode)
        completed.append(args)
    finish = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/finalize_local.py")], cwd=ROOT)
    if finish.returncode:
        write_json("work/build_status.json", {"updated_at": now(), "status": "failed", "stage": ["finalize_local"], "completed": completed})
        raise SystemExit(finish.returncode)
    write_json("work/build_status.json", {"updated_at": now(), "status": "automated_stages_complete",
                                         "completed": completed, "human_review": "pending"})


if __name__ == "__main__":
    main()
