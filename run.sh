#!/bin/sh
# Rebuild everything: synthetic logs -> DuckDB -> Parquet -> query outputs.
set -e
cd "$(dirname "$0")"
PY=.venv/bin/python; DUCK=.venv/bin/duckdb
$PY gen_logs.py
rm -rf llm.duckdb data/curated && mkdir -p data/curated out
$DUCK llm.duckdb < 01_build.sql > out/00_build.txt
# Real gateway calls, if the LiteLLM POC has logged any.
ls data/litellm/dt=*/*.ndjson >/dev/null 2>&1 && $DUCK llm.duckdb < 02_gateway.sql > out/00_gateway.txt
for q in queries/q*.sql; do
  $DUCK -readonly llm.duckdb < "$q" > "out/$(basename "$q" .sql).txt"
done
echo "built: $(ls out | wc -l | tr -d ' ') outputs"
