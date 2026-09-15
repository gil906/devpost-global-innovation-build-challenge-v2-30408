import assert from "node:assert/strict";
import { mkdir, rm } from "node:fs/promises";
import { resolve } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import { launchBrowser, ready, startServer } from "./browser-runtime.mjs";

const server = await startServer();
let browser;
const temporary = resolve(process.env.APP_DATA_DIR || ".runtime", "demo-recording");
await mkdir(temporary, { recursive: true });
await mkdir("docs/media", { recursive: true });
try {
  browser = await launchBrowser();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    recordVideo: { dir: temporary, size: { width: 1440, height: 1000 } },
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("dialog", (dialog) => dialog.accept());
  await ready(page, server.base);
  await page.evaluate(() => {
    const caption = document.createElement("div");
    caption.id = "demo-caption";
    caption.className = "demo-caption";
    caption.setAttribute("aria-live", "polite");
    document.body.append(caption);
  });
  const scene = async (caption, action = async () => {}, duration = 11000) => {
    await page.locator("#demo-caption").evaluate((node, text) => { node.textContent = text; }, caption);
    await action();
    await sleep(duration);
  };
  await scene("CommonTable: good food, better connections. An Open-track prototype for the Global Innovation Build Challenge V2.");
  await scene("Community surplus is a matching problem: the closest destination is not always the best use of a scarce food category.", async () => {
    await page.locator(".tabs").scrollIntoViewIfNeeded();
    await page.evaluate(() => window.scrollTo(0, document.querySelector(".tabs").getBoundingClientRect().top + window.scrollY - 25));
  });
  await scene("This is a synthetic neighborhood: six food batches and four receiving hubs. No real beneficiaries, personal information, or live dispatch.", async () => {
    await page.getByRole("button", { name: "Supply & hubs" }).click();
  });
  await scene("Every batch declares quantity, category, location and expiry. Every hub declares demand, capacity, accepted categories and cold storage.", async () => {
    await page.getByRole("button", { name: "Edit Sunrise bakery", exact: true }).click();
  });
  await scene("The planner checks those constraints before allocating anything. In this sample it connects 230 servings, versus 170 with nearest-first.", async () => {
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await page.getByRole("button", { name: "Plan overview", exact: true }).click();
  });
  await scene("The bakery serves the bakery-only breakfast club, preserving the flexible pantry for produce. Residual edges let the optimizer reconsider greedy choices.");
  await scene("What if volunteers can only cover two kilometers? Change the maximum leg and run the same exact algorithm again.", async () => {
    await page.locator("#max-distance").fill("2");
    await page.getByRole("button", { name: "Run planner" }).click();
    await page.waitForFunction(() => !document.querySelector("#run-button").disabled);
  });
  await scene("Coverage drops because some connections are no longer eligible. The plan exposes those gaps instead of silently ignoring unassigned food.", async () => {
    await page.locator("#unassigned").scrollIntoViewIfNeeded();
    const details = page.locator("#unassigned details").first();
    await details.locator("summary").click();
  });
  await scene("Restore the original five-and-a-half-kilometer limit: 230 servings again. Ten parallel loads, not a scheduled fleet or optimized driving route.", async () => {
    await page.locator("#max-distance").fill("5.5");
    await page.getByRole("button", { name: "Run planner" }).click();
    await page.waitForFunction(() => document.querySelector("#metrics .metric-number").textContent === "230");
    await page.locator(".tabs").scrollIntoViewIfNeeded();
  });
  await scene("Save a snapshot to revisit a what-if. Anonymous browser sessions are isolated; snapshots last seven days. Export JSON for a permanent copy.", async () => {
    await page.getByRole("button", { name: "Save snapshot", exact: true }).click();
    await page.waitForFunction(() => document.querySelector("#saved-count").textContent === "1");
    await page.getByRole("button", { name: "Snapshots" }).click();
  });
  await scene("Export a CSV handoff plan: source, destination, category, servings, direct distance, times, and independent loads.", async () => {
    await page.getByRole("button", { name: "Close snapshots" }).click();
    await page.locator("#transfers").scrollIntoViewIfNeeded();
    const [download] = await Promise.all([
      page.waitForEvent("download"), page.getByRole("button", { name: "Export plan CSV" }).click(),
    ]);
    assert.equal(download.suggestedFilename(), "commontable-transfers.csv");
  });
  await scene("Under the hood: maximum flow first, then minimum serving-kilometers. Python, SQLite and a browser interface; no hosted APIs or model inference.", async () => {
    await page.getByRole("button", { name: "Method & evidence" }).click();
    await page.locator(".method-panel").scrollIntoViewIfNeeded();
  });
  await scene("The algorithm is checked against 180 exhaustive small-network cases. Every possible batch-to-hub connection has a visible eligibility explanation.", async () => {
    await page.locator("#pair-audit").scrollIntoViewIfNeeded();
  });
  await scene("More at the table, less left behind. A transparent planning lab, not a food-safety system: synthetic inputs, direct distances and enough parallel vehicles are explicit assumptions.", async () => {
    await page.getByRole("button", { name: "Plan overview", exact: true }).click();
    await page.evaluate(() => window.scrollTo(0, document.querySelector(".tabs").getBoundingClientRect().top + window.scrollY - 25));
  });
  assert.deepEqual(errors, []);
  const video = page.video();
  await context.close();
  await video.saveAs("docs/media/commontable-demo.webm");
  await video.delete();
  console.log("Recorded docs/media/commontable-demo.webm with burned-in English captions and real application interactions.");
} finally {
  if (browser) await browser.close();
  await server.stop();
  await rm(temporary, { recursive: true, force: true });
}
