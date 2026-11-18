# MySQL Query Optimization from First Principles

> Goal: understand exactly why MySQL picks the plan it does by building a **shadow optimizer**. It reads InnoDB's statistics and MySQL's cost constants, and predicts the access type, `rows`, `filtered`, cost and join order that `EXPLAIN` will print. Then you use it to make slow queries fast.

This guide is engine-specific. Its sibling, [postgres-query-optimization/](../postgres-query-optimization/), does the same for PostgreSQL. You can do them in either order.

---

## Ground rules

- Your shadow optimizer is a program you write in any language. Its **only inputs** are a snapshot of the statistics and settings you exported from MySQL, and a query described as structured data.
- Your optimizer must **never** call `EXPLAIN`, read the optimizer trace, or connect to the server. You use those only to *check* its predictions.
- No SQL parser library, no query builder, no ORM, no library that reads or interprets `EXPLAIN` output. Built-in lists, maps, math and JSON/CSV reading are fine.
- Use the `mysql` client and plain SQL to export statistics and to run checks.
- Use MySQL 8.0.18 or later with InnoDB tables and the default `optimizer_switch`, unless a stage says otherwise. Note your exact version in `NOTES.md`, because the optimizer changes between minor releases.

---

## How to use this doc

- Work through the stages in order. Each one builds on the last.
- Each stage has a **Task**, a **Done when** check, and a few **Questions** to answer in your own notes.
- Hints are hidden. Open one only after you have been stuck for a while. Try the primary sources first (see [References](#references)). For this guide the MySQL source code and the optimizer trace are primary sources.
- Keep a `NOTES.md` in this folder with what surprised you at each stage.
- Use **persistent** InnoDB statistics, and run `ANALYZE TABLE` after loading data. Otherwise your snapshot and the server will drift apart between runs.

Suggested layout (yours to change):

```
mysql-query-optimization/
├── README.md        ← this file
├── NOTES.md         ← your observations and prediction-vs-actual tables
├── schema.sql       ← your test schema and data generator
├── export.sql       ← dumps InnoDB stats, histograms, cost constants → snapshot
├── snapshot/        ← exported statistics, one file per snapshot
├── shadow/          ← your shadow optimizer (stages 1–6)
└── check.*          ← runs EXPLAIN and diffs it against your predictions
```

---

## Stage 0 — Observe before you build

**Task:** Set up a test database and learn every way MySQL explains itself.

1. Create four or five related InnoDB tables with a few hundred thousand to a few million rows. Include a skewed column, two correlated columns, a column with many NULLs, a composite index, and a secondary index that covers one of your queries. Run `ANALYZE TABLE`.
2. For a dozen queries, run `EXPLAIN` in the traditional format, `EXPLAIN FORMAT=TREE`, `EXPLAIN FORMAT=JSON` and `EXPLAIN ANALYZE`.
3. Turn on the optimizer trace for one query and read the whole trace from `INFORMATION_SCHEMA.OPTIMIZER_TRACE`.
4. Read what the optimizer reads: `SHOW INDEX`, `mysql.innodb_table_stats`, `mysql.innodb_index_stats`, `mysql.server_cost` and `mysql.engine_cost`.

**Done when:** You can point at every column of one traditional `EXPLAIN` row (`type`, `possible_keys`, `key`, `key_len`, `ref`, `rows`, `filtered`, `Extra`) and say what decision it records.

**Questions**
- List the `type` values from best to worst. What does each one mean about how rows are found?
- What does `rows × filtered / 100` mean for the *next* table in the join?
- The trace has a "considered_execution_plans" section. How many plans were considered for your largest join?
- Where does the `Cardinality` in `SHOW INDEX` come from, and how exact is it?

<details><summary>Hint</summary>

The manual's "EXPLAIN Output Format" section defines every column and every `type`. The optimizer trace pages in the MySQL Source Code Documentation (dev.mysql.com/doc/dev/mysql-server) explain the trace layout.
</details>

---

## Stage 1 — Export statistics and predict a full table scan

**Task:** Write the export script that captures the InnoDB table and index statistics, any histograms, the cost constants and the relevant system variables into a snapshot file. Then make your shadow optimizer predict `rows` and the cost (`read_cost`, `eval_cost`, `prefix_cost` in `FORMAT=JSON`) of a full table scan.

**Done when:** For every table in your schema, your predicted `rows` and scan cost match `EXPLAIN FORMAT=JSON` to the precision it prints.

**Questions**
- Which statistic gives the table's row count, and how was it computed? Is it exact?
- Which cost constants contribute to a table scan's cost? Which one depends on how much of the table is already in the buffer pool?
- What is the difference between the cost constants in `mysql.server_cost` and `mysql.engine_cost`? Why split them?
- Change one cost constant, run `FLUSH OPTIMIZER_COSTS`, and reconnect. Does your model predict the new cost?

<details><summary>Hint</summary>

The manual's "The Optimizer Cost Model" section lists every constant. The defaults are in `sql/opt_costconstants.cc` in the MySQL source.
</details>

---

## Stage 2 — InnoDB's layout decides the access path

InnoDB stores rows *inside* the primary key B-tree. Every secondary index entry stores the primary key, not a row address. This shapes nearly every plan MySQL makes.

**Task:** For single-table queries, predict the `type`, `key` and the `Using index` / `Using index condition` / `Using where` notes in `Extra`. Cover primary key lookups, unique and non-unique secondary lookups, covering indexes, composite indexes with leading and non-leading columns, and `ORDER BY … LIMIT`.

**Done when:** Your predicted `type`, `key` and `Extra` match `EXPLAIN` on at least 20 single-table queries.

**Questions**
- Why is a lookup through a secondary index more expensive than one through the primary key? What makes it cheap again?
- Why does InnoDB's choice of primary key affect the size of every secondary index?
- What is index condition pushdown, and why is it pointless on the primary key?
- For a composite index on `(a, b, c)`, which of `WHERE a = ?`, `WHERE b = ?`, `WHERE a = ? AND c = ?` and `WHERE a > ? AND b = ?` can use it, and for how many columns? Check with `key_len`.

<details><summary>Hint</summary>

The manual's "Clustered and Secondary Indexes" section (InnoDB chapter) and "Index Condition Pushdown Optimization" section (Optimization chapter).
</details>

---

## Stage 3 — Row estimates for indexed predicates

This is the core of the exercise. MySQL estimates rows for indexed conditions in two very different ways, and you must predict which one it uses.

**Task:** Predict `rows` for `ref` access (equality on an index prefix) from the snapshot alone. Then handle `range` access. Work out when MySQL asks the storage engine to count rows in a range by reading the index (an "index dive"), and when it falls back to index statistics.

**Done when:**
- Your predicted `rows` for `ref` access matches `EXPLAIN` exactly on at least 10 queries.
- For `range` access, you can predict *which* estimation method is used on every query, and you can make MySQL switch methods by changing the length of an `IN (…)` list.
- You have an explanation in `NOTES.md` for why you can't predict index-dive results exactly from a snapshot.

**Questions**
- Which column of `mysql.innodb_index_stats` gives the average number of rows per key prefix? How many pages are sampled to compute it, and what setting controls that?
- What does `eq_range_index_dive_limit` decide, and why does it exist?
- Why can't `ref` access estimates see skew, when index dives can?
- What changes for a predicate on a non-leading column when MySQL uses an index skip scan?

<details><summary>Hint</summary>

The manual's "Range Optimization" section covers index dives and `eq_range_index_dive_limit`. "Configuring Persistent Optimizer Statistics Parameters" (InnoDB chapter) covers the statistics columns and sampling.
</details>

---

## Stage 4 — `filtered`: conditions without an index

**Task:** Predict the `filtered` column for conditions on columns that are **not** used for access. Do it first with no histograms, then after `ANALYZE TABLE … UPDATE HISTOGRAM` with both singleton and equi-height histograms. Cover `=`, `<`, `BETWEEN`, `IN`, `IS NULL`, `AND` and `OR`.

**Done when:**
- Without histograms, your predicted `filtered` matches `EXPLAIN` exactly for at least 15 queries.
- With histograms, you predict the new `filtered` for the same queries within 1 percentage point.
- You have one join where adding a histogram changed the join order, and your model predicts both orders.

**Questions**
- What fixed guesses does MySQL use when it has no information about a column? Where are they defined?
- When does MySQL choose a singleton histogram and when an equi-height one?
- Why does MySQL ignore a histogram on a column it can estimate with an index dive?
- Histograms are not updated automatically. What does that mean after a month of inserts?
- How does the `condition_fanout_filter` flag in `optimizer_switch` change your predictions when you turn it off?

<details><summary>Hint</summary>

The manual's "Optimizer Statistics" section covers histograms. To find the default selectivities, look for the `COND_FILTER_` constants in the MySQL source, and read `get_filtering_effect` in `sql/item_cmpfunc.cc`.
</details>

---

## Stage 5 — Join planning

**Task:** For queries joining 2 to 8 tables, predict the join order, the access type for each table, and whether MySQL uses a hash join. Implement the classic optimizer's search: left-deep plans built table by table, costed from each partial plan's row count, with the pruning and depth limits that stop it from trying every order.

**Done when:**
- Your predicted join order matches `EXPLAIN` on at least 10 queries with 3 to 6 tables.
- For each, your partial-plan costs match the `considered_execution_plans` part of the optimizer trace for the chosen plan.
- You can make the chosen order change by changing `optimizer_search_depth` or `optimizer_prune_level`, and your model predicts the new one.

**Questions**
- Does the classic optimizer consider bushy trees? What does that rule out?
- Why does `eq_ref` access on the next table make an order attractive?
- What replaced the block nested loop join in MySQL 8.0, and when is a hash join used even without an equality condition?
- `STRAIGHT_JOIN` and the `JOIN_ORDER` hint both force an order. Why would you ever use them, and what risk do they carry?

<details><summary>Hint</summary>

The manual's "Controlling Query Plan Evaluation" and "Hash Join Optimization" sections. In the source, read `greedy_search`, `best_extension_by_limited_search` and `best_access_path` in `sql/sql_planner.cc`.
</details>

---

## Stage 6 — Subqueries and derived tables

**Task:** Predict how MySQL rewrites `IN (SELECT …)`, `EXISTS`, `NOT IN`, `NOT EXISTS`, and subqueries in `FROM`. For semi-joins, predict which strategy it picks: table pull-out, FirstMatch, LooseScan, Materialization, or DuplicateWeedout. For derived tables, predict whether they are merged into the outer query or materialized.

**Done when:** Your predicted strategy matches `EXPLAIN` (look in `Extra` and in `FORMAT=TREE`) on at least 8 queries, with at least four different semi-join strategies among them.

**Questions**
- Why is a semi-join different from an ordinary join? What would go wrong if MySQL just joined?
- Which strategy needs an index on the subquery's table, and which builds a temporary table?
- When can a derived table *not* be merged into the outer query?
- Why do `NOT IN` and `NOT EXISTS` give different results when NULLs are present, and how does that limit the optimizer?

<details><summary>Hint</summary>

The manual's "Optimizing IN and EXISTS Subquery Predicates with Semijoin Transformations" section, and "Optimizing Derived Tables, View References, and Common Table Expressions with Merging or Materialization".
</details>

---

## Stage 7 — Flip sides: from predicting to steering

Until now you predicted the optimizer. Now use the model to **change** what it does, preferring fixes that improve its information over fixes that override it.

**Task:** Write a workload of at least 10 queries, including some that are slow on purpose. Use the slow query log or `performance_schema.events_statements_summary_by_digest` to find the worst three. For each, use your shadow optimizer to find *which* estimate or cost is wrong. Then fix it with the smallest change that works, such as statistics sampling, a histogram, a new or changed index, a covering index, or a query rewrite.

**Done when:**
- Each of the three queries is at least 10× faster.
- For each fix, `NOTES.md` has your model's prediction *before* you applied it, and the real `EXPLAIN ANALYZE` after.
- At most one fix uses an optimizer hint or `FORCE INDEX`. For that one, explain why nothing better worked.

**Questions**
- Make an index invisible instead of dropping it. What does that let you test safely?
- Why can a query plan change after a routine `ANALYZE TABLE`, with no change to the query or schema?
- When is `FORCE INDEX` worse than no hint at all, months later?
- Which of your fixes would break if the data distribution changed next month?

<details><summary>Hint</summary>

The manual's "Optimizer Hints", "Invisible Indexes" and "The Slow Query Log" sections.
</details>

---

## Stretch goals

- **Index merge:** predict when MySQL combines two indexes with union, intersection or sort-union instead of choosing one.
- **Multi-range read and batched key access:** turn them on through `optimizer_switch` and predict when they pay off.
- **Sorting and grouping:** predict `Using filesort` and `Using temporary`, and when an index avoids them.
- **The hypergraph optimizer:** read about MySQL's newer join optimizer and check whether your build lets you enable it. Compare its approach with the classic greedy search.
- **Compare engines:** run the same workload through [postgres-query-optimization/](../postgres-query-optimization/) and explain each plan difference. Pay special attention to clustered vs heap storage.

---

## Self-check

You are done when you can answer these without notes:

1. Compute a full scan's cost and a `ref` access row estimate by hand from InnoDB's statistics and the cost tables.
2. Explain when MySQL uses index dives instead of index statistics, and why the two can disagree.
3. Explain what `filtered` means, where its value comes from with and without a histogram, and how it affects join order.
4. Explain how InnoDB's clustered primary key changes the cost of secondary index lookups and covering indexes.
5. Given a slow query and its `EXPLAIN ANALYZE`, find the first table where estimate and reality diverge, and name the fix.

---

## References

Primary sources. Read these before the hints.

- **MySQL Reference Manual** (8.0 or 8.4), "Optimization" chapter:
  - "Optimizing SELECT Statements": "Range Optimization", "Index Merge Optimization", "Hash Join Optimization", "Index Condition Pushdown Optimization", "Nested-Loop Join Algorithms", "Multi-Range Read Optimization", "Block Nested-Loop and Batched Key Access Joins", "Optimizing Subqueries, Derived Tables, View References, and Common Table Expressions"
  - "Understanding the Query Execution Plan": "Optimizing Queries with EXPLAIN", "EXPLAIN Output Format"
  - "Controlling the Query Optimizer": "Controlling Query Plan Evaluation", "Switchable Optimizations", "Optimizer Hints", "Index Hints", "The Optimizer Cost Model", "Optimizer Statistics"
  - "Optimization and Indexes": "Invisible Indexes", "InnoDB and MyISAM Index Statistics Collection"
- **MySQL Reference Manual**, "The InnoDB Storage Engine" chapter: "Clustered and Secondary Indexes", "Configuring Persistent Optimizer Statistics Parameters"
- **MySQL Reference Manual**, SQL statements: `EXPLAIN` (including `EXPLAIN ANALYZE`), `ANALYZE TABLE` (histograms)
- **MySQL Source Code Documentation** (dev.mysql.com/doc/dev/mysql-server): the optimizer trace pages
- **MySQL source** (`mysql/mysql-server`):
  - `sql/sql_planner.cc` (join order search and access path costing)
  - `sql/opt_costconstants.cc`, `sql/opt_costmodel.cc` (cost constants and model)
  - `sql/item_cmpfunc.cc` (`get_filtering_effect` and condition filtering)
  - `sql/histograms/` (histogram construction and selectivity)
  - `storage/innobase/dict/dict0stats.cc` (InnoDB persistent statistics)
- **Papers:**
  - Selinger, P. G. et al. (1979). "Access Path Selection in a Relational Database Management System." *SIGMOD*. §4 (costs and selectivity), §5 (join ordering).
