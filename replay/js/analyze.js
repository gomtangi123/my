/* 사진 파일을 브라우저 안에서 분석한다: 날짜·위치, 선명도, 밝기, 지각 해시, 스크린샷 여부.
 *
 * 원본은 어디에도 올리지 않는다. 256px 축소본으로만 계산하고,
 * 화면에 보여 줄 작은 썸네일(JPEG blob URL)만 남긴다.
 */
(function (root) {
  const Replay = (root.Replay = root.Replay || {});
  const SIZE = 256;
  const THUMB = 200;
  const WORKERS = 4;
  const EXIF_BYTES = 128 * 1024; // EXIF는 파일 앞부분(APP1)에 있다

  const IMAGE_EXT = /\.(jpe?g|png|webp|gif|heic|heif|avif|bmp)$/i;
  const SCREENSHOT_NAME = /screenshot|screen[_ -]?shot|스크린샷|캡처|capture/i;

  function isImageFile(file) {
    return (file.type && file.type.startsWith("image/")) || IMAGE_EXT.test(file.name);
  }

  async function decode(file, options) {
    try {
      return await createImageBitmap(file, options);
    } catch (e) {
      if (options) return createImageBitmap(file); // 크기 옵션을 모르는 브라우저
      throw e;
    }
  }

  function canvasOf(w, h) {
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    return canvas;
  }

  function grayPixels(source, w, h) {
    const ctx = canvasOf(w, h).getContext("2d", { willReadFrequently: true });
    ctx.drawImage(source, 0, 0, w, h);
    const rgba = ctx.getImageData(0, 0, w, h).data;
    const gray = new Float32Array(w * h);
    for (let i = 0, j = 0; i < gray.length; i++, j += 4) {
      gray[i] = 0.299 * rgba[j] + 0.587 * rgba[j + 1] + 0.114 * rgba[j + 2];
    }
    return gray;
  }

  // 라플라시안 분산: 흔들리거나 초점이 나간 사진일수록 작다
  function sharpnessOf(gray, w, h) {
    let sum = 0;
    let sumSq = 0;
    let count = 0;
    for (let y = 1; y < h - 1; y++) {
      for (let x = 1; x < w - 1; x++) {
        const i = y * w + x;
        const lap = gray[i - w] + gray[i + w] + gray[i - 1] + gray[i + 1] - 4 * gray[i];
        sum += lap;
        sumSq += lap * lap;
        count++;
      }
    }
    if (!count) return 0;
    const mean = sum / count;
    return sumSq / count - mean * mean;
  }

  // dHash: 9×8 칸 평균 밝기를 옆 칸과 비교 → 64비트. 비슷한 사진은 비트가 거의 같다.
  // drawImage로 바로 9×8까지 줄이면 픽셀을 건너뛰어 잡티에 흔들리므로 칸 평균을 직접 낸다.
  function dHash(gray, w, h) {
    const cells = new Float32Array(9 * 8);
    const counts = new Uint32Array(9 * 8);
    for (let y = 0; y < h; y++) {
      const row = Math.min(7, Math.floor((y * 8) / h));
      for (let x = 0; x < w; x++) {
        const cell = row * 9 + Math.min(8, Math.floor((x * 9) / w));
        cells[cell] += gray[y * w + x];
        counts[cell]++;
      }
    }
    for (let i = 0; i < cells.length; i++) cells[i] /= counts[i] || 1;
    let hex = "";
    for (let row = 0; row < 8; row++) {
      for (let nibble = 0; nibble < 2; nibble++) {
        let value = 0;
        for (let bit = 0; bit < 4; bit++) {
          const x = nibble * 4 + bit;
          value = (value << 1) | (cells[row * 9 + x] < cells[row * 9 + x + 1] ? 1 : 0);
        }
        hex += value.toString(16);
      }
    }
    return hex;
  }

  function toThumbUrl(source, w, h) {
    const scale = Math.min(1, THUMB / Math.max(w, h));
    const canvas = canvasOf(Math.max(1, Math.round(w * scale)), Math.max(1, Math.round(h * scale)));
    canvas.getContext("2d").drawImage(source, 0, 0, canvas.width, canvas.height);
    return new Promise((resolve) =>
      canvas.toBlob((blob) => resolve(blob ? URL.createObjectURL(blob) : ""), "image/jpeg", 0.8)
    );
  }

  async function analyzePhoto(file, id) {
    const photo = {
      id,
      file,
      name: file.webkitRelativePath || file.name,
      date: null,
      dateSource: null,
      sharpness: 0,
      brightness: 0,
      hash: null,
      aspect: 1,
      screenshot: false,
      error: null,
      thumbUrl: "",
    };

    let exif = {};
    try {
      exif = Replay.readExif(await file.slice(0, EXIF_BYTES).arrayBuffer());
    } catch (e) {
      /* EXIF가 없으면 다른 단서로 */
    }
    const fromName = Replay.dateFromFilename(file.name);
    if (exif.date) Object.assign(photo, { date: +exif.date, dateSource: "exif" });
    else if (fromName) Object.assign(photo, { date: +fromName, dateSource: "filename" });
    else if (file.lastModified) Object.assign(photo, { date: file.lastModified, dateSource: "file" });
    if (exif.lat != null) Object.assign(photo, { lat: exif.lat, lon: exif.lon });

    let bitmap;
    try {
      bitmap = await decode(file, { resizeWidth: SIZE, resizeQuality: "medium" });
    } catch (e) {
      photo.error = /heic|heif/i.test(file.name) || /heic|heif/.test(file.type)
        ? "이 브라우저는 HEIC 사진을 못 열어요"
        : "열 수 없는 파일";
      return photo;
    }

    try {
      const scale = Math.min(1, SIZE / bitmap.width);
      const w = Math.max(3, Math.round(bitmap.width * scale));
      const h = Math.max(3, Math.round(bitmap.height * scale));
      const gray = grayPixels(bitmap, w, h);
      photo.aspect = bitmap.width / bitmap.height;
      photo.brightness = gray.reduce((a, b) => a + b, 0) / gray.length;
      photo.sharpness = sharpnessOf(gray, w, h);
      photo.hash = dHash(gray, w, h);
      photo.thumbUrl = await toThumbUrl(bitmap, bitmap.width, bitmap.height);

      // 카메라로 찍은 사진엔 기종(Make)이 남는다. 없고 화면 비율이면 스크린샷으로 본다.
      const ratio = Math.max(photo.aspect, 1 / photo.aspect);
      photo.screenshot =
        SCREENSHOT_NAME.test(file.name) ||
        (!exif.make && /png/i.test(file.type || file.name)) ||
        (!exif.make && !exif.date && ratio >= 1.95);
    } finally {
      bitmap.close && bitmap.close();
    }
    return photo;
  }

  /* 여러 장을 동시에 몇 개씩 분석한다. onProgress(끝난 수, 전체 수) */
  async function analyzeAll(files, onProgress, firstId = 0) {
    const results = new Array(files.length);
    let next = 0;
    let done = 0;
    async function worker() {
      while (next < files.length) {
        const index = next++;
        try {
          results[index] = await analyzePhoto(files[index], firstId + index);
        } catch (e) {
          results[index] = { id: firstId + index, file: files[index], name: files[index].name, error: "열 수 없는 파일" };
        }
        done++;
        onProgress && onProgress(done, files.length);
      }
    }
    await Promise.all(Array.from({ length: Math.min(WORKERS, files.length) }, worker));
    return results;
  }

  Object.assign(Replay, { analyzeAll, analyzePhoto, isImageFile, decode });
})(self);
