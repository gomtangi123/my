/* JPEG의 EXIF에서 촬영 시각·위치·카메라 정보만 읽는다.
 *
 * 라이브러리를 쓰지 않으려고 필요한 태그만 직접 읽는다.
 * 브라우저에서는 window.Replay에, node에서는 module.exports에 붙는다.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Replay = Object.assign(root.Replay || {}, api);
})(typeof self !== "undefined" ? self : this, function () {
  const TYPE_SIZE = { 1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8 };

  function readExif(buffer) {
    const view = new DataView(buffer);
    if (view.byteLength < 4 || view.getUint16(0) !== 0xffd8) return {};
    let offset = 2;
    while (offset + 4 <= view.byteLength) {
      const marker = view.getUint16(offset);
      if ((marker & 0xff00) !== 0xff00 || marker === 0xffda) break; // 본문(SOS) 시작
      const size = view.getUint16(offset + 2);
      if (
        marker === 0xffe1 &&
        offset + 10 <= view.byteLength &&
        view.getUint32(offset + 4) === 0x45786966 // "Exif"
      ) {
        try {
          return parseTiff(view, offset + 10);
        } catch (e) {
          return {}; // 깨진 EXIF는 없는 것으로 친다
        }
      }
      offset += 2 + size;
    }
    return {};
  }

  function parseTiff(view, start) {
    const little = view.getUint16(start) === 0x4949;
    const u16 = (o) => view.getUint16(o, little);
    const u32 = (o) => view.getUint32(o, little);

    function readIfd(relative) {
      const tags = {};
      const base = start + relative;
      if (!relative || base + 2 > view.byteLength) return tags;
      const count = u16(base);
      for (let i = 0; i < count; i++) {
        const entry = base + 2 + i * 12;
        if (entry + 12 > view.byteLength) break;
        tags[u16(entry)] = { type: u16(entry + 2), count: u32(entry + 4), at: entry + 8 };
      }
      return tags;
    }

    // 4바이트 이하 값은 엔트리 안에, 넘으면 오프셋이 가리키는 곳에 있다
    const dataAt = (tag) =>
      (TYPE_SIZE[tag.type] || 1) * tag.count <= 4 ? tag.at : start + u32(tag.at);

    function ascii(tag) {
      if (!tag) return null;
      const at = dataAt(tag);
      let text = "";
      for (let i = 0; i < tag.count && at + i < view.byteLength; i++) {
        const code = view.getUint8(at + i);
        if (!code) break;
        text += String.fromCharCode(code);
      }
      return text.trim() || null;
    }

    function integer(tag) {
      if (!tag) return 0;
      return tag.type === 3 ? u16(dataAt(tag)) : u32(dataAt(tag));
    }

    function rationals(tag) {
      if (!tag || tag.type !== 5) return null;
      const at = dataAt(tag);
      const values = [];
      for (let i = 0; i < tag.count; i++) {
        const o = at + i * 8;
        if (o + 8 > view.byteLength) return null;
        const denominator = u32(o + 4);
        values.push(denominator ? u32(o) / denominator : 0);
      }
      return values;
    }

    function degrees(valueTag, refTag) {
      const parts = rationals(valueTag);
      if (!parts || parts.length < 3) return null;
      const value = parts[0] + parts[1] / 60 + parts[2] / 3600;
      const ref = ascii(refTag);
      return ref === "S" || ref === "W" ? -value : value;
    }

    const ifd0 = readIfd(u32(start + 4));
    const exif = readIfd(integer(ifd0[0x8769]));
    const gps = readIfd(integer(ifd0[0x8825]));

    const result = {
      date: parseExifDate(ascii(exif[0x9003]) || ascii(exif[0x9004]) || ascii(ifd0[0x0132])),
      make: ascii(ifd0[0x010f]),
      model: ascii(ifd0[0x0110]),
    };
    const lat = degrees(gps[2], gps[1]);
    const lon = degrees(gps[4], gps[3]);
    // 0,0은 위치를 못 잡은 기기가 넣는 값이다
    if (lat !== null && lon !== null && (lat !== 0 || lon !== 0)) {
      result.lat = lat;
      result.lon = lon;
    }
    return result;
  }

  // "2026:09:14 18:30:05" → 기기 현지 시각 기준 Date
  function parseExifDate(text) {
    const m = text && /^(\d{4})[:-](\d{2})[:-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})/.exec(text);
    if (!m) return null;
    const date = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
    return isNaN(date) || date.getFullYear() < 1990 ? null : date;
  }

  // EXIF가 지워진 사진(카톡으로 받은 사진 등)은 파일 이름의 날짜라도 쓴다.
  // 예: 20260914_183005.jpg, IMG_20260914_183005.jpg, KakaoTalk_20260914_183005123.jpg
  function dateFromFilename(name) {
    const m = /(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})[-_ ]?(\d{2})[-_.]?(\d{2})[-_.]?(\d{2})/.exec(name || "");
    if (!m) return null;
    const [y, mo, d, h, mi, s] = m.slice(1).map(Number);
    if (mo < 1 || mo > 12 || d < 1 || d > 31 || h > 23 || mi > 59 || s > 59) return null;
    return new Date(y, mo - 1, d, h, mi, s);
  }

  return { readExif, parseExifDate, dateFromFilename };
});
