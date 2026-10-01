"""LLM analytics dashboard: DuckDB in, Streamlit out.

    .venv/bin/streamlit run dashboard.py

Tab 1 reads the curated Parquet built by 01_build.sql (Bedrock invocation-log shape, 14 days).
Tab 2 reads the live gateway's NDJSON files directly on every refresh, so calls you send through
LiteLLM (:4010) show up without rebuilding anything.
"""
import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="LLM Analytics · DuckDB", layout="wide")

# Reference palette (validated categorical slots 1-4), chart chrome, status colours.
TEAM_COLORS = {"search-rag": "#2a78d6", "code-review": "#eb6834",
               "support-bot": "#1baf7a", "batch-summarizer": "#eda100"}
TEAMS = list(TEAM_COLORS)
INK, MUTED, GRID = "#0b0b0b", "#898781", "#e1e0d9"
CRITICAL, WARNING = "#d03b3b", "#fab219"


def style(fig, height=320):
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=70, b=8), title=dict(y=0.97, x=0.01, font=dict(size=15)), plot_bgcolor="#fcfcfb",
                      paper_bgcolor="#fcfcfb", font=dict(color=INK, size=13),
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, title=None), bargap=0.25)
    fig.update_xaxes(showgrid=False, linecolor="#c3c2b7", tickfont=dict(color=MUTED), title=None)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, tickfont=dict(color=MUTED), title=None)
    fig.update_traces(marker_line_color="#fcfcfb", marker_line_width=2, selector=dict(type="bar"))
    return fig


@st.cache_resource
def con():
    c = duckdb.connect()
    c.execute("CREATE VIEW costed AS SELECT * FROM read_parquet('data/curated/invocations/*/*.parquet', hive_partitioning = true)")
    c.execute("CREATE VIEW guardrail_events AS SELECT * FROM 'data/curated/guardrail_events.parquet'")
    return c


def q(sql, **params):
    return con().execute(sql, params).df()


st.title("LLM analytics")
st.caption("Every number on this page is one DuckDB query over log files. No warehouse, no server.")
tab_aws, tab_live = st.tabs(["AWS · Bedrock logs (SYNTHETIC demo data)", "Live · local LiteLLM gateway"])

# ----------------------------------------------------------------------------------- AWS tab
with tab_aws:
    st.warning("Synthetic data from gen_logs.py, in the real Bedrock log format. No Bedrock calls were made; "
               "costs are example token prices applied to invented records.", icon="⚠️")
    k = q("""SELECT count(*) calls, sum(cost_usd) usd, sum(cache_saved_usd) saved,
                    count(*) FILTER (stop_reason = 'guardrail_intervened') blocked,
                    count(*) FILTER (stop_reason = 'max_tokens') truncated
             FROM costed""").iloc[0]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Model calls", f"{k.calls:,.0f}")
    c2.metric("Spend", f"${k.usd:,.2f}")
    c3.metric("Saved by prompt caching", f"${k.saved:,.2f}")
    c4.metric("Blocked by guardrail", f"{k.blocked:,.0f}")
    c5.metric("Truncated answers", f"{k.truncated:,.0f}")

    st.subheader("Cost")
    daily = q("SELECT dt, team, sum(cost_usd) usd FROM costed GROUP BY ALL ORDER BY dt")
    fig = px.bar(daily, x="dt", y="usd", color="team", color_discrete_map=TEAM_COLORS,
                 category_orders={"team": TEAMS}, title="Daily spend by team (USD)")
    fig.update_traces(hovertemplate="%{x|%b %d} · %{fullData.name}: $%{y:,.2f}<extra></extra>")
    st.plotly_chart(style(fig, 360), use_container_width=True)

    left, right = st.columns(2)
    with left:
        st.markdown("**Anomalies** · team-days above 3× their trailing 7-day median")
        an = q(open("queries/q03_cost_anomaly.sql").read())
        an["dt"] = an["dt"].astype(str).str[:10]
        st.dataframe(an, hide_index=True, use_container_width=True)
        st.markdown("**Drill-down** · who caused the spike")
        st.dataframe(q(open("queries/q04_spike_drilldown.sql").read()), hide_index=True, use_container_width=True)
    with right:
        tm = q("""SELECT team, split_part(model_id, '.', 2) AS model, sum(cost_usd) usd
                  FROM costed GROUP BY ALL ORDER BY usd""")
        tm["model"] = tm["model"].str.replace(r"-\d{8}-v1:0|-v1:0", "", regex=True)
        fig = px.bar(tm, x="usd", y="team", color="team", orientation="h", text="model",
                     color_discrete_map=TEAM_COLORS, title="Spend by team and model (USD)")
        fig.update_traces(textposition="inside", insidetextanchor="start", textfont_color="#ffffff",
                          hovertemplate="%{y} · %{text}: $%{x:,.2f}<extra></extra>")
        st.plotly_chart(style(fig).update_layout(showlegend=False), use_container_width=True)
        st.markdown("**Prompt caching** · share of input served from cache")
        st.dataframe(q(open("queries/q05_cache.sql").read()), hide_index=True, use_container_width=True)

    st.subheader("Quality and latency")
    left, right = st.columns(2)
    with left:
        lat = q("""SELECT split_part(model_id, '.', 2) model,
                          quantile_cont(latency_ms, 0.5) p50, quantile_cont(latency_ms, 0.95) p95
                   FROM costed WHERE stop_reason <> 'guardrail_intervened' GROUP BY ALL ORDER BY p95""")
        lat["model"] = lat["model"].str.replace(r"-\d{8}-v1:0|-v1:0", "", regex=True)
        fig = go.Figure([go.Bar(name="p50", y=lat.model, x=lat.p50, orientation="h", marker_color="#86b6ef"),
                         go.Bar(name="p95", y=lat.model, x=lat.p95, orientation="h", marker_color="#1c5cab")])
        fig.update_traces(hovertemplate="%{y} %{fullData.name}: %{x:,.0f} ms<extra></extra>")
        st.plotly_chart(style(fig).update_layout(title="Latency by model (ms)", barmode="group"), use_container_width=True)
    with right:
        st.markdown("**How answers ended** · truncated answers are paid for and still wrong")
        st.dataframe(q(open("queries/q07_stop_reasons.sql").read()), hide_index=True, use_container_width=True)

    st.subheader("Guardrails")
    left, right = st.columns(2)
    with left:
        g = q("""SELECT dt, policy || ' · ' || action AS kind, count(*) n FROM guardrail_events
                 GROUP BY ALL ORDER BY dt""")
        fig = px.bar(g, x="dt", y="n", color="kind", title="Guardrail findings per day",
                     color_discrete_sequence=["#2a78d6", "#eb6834", "#1baf7a", "#eda100"])
        fig.update_traces(hovertemplate="%{x|%b %d} · %{fullData.name}: %{y}<extra></extra>")
        st.plotly_chart(style(fig), use_container_width=True)
    with right:
        st.markdown("**Repeat offenders** · sessions blocked for prompt attacks ≥ 5 times")
        st.dataframe(q(open("queries/q09_guardrail_burst.sql").read()), hide_index=True, use_container_width=True)
        st.markdown("**Top findings**")
        st.dataframe(q(open("queries/q08_guardrail_summary.sql").read()), hide_index=True, use_container_width=True)

    st.subheader("Trace one agent run")
    tid = st.text_input("trace_id", "tr-5f1c9a2e")
    tr = q("""SELECT ts, feature, split_part(model_id, '.', 2) model, input_tokens, output_tokens,
                     latency_ms, cost_usd FROM costed WHERE trace_id = $tid ORDER BY ts""", tid=tid)
    if len(tr):
        tr["start"] = tr.ts
        tr["end"] = tr.ts + pd.to_timedelta(tr.latency_ms, unit="ms")
        tr["step"] = [f"{i + 1}. {f}" for i, f in enumerate(tr.feature)]
        tr["model"] = tr["model"].str.replace(r"-\d{8}-v1:0|-v1:0", "", regex=True)
        fig = px.timeline(tr, x_start="start", x_end="end", y="step", color="model",
                          color_discrete_sequence=["#2a78d6", "#eb6834"], title=f"{tid} · {len(tr)} calls · ${tr.cost_usd.sum():.4f}")
        fig.update_yaxes(categoryorder="array", categoryarray=list(tr.step)[::-1])
        st.plotly_chart(style(fig, 300), use_container_width=True)
        st.dataframe(tr[["step", "model", "input_tokens", "output_tokens", "latency_ms", "cost_usd"]],
                     hide_index=True, use_container_width=True)

# ---------------------------------------------------------------------------------- Live tab
with tab_live:
    st.caption("Reads data/litellm/dt=*/*.ndjson on every refresh. Send calls to http://127.0.0.1:4010, then press Refresh.")
    st.button("Refresh")
    live = duckdb.connect()
    live.execute(open("02_gateway.sql").read().rsplit("SELECT status", 1)[0])  # build gw_* tables in memory
    L = lambda sql: live.execute(sql).df()

    k = L("""SELECT count(*) calls, sum(cost_usd) usd, count(*) FILTER (status = 'blocked') blocked,
                    (SELECT count(*) FROM gw_guardrail_events WHERE policy = 'pii') pii,
                    max(ts) last_call FROM gw_calls""").iloc[0]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Calls through the gateway", f"{k.calls:,.0f}")
    c2.metric("Shadow cost", f"${k.usd:,.4f}")
    c3.metric("Blocked (prompt attack)", f"{k.blocked:,.0f}")
    c4.metric("PII anonymized", f"{k.pii:,.0f}")
    c5.metric("Last call (UTC)", str(k.last_call)[11:19] if k.last_call is not None else "–")

    left, right = st.columns(2)
    with left:
        m = L("""SELECT time_bucket(INTERVAL 30 SECOND, ts) t, team, count(*) n FROM gw_calls
                 GROUP BY ALL ORDER BY t""")
        fig = px.bar(m, x="t", y="n", color="team", color_discrete_map=TEAM_COLORS,
                     category_orders={"team": TEAMS}, title="Calls per 30 seconds")
        st.plotly_chart(style(fig), use_container_width=True)
    with right:
        c = L("""SELECT team, model, count(*) calls, round(sum(cost_usd), 4) usd,
                        round(median(latency_ms)) p50_ms, round(quantile_cont(latency_ms, 0.95)) p95_ms,
                        round(100 * count(*) FILTER (stop_reason = 'length') / count(*)) AS pct_truncated
                 FROM gw_calls WHERE status = 'success' GROUP BY ALL ORDER BY usd DESC""")
        st.markdown("**Cost, latency and truncation by team and model**")
        st.dataframe(c, hide_index=True, use_container_width=True)

    left, right = st.columns(2)
    with left:
        st.markdown("**Guardrail findings**")
        st.dataframe(L("""SELECT policy, finding, action, count(*) events, count(DISTINCT session) sessions
                          FROM gw_guardrail_events GROUP BY ALL ORDER BY events DESC"""),
                     hide_index=True, use_container_width=True)
    with right:
        st.markdown("**Latest calls**")
        st.dataframe(L("""SELECT strftime(ts, '%H:%M:%S') AS time, team, feature, model, status, stop_reason,
                                 input_tokens in_tok, output_tokens out_tok, round(latency_ms) ms
                          FROM gw_calls ORDER BY ts DESC LIMIT 12"""),
                     hide_index=True, use_container_width=True)
