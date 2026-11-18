# PostgreSQL Query Optimization from First Principles

> Goal: understand exactly why PostgreSQL picks the plan it does by building a **shadow planner**. It reads Postgres's own statistics and settings, and predicts the row estimates, costs, access paths and join order that `EXPLAIN` will print. Then you use it to make slow queries fast.

This guide is engine-specific. Its sibling, [mysql-query-optimization/](../mysql-query-optimization/), does the same for MySQL. You can do them in either order.

---

## Ground rules

- Your shadow planner is a program you write in any language. Its **only inputs** are a snapshot of the statistics and settings you exported from Postgres, and a query described as structured data.
- Your planner must **never** call `EXPLAIN` or connect to the database. You use `EXPLAIN` only to *check* its predictions.
- No SQL parser library, no query builder, no ORM, no library that reads or interprets `EXPLAIN` output. Built-in lists, maps, math and JSON/CSV reading are fine.
- Use `psql` and plain SQL to export statistics and to run checks.
- Use PostgreSQL 14 or later, with default planner settings unless a stage says otherwise. Note your version in `NOTES.md`, because some formulas change between versions.

---

## How to use this doc

- Work through the stages in order. Each one builds on the last.
- Each stage has a **Task**, a **Done when** check, and a few **Questions** to answer in your own notes.
- Hints are hidden. Open one only after you have been stuck for a while. Try the primary sources first (see [References](#references)). For this guide the Postgres source code is a primary source. Read it.
- Keep a `NOTES.md` in this folder with what surprised you at each stage.
- Turn off parallel query (`max_parallel_workers_per_gather = 0`) until the stretch goals. It adds a layer of costing that hides the basics.

Suggested layout (yours to change):

```
postgres-query-optimization/
├── README.md        ← this file
├── NOTES.md         ← your observations and prediction-vs-actual tables
├── schema.sql       ← your test schema and data generator
├── export.sql       ← dumps pg_class, pg_stats, settings → snapshot file
├── snapshot/        ← exported statistics, one file per snapshot
├── shadow/          ← your shadow planner (stages 1–6)
└── check.*          ← runs EXPLAIN and diffs it against your predictions
```

---

## Stage 0 — Observe before you build

**Task:** Set up a test database and learn to read what the planner tells you.

1. Create four or five related tables with a few hundred thousand to a few million rows. Include a skewed column, two correlated columns, a column with many NULLs, and a text column. Add a few B-tree indexes. Run `ANALYZE`.
2. For a dozen queries, run `EXPLAIN`, `EXPLAIN (ANALYZE, BUFFERS)` and `EXPLAIN (FORMAT JSON)`.
3. Read what the planner reads: `pg_class` (`reltuples`, `relpages`, `relallvisible`), `pg_stats` for each column, and the planner settings in `pg_settings` (category "Query Tuning").
4. Install `pg_stat_statements` and `auto_explain`, and look at what they record.

**Done when:** You can point at every number in one `EXPLAIN` line (startup cost, total cost, rows, width) and say which catalog values it probably came from.

**Questions**
- What is the unit of cost? Which setting defines "1.0"?
- Why is there a *startup* cost separate from the total cost? Which node types have a large one?
- Delete half a table's rows without running `ANALYZE`. Does the seq scan row estimate change? Why or why not?
- How many rows does `ANALYZE` sample, and what setting controls it?

<details><summary>Hint</summary>

The docs section "Using EXPLAIN" works through the cost of a seq scan on a sample table. Reproduce that arithmetic on your own table before moving on.
</details>

---

## Stage 1 — Export statistics and predict a sequential scan

**Task:** Write the export script that captures everything the planner might use into a snapshot file. Then make your shadow planner predict the **rows** and **total cost** of a sequential scan with no `WHERE` clause, and with one simple clause.

**Done when:** For every table in your schema, your predicted rows and total cost match `EXPLAIN` to the two decimal places it prints.

**Questions**
- Your prediction may be off when the table has grown since the last `ANALYZE`. The planner doesn't use `reltuples` exactly as stored. What does it do with the table's *current* size on disk?
- What does each `WHERE` clause add to the cost, even if it filters nothing?
- What does `width` mean, and where does it come from?

<details><summary>Hint</summary>

Read `cost_seqscan` in `src/backend/optimizer/path/costsize.c`, and how the planner estimates relation size in `src/backend/optimizer/util/plancat.c`.
</details>

---

## Stage 2 — Selectivity of a single clause

This is the core of the exercise. Most bad plans start with a bad row estimate.

**Task:** Predict the `rows` estimate for single-column predicates: `=`, `<>`, `<`, `>`, `BETWEEN`, `IS NULL`, `IS NOT NULL`, `IN (…)`, and a `LIKE 'prefix%'`. Handle values that are in the most-common-values list, values that are not, values outside the histogram range, and columns with no statistics at all.

**Done when:** Your predicted `rows` exactly matches `EXPLAIN` on at least 30 varied single-clause queries across skewed, uniform and NULL-heavy columns. List any you can't match in `NOTES.md`, with the reason.

**Questions**
- For `col = 42` where 42 is *not* a most-common value, what does the planner assume about every other value?
- How does a range predicate use the most-common values and the histogram *together*?
- What estimate does Postgres use when a column has no statistics, or when the comparison value is a parameter it can't see? Find the default constants.
- `n_distinct` is sometimes negative. What does that mean, and why store it that way?
- Why do estimates for `WHERE col + 0 = 42` or `WHERE lower(col) = 'x'` fall back to defaults, and how can you change that?

<details><summary>Hint 1</summary>

The docs chapter "How the Planner Uses Statistics", section "Row Estimation Examples", walks through equality and range estimates step by step.
</details>

<details><summary>Hint 2</summary>

The code is in `src/backend/utils/adt/selfuncs.c` (`eqsel`, `scalarineqsel`, `ineq_histogram_selectivity`, `var_eq_const`) and the default constants are in `src/include/utils/selfuncs.h`.
</details>

---

## Stage 3 — Combining clauses

**Task:** Predict `rows` for `AND`, `OR` and `NOT` combinations, including two-sided ranges on one column (`a > 10 AND a < 20`) and predicates on two correlated columns. Then create **extended statistics** (`CREATE STATISTICS` with `ndistinct`, `dependencies` and `mcv`) on the correlated columns, and extend your model to use them.

**Done when:**
- Your predictions match `EXPLAIN` on at least 15 multi-clause queries, without extended statistics.
- On your correlated columns, you can show the estimate before and after `CREATE STATISTICS`, and your model predicts both.

**Questions**
- Why is `a > 10 AND a < 20` not estimated as `sel(a > 10) × sel(a < 20)`?
- How is `OR` combined? What assumption does it share with `AND`?
- What does each kind of extended statistic fix, and which kinds of query does each one *not* help?
- Where are extended statistics stored, and how do you export them for your snapshot?

<details><summary>Hint</summary>

Read `clauselist_selectivity` in `src/backend/optimizer/path/clausesel.c`. The docs section "Multivariate Statistics Examples" covers the extended-statistics cases.
</details>

---

## Stage 4 — Access paths: seq scan, index scan, bitmap scan, index-only scan

**Task:** For a single-table query, predict the cost of every access path Postgres considers and which one it picks. Cover queries returning one row, 0.1%, 5% and 50% of the table. Compare a column that is physically sorted with one whose values are scattered.

**Done when:**
- Your predicted plan type matches `EXPLAIN` on at least 20 single-table queries.
- Your predicted total cost is within 5% for each of them.
- You found the selectivity at which Postgres switches from index scan to bitmap scan to seq scan for one column, and your model predicts both switch points.

**Questions**
- How does `pg_stats.correlation` change the cost of an index scan? Why does it matter so much?
- Why does an index-only scan still read the heap sometimes? What does `relallvisible` tell the planner?
- What does `effective_cache_size` change, given that Postgres never allocates that memory?
- If you lower `random_page_cost` to 1.1, which queries change plans? Why might that be right on SSD storage?

<details><summary>Hint</summary>

Read `cost_index` and `index_pages_fetched` in `costsize.c`, and `btcostestimate` in `selfuncs.c`. The page-fetch estimate comes from Mackert & Lohman (1989), cited in the source.
</details>

---

## Stage 5 — Join size and join methods

**Task:** For two-table equality joins, predict the joined `rows`, then the cost of **nested loop**, **hash join** and **merge join**. Also cover the parameterized index nested loop, and **Memoize** (Postgres 14+). Predict which method wins.

**Done when:**
- Your predicted join `rows` matches `EXPLAIN` for at least 10 two-table joins, including joins with filters on both sides.
- Your predicted join method matches for all of them, and you have one query per method where it wins.

**Questions**
- How is a join's selectivity computed from the two columns' statistics? What changes when both columns have most-common-values lists?
- What does `work_mem` change in the hash join cost? What happens when the hash table won't fit, and how does that show up in `EXPLAIN ANALYZE`?
- When is merge join chosen even though it needs sorted input?
- Why does a join's row estimate stay the same whichever join method is used?

<details><summary>Hint</summary>

`eqjoinsel` in `selfuncs.c` for join size. `initial_cost_nestloop`, `initial_cost_hashjoin`, `initial_cost_mergejoin` and their `final_cost_*` partners in `costsize.c` for the methods.
</details>

---

## Stage 6 — Join order search

**Task:** For queries joining 3 to 8 tables, predict the join order and tree shape Postgres chooses. Implement its search: dynamic programming by levels, with the limits that stop the planner from reordering, and a note of where the genetic optimizer takes over.

**Done when:**
- For 10 queries with 3 to 6 tables, your predicted join tree matches `EXPLAIN` exactly.
- You can predict which queries are **not** reordered because of `join_collapse_limit` or `from_collapse_limit`, and show the plan change when you raise the limit.

**Questions**
- Does Postgres consider bushy trees? Does it consider cross products, and when?
- What is the default `geqo_threshold`? Why does the genetic optimizer make plans non-deterministic, and what setting fixes that?
- Explicit `JOIN … ON` syntax can constrain the join order. When, and why is this useful?
- What happens to `LEFT JOIN` ordering? Which reorderings are legal?

<details><summary>Hint</summary>

Read `src/backend/optimizer/README` for the overall algorithm, then `standard_join_search` in `src/backend/optimizer/path/allpaths.c` and `join_search_one_level` in `joinrels.c`. The docs section "Controlling the Planner with Explicit JOIN Clauses" covers the limits.
</details>

---

## Stage 7 — Flip sides: from predicting to steering

Until now you predicted the planner. Now use the model to **change** what it does, without forcing it.

**Task:** Write a workload of at least 10 queries, including some that are slow on purpose. Use `pg_stat_statements` and `auto_explain` to find the worst three. For each, use your shadow planner to find *which* estimate or cost is wrong. Then fix it with the smallest change that works, such as statistics targets, extended statistics, an index, an expression index, a partial index, or a query rewrite.

**Done when:**
- Each of the three queries is at least 10× faster.
- For each fix, `NOTES.md` has your model's prediction *before* you applied it, and the real `EXPLAIN (ANALYZE)` after.
- None of your fixes uses `enable_*` settings or plan hints.

**Questions**
- Why is it better to fix an estimate than to force a plan?
- A prepared statement runs fast five times and then gets slow. What changed? Find `plan_cache_mode` and explain generic vs custom plans.
- When does a CTE act as an optimization fence, and how did that change in Postgres 12?
- Which of your fixes would break if the data distribution changed next month?

<details><summary>Hint</summary>

The docs page for `PREPARE` (Notes section) explains when a generic plan is used. The page for `WITH` queries covers `MATERIALIZED` and `NOT MATERIALIZED`.
</details>

---

## Stretch goals

- **Parallel query:** turn parallelism back on and predict worker counts, Gather costs and when a parallel plan wins.
- **Incremental sort and aggregates:** predict when Postgres picks incremental sort, hash aggregate or group aggregate.
- **Partitioning:** predict partition pruning at plan time and at run time.
- **Subquery pull-up:** predict when `IN`, `EXISTS` and `NOT IN` become semi-joins or anti-joins, and why `NOT IN` often doesn't.
- **pg_hint_plan:** use it only to *test* your model's cost of a plan Postgres rejected, never as a fix.
- **Compare engines:** run the same workload through [mysql-query-optimization/](../mysql-query-optimization/) and explain each plan difference.

---

## Self-check

You are done when you can answer these without notes:

1. Compute a seq scan's cost and an equality predicate's row estimate by hand from `pg_class` and `pg_stats`.
2. Explain how the most-common-values list and the histogram combine for a range predicate.
3. Explain why correlation decides between an index scan and a bitmap heap scan.
4. Explain how Postgres searches join orders, and what changes above `join_collapse_limit` and `geqo_threshold`.
5. Given a slow query and its `EXPLAIN (ANALYZE)`, find the first node where estimate and reality diverge, and name the fix.

---

## References

Primary sources. Read these before the hints.

- **PostgreSQL documentation:**
  - "Performance Tips" chapter: "Using EXPLAIN", "Statistics Used by the Planner", "Controlling the Planner with Explicit JOIN Clauses"
  - "How the Planner Uses Statistics" chapter: "Row Estimation Examples", "Multivariate Statistics Examples", "Planner Statistics and Security"
  - "Genetic Query Optimizer" chapter
  - Server configuration, "Query Planning": "Planner Method Configuration", "Planner Cost Constants", "Genetic Query Optimizer", "Other Planner Options"
  - SQL command pages: `EXPLAIN`, `ANALYZE`, `CREATE STATISTICS`, `PREPARE`, `SELECT` (the `WITH` clause)
  - `pg_stat_statements` and `auto_explain` in "Additional Supplied Modules"
- **PostgreSQL source:**
  - `src/backend/optimizer/README` (planner overview)
  - `src/backend/optimizer/path/costsize.c` (all cost formulas)
  - `src/backend/optimizer/path/clausesel.c` (combining clauses)
  - `src/backend/utils/adt/selfuncs.c`, `src/include/utils/selfuncs.h` (selectivity and defaults)
  - `src/backend/optimizer/path/allpaths.c`, `joinrels.c` (join search)
  - `src/backend/optimizer/util/plancat.c` (relation size estimates)
  - `src/backend/commands/analyze.c` (sampling and statistics collection)
- **Papers:**
  - Selinger, P. G. et al. (1979). "Access Path Selection in a Relational Database Management System." *SIGMOD*. §4 (costs and selectivity), §5 (join ordering).
  - Mackert, L. F. & Lohman, G. M. (1989). "Index Scans Using a Finite LRU Buffer: A Validated I/O Model." *ACM TODS* 14(3).
  - Leis, V. et al. (2015). "How Good Are Query Optimizers, Really?" *PVLDB* 9(3). Its experiments use PostgreSQL.
