// Render the diagrams and the real query outputs (out/*.txt) to PNGs (written to ./screenshots, or $OUT_DIR).
import fs from "node:fs";
import { chromium } from "playwright";

const DIR = new URL(".", import.meta.url).pathname.replace(/\/$/, "");
const OUT = process.env.OUT_DIR ?? "screenshots";
fs.mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1500, height: 1200 }, deviceScaleFactor: 2 });

await page.goto(`file://${DIR}/diagrams.html`);
await page.locator("#arch").screenshot({ path: `${OUT}/architecture.png` });
await page.locator("#model").screenshot({ path: `${OUT}/data-model.png` });

// Terminal-style renders: the SQL file as typed, followed by DuckDB's actual output.
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
const shots = {
  "terminal-build": [["00_build", "duckdb llm.duckdb < 01_build.sql"]],
  "terminal-anomaly": [["q03_cost_anomaly", null], ["q04_spike_drilldown", null]],
  "terminal-cost": [["q02_cost_by_team_model", null], ["q05_cache", null]],
  "terminal-guardrails": [["q09_guardrail_burst", null], ["q10_guardrail_overhead", null]],
  "terminal-trace": [["q11_trace", null]],
};
for (const [name, parts] of Object.entries(shots)) {
  let body = "";
  for (const [q, cmd] of parts) {
    const sql = cmd ?? fs.readFileSync(`${DIR}/queries/${q}.sql`, "utf8").trim();
    const prompt = cmd ? `<span class="p">$</span> ${esc(sql)}` : `<span class="p">D</span> ${esc(sql).replace(/\n/g, "\n  ")}`;
    body += `<span class="c">${prompt}</span>\n${esc(fs.readFileSync(`${DIR}/out/${q}.txt`, "utf8").trimEnd())}\n\n`;
  }
  await page.setContent(`<style>
    body{margin:0;background:#f9f9f7}
    .w{display:inline-block;background:#1a1a19;border-radius:10px;padding:14px 22px 6px;margin:16px}
    .bar{height:14px;margin-bottom:10px}.bar i{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:7px;background:#52514e}
    pre{margin:0;color:#e8e6df;font:13px/1.45 ui-monospace,Menlo,monospace}
    .c{color:#9ec5f4}.p{color:#eda100}
  </style><div class="w"><div class="bar"><i></i><i></i><i></i></div><pre>${body}</pre></div>`);
  await page.locator(".w").screenshot({ path: `${OUT}/${name}.png` });
}
await browser.close();
console.log(fs.readdirSync(OUT).join("  "));
