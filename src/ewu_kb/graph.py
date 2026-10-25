from __future__ import annotations

import json

from .common import ROOT, read_csv, record, write_csv


def build_graph(courses, edges, source="C1"):
    import networkx as nx
    graph = nx.DiGraph()
    for course in courses:
        if course["source"] == source:
            graph.add_node(course["code"], title=course["title"], credits=course["credits_total"],
                           source=source, locator=course["locator"],
                           prerequisite_expression=course["prerequisite_expression"], placeholder=False)
    for edge in edges:
        if edge["source"] == source:
            for node in (edge["from_course"], edge["to_course"]):
                if node not in graph:
                    graph.add_node(node, title="Unresolved reference", credits="", source=source,
                                   locator="", prerequisite_expression="", placeholder=True)
            graph.add_edge(edge["from_course"], edge["to_course"], relation=edge["relation"],
                           source=source, locator=edge["locator"])
    return graph


def query(graph, code, kind="prereqs"):
    import networkx as nx
    if code not in graph:
        raise ValueError(f"Course {code} not found")
    nodes = nx.ancestors(graph, code) if kind == "prereqs" else nx.descendants(graph, code)
    subgraph = graph.subgraph(nodes)
    if not nx.is_directed_acyclic_graph(subgraph):
        raise ValueError("Prerequisite graph contains cycles; a reliable order is unavailable")
    return list(nx.lexicographical_topological_sort(subgraph))


def run():
    import matplotlib.pyplot as plt
    import networkx as nx
    courses, edges = read_csv("data/processed/courses.csv"), read_csv("data/processed/prereq_edges.csv")
    graph = build_graph(courses, edges)
    nodes = [{"code": node, **meta} for node, meta in sorted(graph.nodes(data=True))]
    links = [{"from_course": a, "to_course": b, **meta} for a, b, meta in sorted(graph.edges(data=True))]
    write_csv("graph/nodes.csv", nodes, ["code", "title", "credits", "source", "locator", "prerequisite_expression", "placeholder"])
    write_csv("graph/edges.csv", links, ["from_course", "to_course", "source", "locator", "relation"])
    (ROOT / "graph/import.cypher").write_text('''// Copy nodes.csv and edges.csv into Neo4j's configured import directory first.
CREATE CONSTRAINT course_code IF NOT EXISTS FOR (c:Course) REQUIRE c.code IS UNIQUE;
LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
MERGE (c:Course {code: row.code})
SET c.title = row.title, c.credits = toFloatOrNull(row.credits), c.source = row.source,
    c.locator = row.locator, c.prerequisite_expression = row.prerequisite_expression,
    c.unresolved = row.placeholder = 'True';
LOAD CSV WITH HEADERS FROM 'file:///edges.csv' AS row
MATCH (p:Course {code: row.from_course}), (c:Course {code: row.to_course})
MERGE (p)-[r:PREREQUISITE_OF]->(c)
SET r.source = row.source, r.locator = row.locator, r.relation = row.relation;
''', encoding="utf-8")
    cycles = list(nx.simple_cycles(graph))
    if graph:
        if not cycles:
            levels = list(nx.topological_generations(graph))
            pos = {node: (level, -index + (len(layer) - 1) / 2) for level, layer in enumerate(levels)
                   for index, node in enumerate(sorted(layer))}
        else:
            pos = nx.spring_layout(graph, seed=42)
        fig, ax = plt.subplots(figsize=(16, max(7, min(24, len(graph) / 5))))
        colors = ["#fbbf24" if graph.nodes[n].get("placeholder") else "#bfdbfe" for n in graph]
        nx.draw_networkx(graph, pos, ax=ax, node_size=1050, node_color=colors, edge_color="#64748b",
                         font_size=7, arrowsize=12, width=0.8)
        ax.set_title("CSE prerequisite references | prerequisite → course\nAmber nodes: unresolved catalogue references")
        ax.axis("off")
        fig.tight_layout()
        fig.savefig(ROOT / "reports/figures/prerequisite_graph.png", dpi=160)
        plt.close(fig)
    record("graph", {"source": "C1", "nodes": graph.number_of_nodes(), "edges": graph.number_of_edges(),
                     "cycles": cycles, "isolated_courses": sorted(nx.isolates(graph)),
                     "unresolved": [n for n, d in graph.nodes(data=True) if d.get("placeholder")],
                     "alternative_edges": sum(d.get("relation") == "alternative" for _, _, d in graph.edges(data=True)),
                     "limitations": "Graph represents prerequisite references; OR alternatives and non-course conditions require reading the stored expression."})
