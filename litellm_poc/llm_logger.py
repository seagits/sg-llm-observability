"""LiteLLM proxy callback: one JSON line per model call, plus a small input guardrail.

Writes to $LLM_LOG_DIR/dt=YYYY-MM-DD/HH.ndjson, the same day/hour layout you would use in S3.
In AWS the write() below becomes an S3 put (or use LiteLLM's built-in S3 logger); DuckDB reads
either with the same query.

Guardrail (input side, deliberately simple, regex only):
  - PROMPT_ATTACK  -> request BLOCKED (HTTP 400), the model never runs
  - PII (email, US SSN, card number) -> ANONYMIZED in the prompt before it reaches the model
Every finding is logged, so "what did the guardrail catch" is a SQL query, not a guess.
"""
import json, os, re, threading, time, uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger

LOG_DIR = os.environ.get("LLM_LOG_DIR", "data/litellm")
_lock = threading.Lock()

ATTACK = re.compile(r"ignore (all|any|the|your) (previous|prior|above) instructions|reveal (your|the) system prompt|you are now DAN", re.I)
PII = {
    "EMAIL": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "US_SOCIAL_SECURITY_NUMBER": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "CREDIT_DEBIT_CARD_NUMBER": re.compile(r"\b(?:\d[ -]?){15,16}\b"),
}


def write(rec: dict) -> None:
    now = datetime.now(timezone.utc)
    d = os.path.join(LOG_DIR, f"dt={now:%Y-%m-%d}")
    os.makedirs(d, exist_ok=True)
    with _lock, open(os.path.join(d, f"{now:%H}.ndjson"), "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def tags(data: dict) -> dict:
    m = data.get("metadata") or data.get("litellm_metadata") or {}
    return {k: m.get(k) for k in ("team", "feature", "env", "trace_id", "session")}


class Handler(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        t0 = time.perf_counter()
        findings = []
        for msg in data.get("messages", []):
            text = msg.get("content")
            if not isinstance(text, str):
                continue
            if ATTACK.search(text):
                findings.append({"policy": "content_filter", "finding": "PROMPT_ATTACK", "action": "BLOCKED"})
            for name, rx in PII.items():
                if rx.search(text):
                    text = rx.sub(f"{{{name}}}", text)
                    findings.append({"policy": "pii", "finding": name, "action": "ANONYMIZED"})
            msg["content"] = text
        guard_ms = round((time.perf_counter() - t0) * 1000, 3)
        meta = data.setdefault("metadata", {})
        meta["guardrail_findings"], meta["guardrail_ms"] = findings, guard_ms

        if any(f["action"] == "BLOCKED" for f in findings):
            write({"ts": datetime.now(timezone.utc).isoformat(), "request_id": str(uuid.uuid4()),
                   "model": data.get("model"), "status": "blocked", "stop_reason": "guardrail_intervened",
                   "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "latency_ms": guard_ms,
                   "guardrail_ms": guard_ms, "guardrail_findings": findings, **tags(data)})
            raise HTTPException(status_code=400, detail={"error": "Blocked by guardrail: PROMPT_ATTACK"})
        return data

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        slo = kwargs.get("standard_logging_object") or {}
        meta = (kwargs.get("litellm_params") or {}).get("metadata") or {}
        choices = (slo.get("response") or {}).get("choices") or [{}]
        write({"ts": end_time.astimezone(timezone.utc).isoformat(),
               "request_id": slo.get("id") or kwargs.get("litellm_call_id"),
               "model": slo.get("model_group") or kwargs.get("model"),
               "upstream_model": slo.get("model"),
               "status": "success",
               "stop_reason": choices[0].get("finish_reason"),
               "input_tokens": slo.get("prompt_tokens"),
               "output_tokens": slo.get("completion_tokens"),
               "cost_usd": slo.get("response_cost"),
               "latency_ms": round((end_time - start_time).total_seconds() * 1000),
               "guardrail_ms": meta.get("guardrail_ms"),
               "guardrail_findings": meta.get("guardrail_findings") or [],
               **{k: meta.get(k) for k in ("team", "feature", "env", "trace_id", "session")}})

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        if "Blocked by guardrail" in str(kwargs.get("exception")):
            return  # already logged as status=blocked by the pre-call hook
        meta = (kwargs.get("litellm_params") or {}).get("metadata") or {}
        write({"ts": end_time.astimezone(timezone.utc).isoformat(), "request_id": kwargs.get("litellm_call_id"),
               "model": kwargs.get("model"), "status": "error", "stop_reason": "error",
               "error": str(kwargs.get("exception"))[:300],
               "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
               "latency_ms": round((end_time - start_time).total_seconds() * 1000),
               "guardrail_findings": [], **{k: meta.get(k) for k in ("team", "feature", "env", "trace_id", "session")}})


handler = Handler()
