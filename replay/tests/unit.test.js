// node --test replay/tests
const test = require("node:test");
const assert = require("node:assert/strict");
const { readExif, dateFromFilename } = require("../js/exif.js");
const { selectPhotos, applyCustomOrder, hamming, REASONS } = require("../js/select.js");
const { buildTimeline, activeSegments, defaultTitle } = require("../js/timeline.js");

// 8×8 JPEG: JFIF + EXIF(빅엔디언) — 기종 TestCam, 2026:09:14 18:30:05, 남위 37°33'36" 동경 126°58'48"
const JPEG_B64 =
  "/9j/4AAQSkZJRgABAQAAAQABAAD/4QDiRXhpZgAATU0AKgAAAAgABAEPAAIAAAAIAAAAPgEQAAIAAAAIAAAARodpAAQAAAABAAAAToglAAQAAAABAAAAdAAAAABUZXN0Q2FtAE1vZGVsIFgAAAGQAwACAAAAFAAAAGAAAAAAMjAyNjowOToxNCAxODozMDowNQAABAABAAIAAAACUwAAAAACAAUAAAADAAAAqgADAAIAAAACRQAAAAAEAAUAAAADAAAAwgAAAAAAAAAlAAAAAQAAACEAAAABAAAAJAAAAAEAAAB+AAAAAQAAADoAAAABAAAAMAAAAAH/2wBDABALDA4MChAODQ4SERATGCgaGBYWGDEjJR0oOjM9PDkzODdASFxOQERXRTc4UG1RV19iZ2hnPk1xeXBkeFxlZ2P/2wBDARESEhgVGC8aGi9jQjhCY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2P/wAARCAAIAAgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwBtFFFeWeyf/9k=";

const toArrayBuffer = (buf) => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);

test("EXIF에서 날짜·기종·위치를 읽는다", () => {
  const exif = readExif(toArrayBuffer(Buffer.from(JPEG_B64, "base64")));
  assert.equal(exif.make, "TestCam");
  assert.equal(exif.model, "Model X");
  assert.deepEqual(exif.date, new Date(2026, 8, 14, 18, 30, 5));
  assert.ok(Math.abs(exif.lat - -37.56) < 1e-9);
  assert.ok(Math.abs(exif.lon - 126.98) < 1e-9);
});

test("JPEG가 아니거나 잘린 파일이면 빈 결과", () => {
  assert.deepEqual(readExif(new ArrayBuffer(2)), {});
  assert.deepEqual(readExif(toArrayBuffer(Buffer.from("not a jpeg at all"))), {});
  const truncated = Buffer.from(JPEG_B64, "base64").subarray(0, 60);
  assert.doesNotThrow(() => readExif(toArrayBuffer(truncated)));
});

test("파일 이름에서 날짜를 읽는다", () => {
  assert.deepEqual(dateFromFilename("20260914_183005.jpg"), new Date(2026, 8, 14, 18, 30, 5));
  assert.deepEqual(dateFromFilename("KakaoTalk_20260301_090000123.jpg"), new Date(2026, 2, 1, 9, 0, 0));
  assert.deepEqual(dateFromFilename("IMG-2026-03-01 09.00.00.jpg"), new Date(2026, 2, 1, 9, 0, 0));
  assert.equal(dateFromFilename("IMG_1234.JPG"), null);
  assert.equal(dateFromFilename("20261399_999999.jpg"), null);
});

// ---------------------------------------------------------------- 선별

const BASE = +new Date(2026, 8, 1, 10, 0, 0);
const HOUR = 3600 * 1000;
const DAY = 24 * HOUR;
let nextId = 0;
function photo(over = {}) {
  const id = nextId++;
  return {
    id,
    name: `p${String(id).padStart(4, "0")}.jpg`,
    date: BASE,
    dateSource: "exif",
    aspect: 0.75,
    sharpness: 500,
    brightness: 120,
    // id마다 확실히 다른 해시
    hash: (((id + 1) * 2654435761) >>> 0).toString(16).padStart(8, "0") + ((id * 40503 + 7) >>> 0).toString(16).padStart(8, "0"),
    screenshot: false,
    error: null,
    ...over,
  };
}

test("해밍 거리", () => {
  assert.equal(hamming("0000000000000000", "0000000000000000"), 0);
  assert.equal(hamming("000000000000000f", "0000000000000000"), 4);
  assert.equal(hamming("ffffffffffffffff", "0000000000000000"), 64);
  assert.equal(hamming(null, "00"), Infinity);
});

test("스크린샷·어두운 사진·흔들린 사진·열 수 없는 파일을 뺀다", () => {
  const good = [0, 1, 2, 3].map((i) => photo({ date: BASE + i * HOUR }));
  const shot = photo({ screenshot: true });
  const dark = photo({ brightness: 5 });
  const blurry = photo({ sharpness: 10 });
  const broken = photo({ error: "열 수 없는 파일" });
  const { kept, rejected } = selectPhotos([...good, shot, dark, blurry, broken], { maxCount: 50 });
  assert.deepEqual(kept.map((p) => p.id), good.map((p) => p.id));
  const reasonOf = (p) => rejected.find((r) => r.photo === p).reason;
  assert.equal(reasonOf(shot), REASONS.screenshot);
  assert.equal(reasonOf(dark), REASONS.dark);
  assert.equal(reasonOf(blurry), REASONS.blurry);
  assert.equal(reasonOf(broken), REASONS.error);
});

test("모든 사진이 똑같이 흐리면 흔들림으로 빼지 않는다 (상대 기준)", () => {
  const soft = [0, 1, 2].map((i) => photo({ date: BASE + i * HOUR, sharpness: 50 }));
  assert.equal(selectPhotos(soft).kept.length, 3);
});

test("연속 촬영은 가장 선명한 한 장만 남긴다", () => {
  const burst = [300, 900, 600].map((sharpness, i) =>
    photo({ date: BASE + i * 2000, sharpness, hash: "a5a5a5a5a5a5a5a" + i })
  );
  const later = photo({ date: BASE + 2 * HOUR, hash: "a5a5a5a5a5a5a5a5" }); // 같아 보여도 시간이 멀면 따로
  const { kept, rejected } = selectPhotos([...burst, later]);
  assert.deepEqual(kept.map((p) => p.id), [burst[1].id, later.id]);
  assert.equal(rejected.filter((r) => r.reason === REASONS.duplicate).length, 2);
});

test("분량을 넘으면 날짜(장면)마다 고르게 남긴다", () => {
  const day1 = Array.from({ length: 30 }, (_, i) => photo({ date: BASE + i * 60 * 1000 * 15 }));
  const day2 = Array.from({ length: 6 }, (_, i) => photo({ date: BASE + DAY + i * HOUR }));
  const day3 = [photo({ date: BASE + 2 * DAY })];
  const { kept, rejected } = selectPhotos([...day1, ...day2, ...day3], { maxCount: 10 });
  assert.equal(kept.length, 10);
  const days = kept.map((p) => Math.floor((p.date - BASE) / DAY));
  assert.ok(days.includes(0) && days.includes(1) && days.includes(2), `장면마다 한 장 이상: ${days}`);
  assert.ok(days.filter((d) => d === 0).length > days.filter((d) => d === 1).length, "큰 장면이 더 많이");
  assert.equal(rejected.filter((r) => r.reason === REASONS.trimmed).length, 27);
  assert.deepEqual(kept.map((p) => p.date), kept.map((p) => p.date).slice().sort((a, b) => a - b), "날짜순");
});

test("장면이 분량보다 많으면 장면을 고르게 건너뛴다", () => {
  const days = Array.from({ length: 20 }, (_, i) => photo({ date: BASE + i * DAY }));
  const { kept } = selectPhotos(days, { maxCount: 5 });
  assert.equal(kept.length, 5);
  assert.equal(new Set(kept.map((p) => p.id)).size, 5);
});

test("기간 밖 사진은 세기만 하고, 날짜 모르는 사진은 남긴다", () => {
  const inside = photo({ date: BASE + DAY });
  const outside = photo({ date: BASE + 40 * DAY });
  const undated = photo({ date: null, dateSource: null });
  const result = selectPhotos([inside, outside, undated], { from: BASE, to: BASE + 2 * DAY });
  assert.deepEqual(result.kept.map((p) => p.id), [inside.id, undated.id]);
  assert.equal(result.outOfRange, 1);
});

test("직접 넣은 사진은 필터를 무시하고, 직접 뺀 사진은 빠진다", () => {
  const blurry = photo({ sharpness: 1, date: BASE + HOUR });
  const a = photo({ date: BASE });
  const b = photo({ date: BASE + 2 * HOUR });
  const result = selectPhotos([a, blurry, b], { forceIn: [blurry.id], forceOut: [b.id] });
  assert.deepEqual(result.kept.map((p) => p.id), [a.id, blurry.id]);
  assert.equal(result.rejected.find((r) => r.photo === b).reason, REASONS.manual);
});

test("직접 바꾼 순서를 지키고 새 사진은 날짜 자리에 끼운다", () => {
  const [a, b, c, d] = [0, 1, 2, 3].map((i) => photo({ date: BASE + i * HOUR }));
  assert.deepEqual(applyCustomOrder([a, b, c], null), [a, b, c]);
  const ordered = applyCustomOrder([a, b, c, d], [c.id, a.id, b.id]);
  assert.deepEqual(ordered.map((p) => p.id), [c.id, a.id, b.id, d.id]);
  const early = photo({ date: BASE - HOUR });
  assert.equal(applyCustomOrder([early, a, b], [b.id, a.id])[0], early);
});

// ---------------------------------------------------------------- 타임라인

test("타임라인 길이와 겹침", () => {
  const photos = [0, 1, 2].map((i) => photo({ date: BASE + i * DAY }));
  const tl = buildTimeline(photos, "emotional");
  assert.equal(tl.segments.length, 3);
  assert.equal(tl.duration, 3 * tl.hold + 2.4);
  assert.equal(tl.segments[1].start, tl.hold);
  assert.ok(tl.segments[0].end > tl.segments[1].start, "앞 사진과 겹쳐서 넘어간다");
  assert.equal(tl.segments[0].fadeIn, 0);
  // 겹치는 순간엔 두 장이 같이 보인다
  assert.equal(activeSegments(tl, tl.hold + 0.1).length, 2);
  assert.equal(activeSegments(tl, 0.1).length, 1);
});

test("날짜가 바뀌는 사진에만 날짜 자막", () => {
  const photos = [
    photo({ date: +new Date(2026, 8, 14, 10) }),
    photo({ date: +new Date(2026, 8, 14, 12) }),
    photo({ date: +new Date(2026, 8, 15, 9) }),
    photo({ date: +new Date(2026, 8, 15, 10), dateSource: "file" }),
  ];
  const captions = buildTimeline(photos, "calm").segments.map((s) => s.caption);
  assert.deepEqual(captions, ["9월 14일 월요일", null, "9월 15일 화요일", null]);
});

test("음악 길이에 맞추기", () => {
  const photos = Array.from({ length: 10 }, (_, i) => photo({ date: BASE + i * HOUR }));
  const tl = buildTimeline(photos, "upbeat", { musicDuration: 32.4, fitMusic: true });
  assert.ok(Math.abs(tl.duration - 32.4) < 1e-9);
  const short = buildTimeline(photos, "upbeat", { musicDuration: 3, fitMusic: true });
  assert.equal(short.hold, 0.8, "너무 빠르게는 안 넘긴다");
});

test("기본 제목", () => {
  const sept = [photo({ date: +new Date(2026, 8, 1) }), photo({ date: +new Date(2026, 8, 30) })];
  assert.deepEqual(defaultTitle(sept), { title: "2026년 9월", sub: "9.1 – 9.30" });
  const spring = [photo({ date: +new Date(2026, 2, 5) }), photo({ date: +new Date(2026, 4, 2) })];
  assert.equal(defaultTitle(spring).title, "2026년 3월 – 5월");
  const years = [photo({ date: +new Date(2024, 0, 1) }), photo({ date: +new Date(2026, 0, 1) })];
  assert.equal(defaultTitle(years).title, "2024 – 2026");
  assert.equal(defaultTitle([photo({ dateSource: "file" })]).title, "나의 리플레이");
  assert.equal(buildTimeline([], "calm").duration, 0);
});
