// Copy nodes.csv and edges.csv into Neo4j's configured import directory first.
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
