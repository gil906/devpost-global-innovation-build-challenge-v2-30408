import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { launchBrowser, ready, startServer } from "./browser-runtime.mjs";

const server = await startServer();
let browser;
try {
  browser = await launchBrowser();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1120 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const errors = [];
  const external = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error" && !message.text().includes("status of 422")) errors.push(message.text()); });
  page.on("request", (request) => { if (!request.url().startsWith(server.base) && !request.url().startsWith("blob:")) external.push(request.url()); });
  page.on("dialog", (dialog) => dialog.accept());
  await ready(page, server.base);
  assert.equal(await page.locator("#transfers tr").count(), 6);
  assert.equal(await page.locator("#network-map .map-label").count(), 10);
  assert.equal(await page.locator("#metrics .metric-number").nth(2).innerText(), "+60");
  await mkdir("docs/media", { recursive: true });
  await page.screenshot({ path: "docs/media/01-plan-overview.png", fullPage: true });

  await page.getByRole("button", { name: "Supply & hubs" }).click();
  assert.equal(await page.locator("#donor-list .location-card").count(), 6);
  assert.equal(await page.locator("#hub-list .location-card").count(), 4);
  await page.screenshot({ path: "docs/media/02-supply-and-hubs.png", fullPage: true });

  await page.getByRole("button", { name: "Method & evidence" }).click();
  assert.equal(await page.locator("#pair-audit tr").count(), 24);
  await page.screenshot({ path: "docs/media/03-method-and-evidence.png", fullPage: true });

  await page.getByRole("button", { name: "Supply & hubs" }).click();
  await page.getByRole("button", { name: "Edit Sunrise bakery", exact: true }).click();
  await page.getByLabel("Servings available").fill("45");
  await page.getByRole("button", { name: "Apply changes" }).click();
  await page.locator("#editor-dialog").waitFor({ state: "hidden" });
  assert.equal(await page.locator("#stale-warning").isVisible(), true);
  await page.getByRole("button", { name: "Plan overview", exact: true }).click();
  await page.getByRole("button", { name: "Export plan CSV" }).click();
  assert.match(await page.locator("#error").innerText(), /out of date/);
  await page.getByRole("button", { name: "Run planner" }).click();
  await page.waitForFunction(() => document.querySelector("#metrics .metric-number").textContent === "215");
  assert.equal(await page.locator("#stale-warning").isVisible(), false);

  await page.getByLabel("Scenario name", { exact: true }).fill("Browser verification snapshot");
  await page.getByRole("button", { name: "Save snapshot", exact: true }).click();
  await page.waitForFunction(() => document.querySelector("#saved-count").textContent === "1");
  await page.reload();
  await page.waitForFunction(() => document.querySelector("#metrics .metric-number")?.textContent === "230");
  await page.getByRole("button", { name: "Snapshots" }).click();
  await page.getByRole("button", { name: "Load Browser verification snapshot" }).click();
  await page.waitForFunction(() => document.querySelector("#metrics .metric-number").textContent === "215");
  assert.equal(await page.locator("#scenario-title").innerText(), "Browser verification snapshot");

  const [csvDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export plan CSV" }).click(),
  ]);
  const csv = await readFile(await csvDownload.path(), "utf8");
  assert.match(csv, /Sunrise bakery,Eastside breakfast club,bakery,45/);
  await page.getByRole("button", { name: "Supply & hubs" }).click();
  const [jsonDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export scenario JSON" }).click(),
  ]);
  const exported = JSON.parse(await readFile(await jsonDownload.path(), "utf8"));
  assert.equal(exported.donors[0].quantity, 45);

  const maliciousName = '<img src=x onerror="window.injected=true">';
  exported.name = maliciousName;
  exported.donors[0].name = maliciousName;
  await page.locator("#import-file").setInputFiles({ name: "scenario.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(exported)) });
  await page.waitForFunction((name) => document.querySelector("#scenario-title").textContent === name, maliciousName);
  assert.equal(await page.evaluate(() => window.injected), undefined);
  assert.equal(await page.locator("#donor-list img").count(), 0);
  assert.equal(await page.locator("#donor-list").getByText(maliciousName, { exact: true }).count(), 1);
  const invalid = { ...exported, speed_kph: -1 };
  await page.locator("#import-file").setInputFiles({ name: "invalid.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(invalid)) });
  await page.waitForFunction(() => document.querySelector("#error").textContent.includes("speed_kph"));
  assert.equal(await page.locator("#scenario-title").innerText(), maliciousName);

  await page.getByRole("button", { name: "+ Add hub", exact: true }).click();
  await page.getByLabel("Fictional location name").fill("New test hub");
  await page.getByLabel("Requested servings").fill("12");
  await page.getByRole("button", { name: "Apply changes" }).click();
  await page.locator("#editor-dialog").waitFor({ state: "hidden" });
  assert.equal(await page.locator("#hub-list .location-card").count(), 5);
  await page.getByRole("button", { name: "Remove New test hub", exact: true }).click();
  assert.equal(await page.locator("#hub-list .location-card").count(), 4);
  await page.getByRole("button", { name: "+ Add batch", exact: true }).click();
  await page.getByLabel("Fictional location name").fill("New test batch");
  await page.getByRole("button", { name: "Apply changes" }).click();
  await page.locator("#editor-dialog").waitFor({ state: "hidden" });
  assert.equal(await page.locator("#donor-list .location-card").count(), 7);
  await page.getByRole("button", { name: "Remove New test batch", exact: true }).click();
  assert.equal(await page.locator("#donor-list .location-card").count(), 6);

  const isolated = await browser.newContext();
  const other = await isolated.newPage();
  await ready(other, server.base);
  assert.equal(await other.locator("#saved-count").innerText(), "0");
  await isolated.close();
  await page.getByRole("button", { name: "Snapshots" }).click();
  await page.getByRole("button", { name: "Delete Browser verification snapshot" }).click();
  await page.waitForFunction(() => document.querySelector("#saved-count").textContent === "0");
  await page.getByRole("button", { name: "Close snapshots" }).click();

  await page.getByRole("button", { name: "Reset sample" }).click();
  await page.waitForFunction(() => document.querySelector("#metrics .metric-number").textContent === "230");
  await page.locator("#max-distance").fill("2");
  await page.getByRole("button", { name: "Run planner" }).click();
  await page.waitForFunction(() => !document.querySelector("#run-button").disabled && document.querySelector("#metrics .metric-number").textContent !== "230");
  const reduced = Number(await page.locator("#metrics .metric-number").first().innerText());
  assert.ok(reduced < 230 && reduced >= 0);
  await page.getByRole("button", { name: "Reset sample" }).click();
  await page.waitForFunction(() => document.querySelector("#metrics .metric-number").textContent === "230");

  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  await page.getByRole("button", { name: "Adjust plan parameters" }).click();
  assert.equal(await page.getByLabel("Start time").isVisible(), true);
  await page.getByLabel("Vehicle capacity (servings)").fill("20");
  await page.getByRole("button", { name: "Run planner" }).click();
  await page.waitForFunction(() => !document.querySelector("#run-button").disabled);
  assert.equal(await page.locator("#metrics .metric-number").first().innerText(), "230");
  assert.ok(Number(await page.locator("#metrics .metric-number").nth(3).innerText()) > 10);
  await page.getByRole("button", { name: "Adjust plan parameters" }).click();
  await page.screenshot({ path: "docs/media/04-mobile-plan.png", fullPage: true });

  assert.deepEqual(errors, [], "Browser console/page errors");
  assert.deepEqual(external, [], "Unexpected network dependency");
  await context.close();
  console.log("PASS: browser rendering, editing, add/remove, validation, stale guards, snapshot reload/isolation/delete, CSV/JSON downloads, import/XSS, distance what-if, mobile layout, and zero external requests.");
  console.log(`Screenshots: ${resolve("docs/media")}`);
} finally {
  if (browser) await browser.close();
  await server.stop();
}
