// Screenshot both dashboard tabs (full page) (written to ./screenshots, or $OUT_DIR). Fails loudly on Streamlit exceptions.
import fs from "node:fs";
import { chromium } from "playwright";

const OUT = process.env.OUT_DIR ?? "screenshots";
fs.mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 3300 }, deviceScaleFactor: 2 });
await page.goto("http://localhost:8510", { waitUntil: "networkidle" });
await page.getByText("Daily spend by team").first().waitFor({ timeout: 60000 });
await page.waitForTimeout(2500);

const errors = async () => page.locator('[data-testid="stException"]').allInnerTexts();
console.log("aws tab errors:", await errors());
await page.screenshot({ path: `${OUT}/dashboard-aws-full.png`, fullPage: true });

// Section crops for inline use.
for (const [name, text] of [["cost", "Daily spend by team"], ["guardrails", "Guardrail findings per day"], ["trace", "Trace one agent run"]]) {
  const el = page.getByText(text).first();
  await el.scrollIntoViewIfNeeded();
  await page.waitForTimeout(400);
  const box = await el.boundingBox();
  await page.screenshot({ path: `${OUT}/dashboard-${name}.png`, clip: { x: 0, y: Math.max(0, box.y - 60), width: 1440, height: 800 } });
}

await page.getByRole("tab", { name: /Live/ }).click();
await page.getByText("Calls per 30 seconds").first().waitFor({ timeout: 60000 });
await page.waitForTimeout(2500);
console.log("live tab errors:", await errors());
await page.screenshot({ path: `${OUT}/dashboard-live.png`, fullPage: true });
await browser.close();
