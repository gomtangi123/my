// 브라우저에서 처음부터 끝까지: 사진 고르기 → 선별 확인 → 음악 → 영상 만들기
//
//   python replay/tests/make_photos.py /tmp/replay-photos
//   node replay/tests/e2e.mjs /tmp/replay-photos [결과 폴더]
//
// playwright가 필요하다 (npm i -D playwright 또는 전역 설치 + NODE_PATH).
import { createRequire } from "node:module";
import { readdirSync, writeFileSync, mkdirSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const here = dirname(fileURLToPath(import.meta.url));
const photosDir = resolve(process.argv[2] || "replay-test-photos");
const outDir = resolve(process.argv[3] || photosDir);
mkdirSync(outDir, { recursive: true });

const files = readdirSync(photosDir).filter((f) => !f.endsWith(".wav")).map((f) => join(photosDir, f));
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
  args: ["--autoplay-policy=no-user-gesture-required"],
});
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

await page.goto(pathToFileURL(join(here, "..", "index.html")).href);
await page.setInputFiles("#file-input", files);
await page.waitForSelector("#step-edit:not([hidden])", { timeout: 60_000 });

const picked = await page.evaluate(() => {
  const { state } = window.__replay;
  return {
    kept: state.kept.map((p) => p.name),
    rejected: Object.fromEntries(state.rejected.map((r) => [r.photo.name, r.reason])),
    kakao: state.photos.find((p) => p.name.startsWith("KakaoTalk")).dateSource,
    sharpness: Object.fromEntries(state.photos.map((p) => [p.name, Math.round(p.sharpness)])),
  };
});
console.log("남은 사진:", picked.kept.join(", "));
console.log("뺀 사진:", picked.rejected);

const expectedKept = files
  .map((f) => f.split("/").pop())
  .filter((n) => n.startsWith("keep_") || n === "burst_b.jpg" || n.startsWith("KakaoTalk"));
assert.deepEqual([...picked.kept].sort(), expectedKept.sort(), JSON.stringify(picked.sharpness));
assert.equal(picked.rejected["burst_a.jpg"], "비슷한 사진");
assert.equal(picked.rejected["burst_c.jpg"], "비슷한 사진");
assert.equal(picked.rejected["blurry_day2.jpg"], "흔들림");
assert.equal(picked.rejected["dark_day2.jpg"], "너무 어두움");
assert.equal(picked.rejected["shot_Screenshot_20260913-101010.png"], "스크린샷");
assert.equal(picked.rejected["broken_file.jpg"], "열 수 없는 파일");
assert.equal(picked.kakao, "filename");
// 날짜순: 9/5 → 9/12 → 9/20
assert.ok(picked.kept[0].startsWith("keep_day1"));
assert.ok(picked.kept.at(-1).startsWith("KakaoTalk"));

// 직접 빼기 → 다시 넣기
await page.click('#kept .tile:first-child [data-act="remove"]');
assert.equal(await page.locator("#kept .tile").count(), expectedKept.length - 1);
await page.click("#rejected-box summary");
await page.click('#rejected .tile:has(.badge:text("직접 뺌")) [data-act="add"]');
assert.equal(await page.locator("#kept .tile").count(), expectedKept.length);

// 순서 바꾸기
const before = await page.evaluate(() => window.__replay.state.kept.map((p) => p.id));
await page.click('#kept .tile:nth-child(1) [data-act="right"]');
const after = await page.evaluate(() => window.__replay.state.kept.map((p) => p.id));
assert.deepEqual(after.slice(0, 2), [before[1], before[0]]);

await page.fill("#title", "테스트 여행");
await page.click('#mood .chip[data-value="upbeat"]');
await page.setInputFiles("#music-input", join(photosDir, "music.wav"));
await page.waitForSelector("#fit-music-label:not([hidden])");
const duration = await page.evaluate(() => window.__replay.player.duration);
console.log("영상 길이:", duration.toFixed(2), "초");
assert.ok(Math.abs(duration - 6) < 0.01 || duration > 6, "음악(6초)에 맞추거나 최소 길이");

await page.evaluate(() => window.__replay.player.seek(1.0));
await page.screenshot({ path: join(outDir, "edit.png"), fullPage: true });

await page.click("#export");
await page.waitForSelector("#result:not([hidden])", { timeout: 120_000 });
const video = await page.evaluate(async () => {
  const link = document.getElementById("download");
  const blob = await (await fetch(link.href)).blob();
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return { name: link.download, type: blob.type, base64: btoa(binary) };
});
const videoPath = join(outDir, video.name);
writeFileSync(videoPath, Buffer.from(video.base64, "base64"));
console.log("영상:", videoPath, video.type);
await page.screenshot({ path: join(outDir, "result.png"), fullPage: true });

await browser.close();
assert.deepEqual(errors, [], "브라우저 콘솔 오류");
console.log("통과");
