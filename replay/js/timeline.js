/* 고른 사진들을 시간축에 올린다. (순수 로직)
 *
 * 사진 i는 start = i × hold 에 나타나서 다음 사진과 fade초 겹치며 넘어간다.
 * 마지막 사진 뒤에는 엔딩 카드가 붙는다.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Replay = Object.assign(root.Replay || {}, api);
})(typeof self !== "undefined" ? self : this, function () {
  const MOODS = {
    emotional: {
      label: "감성",
      hold: 2.6,
      fade: 0.9,
      zoom: [1.0, 1.1],
      pan: 0.6,
      tint: "rgba(255, 170, 110, 0.10)",
      font: "serif",
    },
    upbeat: {
      label: "신나는",
      hold: 1.1,
      fade: 0.12,
      zoom: [1.14, 1.0],
      pan: 0.2,
      tint: null,
      font: "sans",
    },
    calm: {
      label: "잔잔한",
      hold: 3.6,
      fade: 1.4,
      zoom: [1.06, 1.06],
      pan: 1.0,
      tint: "rgba(120, 150, 200, 0.08)",
      font: "sans",
    },
  };

  const TITLE_SECONDS = 2.8;
  const END_SECONDS = 2.4;
  const MIN_HOLD = 0.8;
  const MAX_HOLD = 6;

  const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
  const reliableDate = (p) => p.date != null && (p.dateSource === "exif" || p.dateSource === "filename");

  function dayLabel(ms) {
    const d = new Date(ms);
    return `${d.getMonth() + 1}월 ${d.getDate()}일 ${WEEKDAYS[d.getDay()]}요일`;
  }

  /* 사진 날짜 범위로 기본 제목을 만든다: "2026년 9월", "2026년 3월 – 9월", "2024 – 2026" */
  function defaultTitle(photos) {
    const dates = photos.filter(reliableDate).map((p) => p.date);
    if (!dates.length) return { title: "나의 리플레이", sub: "" };
    const first = new Date(Math.min(...dates));
    const last = new Date(Math.max(...dates));
    const y1 = first.getFullYear();
    const y2 = last.getFullYear();
    const m1 = first.getMonth() + 1;
    const m2 = last.getMonth() + 1;
    const short = (d) => `${d.getMonth() + 1}.${d.getDate()}`;
    let title;
    if (y1 !== y2) title = `${y1} – ${y2}`;
    else if (m1 !== m2) title = `${y1}년 ${m1}월 – ${m2}월`;
    else title = `${y1}년 ${m1}월`;
    const sub = y1 !== y2 ? `${y1}.${short(first)} – ${y2}.${short(last)}` : `${short(first)} – ${short(last)}`;
    return { title, sub: dates.length > 1 && +first !== +last ? sub : short(first) };
  }

  /**
   * @param photos 영상 순서대로 정렬된 사진들
   * @param moodKey MOODS의 키
   * @param options { title, sub, musicDuration, fitMusic, watermark }
   */
  function buildTimeline(photos, moodKey, options = {}) {
    const mood = MOODS[moodKey] || MOODS.emotional;
    const n = photos.length;
    if (!n) return { duration: 0, segments: [], mood, title: null, end: null };

    let hold = mood.hold;
    if (options.fitMusic && options.musicDuration > 0) {
      hold = (options.musicDuration - END_SECONDS) / n;
      hold = Math.min(MAX_HOLD, Math.max(MIN_HOLD, hold));
    }
    const fade = Math.min(mood.fade, hold * 0.6);

    const segments = photos.map((photo, i) => {
      const prev = photos[i - 1];
      const sceneStart =
        reliableDate(photo) && (!prev || !reliableDate(prev) || new Date(prev.date).toDateString() !== new Date(photo.date).toDateString());
      // 방향을 사진마다 번갈아 바꿔서 단조롭지 않게
      const zoomIn = mood.zoom[0] === mood.zoom[1] ? true : i % 2 === 0;
      const sx = (i % 2 ? -1 : 1) * mood.pan;
      const sy = (i % 3 === 0 ? 1 : -1) * mood.pan * 0.5;
      return {
        photoId: photo.id,
        start: i * hold,
        end: i * hold + hold + fade,
        fadeIn: i === 0 ? 0 : fade,
        zoomFrom: zoomIn ? mood.zoom[0] : mood.zoom[1],
        zoomTo: zoomIn ? mood.zoom[1] : mood.zoom[0],
        panFrom: [sx, sy],
        panTo: [-sx, -sy],
        caption: sceneStart ? dayLabel(photo.date) : null,
      };
    });

    const endStart = n * hold;
    const duration = endStart + END_SECONDS;
    const fallback = defaultTitle(photos);
    const title = {
      text: options.title || fallback.title,
      sub: options.sub ?? fallback.sub,
      start: 0,
      end: Math.min(TITLE_SECONDS, endStart),
    };
    const end = {
      text: title.text,
      sub: options.watermark === false ? "" : "made with 리플레이",
      start: endStart,
      end: duration,
      fadeIn: Math.max(0.4, fade),
    };
    return { duration, hold, fade, segments, mood, title, end };
  }

  /* t초에 보이는 구간들 (그리는 순서대로) */
  function activeSegments(timeline, t) {
    return timeline.segments.filter((s) => t >= s.start && t < s.end);
  }

  return { MOODS, buildTimeline, activeSegments, defaultTitle, dayLabel };
});
