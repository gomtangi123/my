/* 사진 수백~수천 장에서 영상에 넣을 사진을 고른다. (화면·브라우저와 무관한 순수 로직)
 *
 * 사진 하나는 analyze.js가 만든 이런 모양이다:
 *   { id, name, date(ms|null), dateSource, lat, lon, aspect,
 *     sharpness, brightness, hash(16자리 hex), screenshot, error }
 *
 * 순서: 기간 → 못 쓰는 사진(스크린샷·어두움·흔들림) → 연속 촬영 중복 → 분량 맞추기
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Replay = Object.assign(root.Replay || {}, api);
})(typeof self !== "undefined" ? self : this, function () {
  const REASONS = {
    error: "열 수 없는 파일",
    screenshot: "스크린샷",
    dark: "너무 어두움",
    blurry: "흔들림",
    duplicate: "비슷한 사진",
    trimmed: "분량 조절",
    manual: "직접 뺌",
  };

  const DARK_LIMIT = 18; // 평균 밝기(0~255)
  const BLUR_ABSOLUTE = 60; // 라플라시안 분산, 256px 축소본 기준
  const BLUR_RELATIVE = 0.35; // 이번 사진들 중앙값 대비
  const DUP_BITS = 8; // dHash 64비트 중 다른 비트 수
  const DUP_BITS_NO_DATE = 5; // 날짜를 모를 땐 더 엄격하게
  const DUP_WINDOW_MS = 10 * 60 * 1000;
  const SCENE_GAP_MS = 3 * 60 * 60 * 1000;
  const SCENE_DISTANCE_KM = 20;

  const POPCOUNT = [0, 1, 1, 2, 1, 2, 2, 3, 1, 2, 2, 3, 2, 3, 3, 4];

  function hamming(a, b) {
    if (!a || !b || a.length !== b.length) return Infinity;
    let bits = 0;
    for (let i = 0; i < a.length; i++) {
      bits += POPCOUNT[parseInt(a[i], 16) ^ parseInt(b[i], 16)];
    }
    return bits;
  }

  function distanceKm(a, b) {
    const rad = Math.PI / 180;
    const dLat = (b.lat - a.lat) * rad;
    const dLon = (b.lon - a.lon) * rad;
    const h =
      Math.sin(dLat / 2) ** 2 +
      Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
    return 2 * 6371 * Math.asin(Math.sqrt(h));
  }

  const hasGps = (p) => typeof p.lat === "number" && typeof p.lon === "number";

  function dayKey(ms) {
    const d = new Date(ms);
    return d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate();
  }

  // 날짜순, 날짜를 모르는 사진은 뒤로 (이름순)
  function byDate(a, b) {
    if (a.date != null && b.date != null) return a.date - b.date || cmpName(a, b);
    if (a.date != null) return -1;
    if (b.date != null) return 1;
    return cmpName(a, b);
  }
  const cmpName = (a, b) => String(a.name).localeCompare(String(b.name), undefined, { numeric: true });

  function median(values) {
    if (!values.length) return 0;
    const sorted = values.slice().sort((a, b) => a - b);
    const mid = sorted.length >> 1;
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  }

  function isNewScene(prev, next) {
    if (prev.date == null || next.date == null) return false;
    if (dayKey(prev.date) !== dayKey(next.date)) return true;
    if (next.date - prev.date > SCENE_GAP_MS) return true;
    return hasGps(prev) && hasGps(next) && distanceKm(prev, next) > SCENE_DISTANCE_KM;
  }

  function splitScenes(photos) {
    const scenes = [];
    for (const photo of photos) {
      const last = scenes[scenes.length - 1];
      if (!last || isNewScene(last[last.length - 1], photo)) scenes.push([photo]);
      else last.push(photo);
    }
    return scenes;
  }

  const sharpest = (list) => list.reduce((best, p) => (p.sharpness > best.sharpness ? p : best));

  // 장면을 시간순으로 n칸으로 나눠 칸마다 가장 선명한 사진 하나
  function pickSpread(scene, count) {
    const picked = [];
    for (let k = 0; k < count; k++) {
      const from = Math.floor((k * scene.length) / count);
      const to = Math.floor(((k + 1) * scene.length) / count);
      if (to > from) picked.push(sharpest(scene.slice(from, to)));
    }
    return picked;
  }

  // 장면 크기에 비례해서 나누되 장면마다 최소 한 장은 남긴다
  function capByScenes(scenes, limit) {
    const total = scenes.reduce((sum, s) => sum + s.length, 0);
    if (total <= limit) return scenes.flat();
    if (limit <= 0) return [];

    if (scenes.length >= limit) {
      const picked = [];
      for (let k = 0; k < limit; k++) {
        picked.push(sharpest(scenes[Math.floor(((k + 0.5) * scenes.length) / limit)]));
      }
      return picked;
    }

    const quotas = scenes.map((s) => Math.max(1, Math.floor((limit * s.length) / total)));
    let sum = quotas.reduce((a, b) => a + b, 0);
    while (sum > limit) {
      let biggest = 0;
      quotas.forEach((q, i) => {
        if (q > quotas[biggest]) biggest = i;
      });
      quotas[biggest]--;
      sum--;
    }
    while (sum < limit) {
      let best = -1;
      quotas.forEach((q, i) => {
        if (q < scenes[i].length && (best < 0 || scenes[i].length / q > scenes[best].length / quotas[best])) best = i;
      });
      if (best < 0) break;
      quotas[best]++;
      sum++;
    }
    return scenes.flatMap((scene, i) => pickSpread(scene, quotas[i]));
  }

  /**
   * @param photos 분석된 사진들
   * @param options { from, to (ms, 포함), maxCount, forceIn, forceOut (id 배열/Set) }
   * @returns { kept: 사진[] (날짜순), rejected: [{photo, reason}], outOfRange: 개수 }
   */
  function selectPhotos(photos, options = {}) {
    const maxCount = options.maxCount ?? 40;
    const forceIn = new Set(options.forceIn || []);
    const forceOut = new Set(options.forceOut || []);
    const from = options.from ?? null;
    const to = options.to ?? null;

    const rejected = [];
    const reject = (photo, reason) => rejected.push({ photo, reason });
    const pinned = [];
    let outOfRange = 0;

    const inRange = (p) => p.date == null || ((from == null || p.date >= from) && (to == null || p.date <= to));

    const valid = [];
    for (const photo of photos) {
      if (photo.error) reject(photo, REASONS.error);
      else if (forceOut.has(photo.id)) reject(photo, REASONS.manual);
      else if (forceIn.has(photo.id)) pinned.push(photo);
      else if (!inRange(photo)) outOfRange++;
      else valid.push(photo);
    }

    const blurLimit = Math.min(BLUR_ABSOLUTE, BLUR_RELATIVE * median(valid.map((p) => p.sharpness)));
    const usable = [];
    for (const photo of valid) {
      if (photo.screenshot) reject(photo, REASONS.screenshot);
      else if (photo.brightness < DARK_LIMIT) reject(photo, REASONS.dark);
      else if (photo.sharpness < blurLimit) reject(photo, REASONS.blurry);
      else usable.push(photo);
    }
    usable.sort(byDate);

    // 연속 촬영: 묶음의 첫 사진과 비교해서 비슷하면 같은 묶음
    const unique = [];
    let group = [];
    const flush = () => {
      if (!group.length) return;
      const best = sharpest(group);
      unique.push(best);
      for (const p of group) if (p !== best) reject(p, REASONS.duplicate);
      group = [];
    };
    for (const photo of usable) {
      const head = group[0];
      if (head && isDuplicate(head, photo)) group.push(photo);
      else {
        flush();
        group = [photo];
      }
    }
    flush();

    const room = Math.max(0, maxCount - pinned.length);
    const capped = new Set(capByScenes(splitScenes(unique), room));
    for (const photo of unique) if (!capped.has(photo)) reject(photo, REASONS.trimmed);

    const kept = [...capped, ...pinned].sort(byDate);
    return { kept, rejected, outOfRange };
  }

  function isDuplicate(a, b) {
    if (a.date != null && b.date != null) {
      return Math.abs(b.date - a.date) <= DUP_WINDOW_MS && hamming(a.hash, b.hash) <= DUP_BITS;
    }
    return hamming(a.hash, b.hash) <= DUP_BITS_NO_DATE;
  }

  /* 사용자가 순서를 바꿨으면 그 순서를 지키고, 새로 들어온 사진은 날짜 자리에 끼운다. */
  function applyCustomOrder(kept, order) {
    if (!order || !order.length) return kept;
    const position = new Map(order.map((id, i) => [id, i]));
    const result = kept.filter((p) => position.has(p.id)).sort((a, b) => position.get(a.id) - position.get(b.id));
    for (const photo of kept.filter((p) => !position.has(p.id))) {
      const at = photo.date == null ? -1 : result.findIndex((p) => p.date != null && p.date > photo.date);
      if (at < 0) result.push(photo);
      else result.splice(at, 0, photo);
    }
    return result;
  }

  return { REASONS, selectPhotos, applyCustomOrder, splitScenes, hamming, distanceKm, dayKey };
});
