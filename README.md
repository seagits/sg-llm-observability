# LLM analytics with DuckDB: local POC

Cost, guardrail and trace analytics over LLM logs, with DuckDB and no server. The repo ships code only;
every dataset is generated on your machine (`data/`, `llm.duckdb` and `out/` are gitignored).

## Run it

```bash
uv venv .venv && uv pip install -p .venv/bin/python -r requirements.txt
./run.sh                                             # synthetic Bedrock logs -> DuckDB -> Parquet -> out/*.txt
.venv/bin/streamlit run dashboard.py --server.port 8510    # http://localhost:8510
```

## Live gateway tab (optional)

Needs `litellm[proxy]`, `httpx` and Ollama with `gemma3:1b` and `qwen3:1.7b`.

```bash
cd litellm_poc && LLM_LOG_DIR=../data/litellm litellm --config config.yml --host 127.0.0.1 --port 4010
python3 traffic.py          # 269 real requests, about 2.5 minutes
```

Then press Refresh on the dashboard's Live tab.

## What is what

| File | What it does |
| --- | --- |
| `gen_logs.py` | Writes synthetic Bedrock invocation logs in the documented record schema and S3 folder layout (seeded). |
| `01_build.sql` | Raw logs -> `invocations`, `prices`, `costed`, `guardrail_events` -> Parquet. |
| `02_gateway.sql` | Loads the real LiteLLM gateway logs into `gw_calls`, `gw_guardrail_events`. |
| `queries/q*.sql` | The eleven analysis queries; outputs land in `out/`. |
| `dashboard.py` | Streamlit dashboard over the Parquet (tab 1) and the live gateway logs (tab 2). |
| `litellm_poc/` | Throwaway LiteLLM config + logging/guardrail callback (port 4010). |
| `traffic.py` | Sends real requests through the gateway. |
| `shoot.mjs`, `shoot_static.mjs`, `diagrams.html` | Optional: `npm i && npx playwright install chromium && npm run shoot` renders PNGs into `screenshots/`. |

## Not real

The Bedrock data is synthetic. Prices are example rates. Nothing here was run against a real S3
bucket. The gateway guardrail is three regular expressions and protects nothing.
