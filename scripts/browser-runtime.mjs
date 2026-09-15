import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, mkdir, rm } from "node:fs/promises";
import { resolve } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";

process.env.PLAYWRIGHT_BROWSERS_PATH = resolve("node_modules/.cache/ms-playwright");
const { chromium } = await import("playwright");
const libraryRoot = resolve("node_modules/.cache/browser-sysroot");
const architecture = process.arch === "arm64" ? "aarch64-linux-gnu" : "x86_64-linux-gnu";
const browserEnvironment = { ...process.env };
if (existsSync(libraryRoot)) {
  browserEnvironment.LD_LIBRARY_PATH = `${libraryRoot}/usr/lib/${architecture}:${libraryRoot}/lib/${architecture}`;
  browserEnvironment.FONTCONFIG_FILE = resolve("scripts/browser-fonts.conf");
  process.env.PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS = "1";
}

export async function launchBrowser() {
  const temporary = resolve(process.env.APP_DATA_DIR || ".runtime", "browser-temp");
  await mkdir(temporary, { recursive: true });
  process.env.TMPDIR = temporary;
  browserEnvironment.TMPDIR = temporary;
  return chromium.launch({ headless: true, env: browserEnvironment });
}

export async function startServer() {
  const base = "http://127.0.0.1:8764";
  try {
    await fetch(`${base}/health`, { signal: AbortSignal.timeout(500) });
    throw new Error("Port 8764 is already occupied. Refusing to use or stop an unrelated server.");
  } catch (error) {
    if (!["TypeError", "TimeoutError"].includes(error.name)) throw error;
  }
  const runtime = resolve(process.env.APP_DATA_DIR || ".runtime");
  await mkdir(runtime, { recursive: true });
  const directory = await mkdtemp(`${runtime}/browser-`);
  const child = spawn("python3", ["app.py", "--host", "0.0.0.0", "--port", "8764"], {
    env: { ...process.env, APP_DATA_DIR: directory }, stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  let spawnError;
  child.on("error", (error) => { spawnError = error; });
  child.stdout.on("data", (data) => { output += data; });
  child.stderr.on("data", (data) => { output += data; });
  const exited = new Promise((done) => child.on("close", done));
  const stop = async () => {
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
    await exited;
    await rm(directory, { recursive: true, force: true });
  };
  try {
    for (let attempt = 0; attempt < 60; attempt++) {
      if (spawnError) throw spawnError;
      if (child.exitCode !== null) throw new Error(`Server exited:\n${output}`);
      try {
        const response = await fetch(`${base}/health`, { signal: AbortSignal.timeout(500) });
        if (response.ok && (await response.json()).app === "CommonTable") return { base, stop };
      } catch (error) {
        if (!["TypeError", "TimeoutError"].includes(error.name)) throw error;
      }
      await sleep(100);
    }
    throw new Error(`Server did not become healthy:\n${output}`);
  } catch (error) {
    await stop();
    throw error;
  }
}

export async function ready(page, base) {
  await page.goto(base);
  await page.waitForFunction(() => document.querySelector("#metrics .metric-number")?.textContent === "230");
  await page.waitForFunction(() => document.querySelector("#saved-count")?.textContent === "0");
}
