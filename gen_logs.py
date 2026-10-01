"""Synthetic Amazon Bedrock model-invocation logs, in the documented S3 layout and record schema.

Record schema: https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html
Converse response body (usage, metrics, stopReason, trace.guardrail):
https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html

The DATA is made up (seeded, reproducible). The SHAPE is what Bedrock writes, so every query in
the article runs unchanged against a real log bucket.

Planted stories, so the analysis has something to find:
  1. batch-summarizer retry storm on day 11 (cost spike)
  2. support-bot uses prompt caching, search-rag does not (savings opportunity)
  3. prompt-attack burst on day 9 from one role session (guardrail spike)
  4. PII in support-bot traffic, anonymized by the guardrail
  5. code-review answers truncated at max_tokens
  6. one multi-step agent trace to follow end to end
"""
import gzip, json, os, random, shutil, uuid
from datetime import datetime, timedelta, timezone

random.seed(7)
ACCOUNT, REGION = "123456789012", "us-east-1"
OUT = f"data/raw/AWSLogs/{ACCOUNT}/BedrockModelInvocationLogs/{REGION}"
START = datetime(2026, 9, 14, tzinfo=timezone.utc)
DAYS = 14
GUARDRAIL_ID = "gr7x2k9demo1"
GUARDRAIL_ARN = f"arn:aws:bedrock:{REGION}:{ACCOUNT}:guardrail/{GUARDRAIL_ID}"

SONNET = "anthropic.claude-sonnet-4-20250514-v1:0"
HAIKU = "anthropic.claude-haiku-4-5-20251001-v1:0"
NOVA = "amazon.nova-lite-v1:0"

# team -> traffic profile
TEAMS = {
    "support-bot":      dict(role="SupportBotRole",   model=HAIKU,  per_day=1500, feature=["chat", "chat", "handoff-summary"], inp=(1800, 400), out=(220, 90),  cache=True,  guard=True),
    "search-rag":       dict(role="SearchRagRole",    model=SONNET, per_day=700,  feature=["answer", "rerank"],               inp=(6200, 1500), out=(380, 140), cache=False, guard=True),
    "code-review":      dict(role="CodeReviewRole",   model=SONNET, per_day=260,  feature=["pr-review"],                      inp=(9000, 4000), out=(1400, 700), cache=False, guard=False),
    "batch-summarizer": dict(role="BatchSummaryRole", model=NOVA,   per_day=900,  feature=["nightly-digest"],                 inp=(3000, 900), out=(300, 80),  cache=False, guard=False),
}

def clamp(x, lo): return max(lo, int(x))

def assessment(**policies):
    a = {
        "appliedGuardrailDetails": {"guardrailId": GUARDRAIL_ID, "guardrailVersion": "3", "guardrailArn": GUARDRAIL_ARN,
                                    "guardrailOrigin": ["REQUEST"], "guardrailOwnership": "SELF"},
        "invocationMetrics": {
            "guardrailProcessingLatency": random.randint(90, 420),
            "usage": {"topicPolicyUnits": 1, "contentPolicyUnits": 1, "wordPolicyUnits": 0,
                      "sensitiveInformationPolicyUnits": 1, "sensitiveInformationPolicyFreeUnits": 0,
                      "contextualGroundingPolicyUnits": 0},
            "guardrailCoverage": {"textCharacters": {"guarded": 0, "total": 0}},
        },
    }
    a.update(policies)
    return a

def record(ts, team, p, *, feature=None, trace_id=None, session=None, model=None, scale=1.0, env="prod", force=None):
    model = model or p["model"]
    inp = clamp(random.gauss(*p["inp"]) * scale, 50)
    out = clamp(random.gauss(*p["out"]), 10)
    stop = "end_turn"
    usage = {"inputTokens": inp, "outputTokens": out, "totalTokens": inp + out}
    if p["cache"]:
        # A long shared system prompt: most calls read it from cache, a few (re)write it.
        cached = 5200
        if random.random() < 0.08:
            usage["cacheWriteInputTokens"] = cached
        else:
            usage["cacheReadInputTokens"] = cached
        usage["inputTokens"] = clamp(inp * 0.25, 40)
        usage["totalTokens"] = usage["inputTokens"] + out
    if team == "code-review" and random.random() < 0.17:
        stop, out = "max_tokens", 4096
        usage["outputTokens"], usage["totalTokens"] = out, usage["inputTokens"] + out

    # Latency: roughly linear in output tokens, model-dependent, with a heavy tail.
    per_tok = {SONNET: 17, HAIKU: 7, NOVA: 5}[model]
    latency = int(350 + out * per_tok * random.uniform(0.8, 1.3))
    if random.random() < 0.012:
        latency *= random.randint(4, 9)

    body_out = {"output": {"message": {"role": "assistant", "content": [{"text": "…"}]}},
                "stopReason": stop, "usage": usage, "metrics": {"latencyMs": latency}}

    if p["guard"]:
        kind = force or random.choices(
            ["none", "pii", "topic", "attack", "hate"],
            weights=[955, 30 if team == "support-bot" else 4, 8, 5, 2])[0]
        trace = {"guardrail": {"inputAssessment": {GUARDRAIL_ID: assessment()}}}
        if kind == "pii":
            ent = random.choice(["EMAIL", "PHONE", "US_SOCIAL_SECURITY_NUMBER", "CREDIT_DEBIT_CARD_NUMBER"])
            trace["guardrail"]["outputAssessments"] = {GUARDRAIL_ID: [assessment(sensitiveInformationPolicy={
                "piiEntities": [{"type": ent, "match": "<redacted>", "action": "ANONYMIZED", "detected": True}]})]}
            trace["guardrail"]["actionReason"] = "Guardrail masked."
        elif kind in ("topic", "attack", "hate"):
            pol = {
                "topic": dict(topicPolicy={"topics": [{"name": random.choice(["investment-advice", "medical-diagnosis"]),
                                                      "type": "DENY", "action": "BLOCKED", "detected": True}]}),
                "attack": dict(contentPolicy={"filters": [{"type": "PROMPT_ATTACK", "confidence": "HIGH",
                                                           "filterStrength": "HIGH", "action": "BLOCKED", "detected": True}]}),
                "hate": dict(contentPolicy={"filters": [{"type": random.choice(["HATE", "INSULTS"]), "confidence": "MEDIUM",
                                                         "filterStrength": "MEDIUM", "action": "BLOCKED", "detected": True}]}),
            }[kind]
            trace["guardrail"]["inputAssessment"] = {GUARDRAIL_ID: assessment(**pol)}
            trace["guardrail"]["actionReason"] = "Guardrail blocked."
            # Blocked on input: the model never runs, so no model tokens are billed.
            body_out["stopReason"] = "guardrail_intervened"
            body_out["output"]["message"]["content"] = [{"text": "Sorry, I can't help with that."}]
            body_out["usage"] = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}
            body_out["metrics"]["latencyMs"] = random.randint(180, 520)
        body_out["trace"] = trace

    u = body_out["usage"]
    session = session or f"i-{random.randint(0, 40):03d}"
    meta = {"team": team, "feature": feature or random.choice(p["feature"]), "env": env}
    if trace_id:
        meta["trace_id"] = trace_id
    return {
        "schemaType": "ModelInvocationLog", "schemaVersion": "1.0",
        "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "accountId": ACCOUNT, "region": REGION, "requestId": str(uuid.UUID(int=random.getrandbits(128))),
        "operation": "Converse", "modelId": model,
        "identity": {"arn": f"arn:aws:sts::{ACCOUNT}:assumed-role/{p['role']}/{session}"},
        "requestMetadata": meta,
        "input": {"inputContentType": "application/json",
                  "inputBodyJson": {"messages": [{"role": "user", "content": [{"text": "…"}]}],
                                    "inferenceConfig": {"maxTokens": 4096}},
                  "inputTokenCount": u["inputTokens"]},
        "output": {"outputContentType": "application/json", "outputBodyJson": body_out,
                   "outputTokenCount": u["outputTokens"]},
    }

def rand_time(day, hours=(0, 24)):
    # Office-hours bump for interactive teams.
    h = min(23, max(0, int(random.triangular(hours[0], hours[1], 14))))
    return day + timedelta(hours=h, minutes=random.randint(0, 59), seconds=random.randint(0, 59))

records = []
for d in range(DAYS):
    day = START + timedelta(days=d)
    weekend = day.weekday() >= 5
    for team, p in TEAMS.items():
        n = int(p["per_day"] * (0.35 if weekend and team != "batch-summarizer" else 1) * random.uniform(0.9, 1.1))
        hours = (1, 4) if team == "batch-summarizer" else (0, 24)
        for _ in range(n):
            records.append(record(rand_time(day, hours), team, p))

    if d == 10:  # story 1: retry storm — a failing job re-sends ever larger documents, on Sonnet by mistake
        p = TEAMS["batch-summarizer"]
        for i in range(2600):
            ts = day + timedelta(hours=2, seconds=i * 3)
            records.append(record(ts, "batch-summarizer", p, model=SONNET, scale=9, session="digest-job-7f3a"))

    if d == 8:  # story 3: prompt-attack burst from one session
        p = TEAMS["support-bot"]
        for i in range(140):
            ts = day + timedelta(hours=21, minutes=10, seconds=i * 6)
            records.append(record(ts, "support-bot", p, feature="chat", session="i-attacker-9c1", force="attack"))

# story 6: one agent run, six model calls sharing a trace_id
p = TEAMS["search-rag"]
t0 = START + timedelta(days=12, hours=15, minutes=42, seconds=10)
for step, (feature, model, gap) in enumerate([
        ("plan", HAIKU, 0), ("rewrite-query", HAIKU, 8), ("rerank", HAIKU, 14),
        ("answer", SONNET, 17), ("self-check", HAIKU, 28), ("answer", SONNET, 33)]):
    records.append(record(t0 + timedelta(seconds=gap), "search-rag", p, feature=feature, model=model,
                          trace_id="tr-5f1c9a2e", session="i-017"))

# Bedrock delivers gzipped batches under .../YYYY/MM/DD/HH/. Each file here holds up to 500 records.
shutil.rmtree("data/raw", ignore_errors=True)
records.sort(key=lambda r: r["timestamp"])
buckets = {}
for r in records:
    ts = r["timestamp"]
    buckets.setdefault(f"{ts[0:4]}/{ts[5:7]}/{ts[8:10]}/{ts[11:13]}", []).append(r)
files = 0
for hour, rows in buckets.items():
    os.makedirs(f"{OUT}/{hour}", exist_ok=True)
    for i in range(0, len(rows), 500):
        stamp = rows[i]["timestamp"].replace("-", "").replace(":", "")
        with gzip.open(f"{OUT}/{hour}/{stamp}_{uuid.UUID(int=random.getrandbits(128)).hex[:8]}.json.gz", "wt") as f:
            for r in rows[i:i + 500]:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
        files += 1
print(f"{len(records):,} records in {files} files under {OUT}")
