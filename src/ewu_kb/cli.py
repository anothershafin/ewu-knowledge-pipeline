from __future__ import annotations

import argparse
import importlib

from .common import config, run_record, setup_paths


def main():
    setup_paths()
    parser = argparse.ArgumentParser(description="Public university document engineering and cited retrieval")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("collect", "extract", "clean", "structure", "pii", "pii-recheck", "annotate", "review", "freeze-questions", "evaluate", "graph", "report", "validate", "run-all"):
        sub.add_parser(name)
    p = sub.add_parser("chunk")
    p.add_argument("--size", type=int, choices=[200, 300], default=300)
    p = sub.add_parser("embed")
    p.add_argument("--model", choices=["bge", "minilm"], default="bge")
    p.add_argument("--size", type=int, choices=[200, 300], default=300)
    p = sub.add_parser("search")
    p.add_argument("question")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--topic")
    p.add_argument("--document")
    p.add_argument("--version")
    p.add_argument("--model", choices=["bge", "minilm"], default="bge")
    p.add_argument("--size", type=int, default=300, choices=[200, 300])
    for name in ("prereqs", "unlocks"):
        p = sub.add_parser(name)
        p.add_argument("code")
    args = parser.parse_args()
    if args.command == "run-all":
        for stage in ("collect", "extract", "clean", "structure", "pii", "annotate"):
            print(f"\n=== {stage} ===", flush=True)
            importlib.import_module(f"ewu_kb.{stage}").run()
            run_record(stage)
        from . import chunk, embed_store, evaluate, graph, report, review, validate
        for size in config()["chunking"]["sizes"]:
            chunk.run(size)
            for key in ("bge", "minilm"):
                embed_store.run(key, size)
        review.run()
        graph.run()
        evaluate.run()
        report.run()
        validate.run()
    elif args.command == "chunk":
        from .chunk import run
        run(args.size)
    elif args.command == "embed":
        from .embed_store import run
        run(args.model, args.size)
    elif args.command == "search":
        from .search import run
        run(args.question, args.top, args.topic, args.model, args.size, args.document, args.version)
    elif args.command in ("prereqs", "unlocks"):
        from .common import read_csv
        from .graph import build_graph, query
        graph = build_graph(read_csv("data/processed/courses.csv"), read_csv("data/processed/prereq_edges.csv"))
        for node in query(graph, args.code.upper(), args.command):
            print(node, graph.nodes[node]["title"])
        print("Original condition:", graph.nodes[args.code.upper()].get("prerequisite_expression") or "not specified")
        print("Reference graph only; consult original prerequisite expressions for alternatives and other conditions.")
    elif args.command == "pii-recheck":
        from .pii import recheck_review_pages
        recheck_review_pages()
    elif args.command == "freeze-questions":
        from .evaluate import freeze_questions
        freeze_questions()
    else:
        importlib.import_module(f"ewu_kb.{args.command}").run()
    run_record(args.command)


if __name__ == "__main__":
    main()
