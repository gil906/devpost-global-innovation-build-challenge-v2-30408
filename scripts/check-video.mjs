import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { launchBrowser } from "./browser-runtime.mjs";

const bytes = await readFile("docs/media/commontable-demo.webm");
const browser = await launchBrowser();
try {
  const page = await browser.newPage();
  page.setDefaultTimeout(15000);
  await page.route("http://127.0.0.1:8764/**", async (route) => {
    if (new URL(route.request().url()).pathname === "/demo.webm") {
      const range = /^bytes=(\d+)-(\d*)$/.exec(route.request().headers().range || "");
      const start = range ? Number(range[1]) : 0;
      const end = range?.[2] ? Math.min(Number(range[2]), bytes.length - 1) : bytes.length - 1;
      await route.fulfill({
        status: range ? 206 : 200, contentType: "video/webm", body: bytes.subarray(start, end + 1),
        headers: { "Accept-Ranges": "bytes", "Content-Length": String(end - start + 1),
          ...(range ? { "Content-Range": `bytes ${start}-${end}/${bytes.length}` } : {}) },
      });
    } else {
      await route.fulfill({ status: 200, contentType: "text/html",
        body: '<!doctype html><title>Video verification</title><video preload="auto" src="/demo.webm"></video>' });
    }
  });
  // In-memory, same-origin responses permit checking decoded pixels without a server.
  await page.goto("http://127.0.0.1:8764/media-check");
  await page.waitForFunction(() => document.querySelector("video")?.readyState >= 2);
  const result = await page.locator("video").evaluate(async (video) => {
    video.pause();
    const frames = [];
    for (const second of [5, 75, 150]) {
      await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error("Video seek timed out")), 10000);
        video.requestVideoFrameCallback(() => { clearTimeout(timeout); resolve(); });
        video.currentTime = second;
      });
      const canvas = document.createElement("canvas");
      canvas.width = 144;
      canvas.height = 100;
      const context = canvas.getContext("2d");
      context.drawImage(video, 0, 0, 144, 100);
      const pixels = context.getImageData(0, 0, 144, 100).data;
      const colors = new Set();
      let checksum = 0;
      for (let i = 0; i < pixels.length; i += 4) {
        colors.add(pixels.slice(i, i + 3).join(","));
        checksum = (checksum * 31 + pixels[i] + pixels[i + 1] * 2 + pixels[i + 2] * 3) >>> 0;
      }
      frames.push({ second, colors: colors.size, checksum });
    }
    return { duration: video.duration, width: video.videoWidth, height: video.videoHeight, frames };
  });
  assert.ok(result.duration >= 120 && result.duration <= 300);
  assert.equal(result.width, 1440);
  assert.equal(result.height, 1000);
  for (const frame of result.frames) assert.ok(frame.colors > 50, `Frame at ${frame.second}s has only ${frame.colors} colors`);
  assert.equal(new Set(result.frames.map((frame) => frame.checksum)).size, 3);
  console.log(`PASS: Chromium decoded the ${result.duration.toFixed(2)}s demo at 1440x1000; nonblank, distinct frames at 5s, 75s and 150s.`);
} finally {
  await browser.close();
}
