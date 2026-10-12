/* 타임라인을 캔버스에 그리고, 재생하고, MediaRecorder로 영상 파일을 만든다.
 *
 * 시계는 AudioContext 하나를 쓴다. 음악이 있으면 소리와 화면이 같은 시계로 맞물린다.
 * 녹화는 실시간이라서 1분짜리 영상은 1분이 걸린다.
 */
(function (root) {
  const Replay = (root.Replay = root.Replay || {});
  const W = 1080;
  const H = 1920;
  const FPS = 30;
  const MUSIC_FADE = 1.5;

  const FONTS = {
    sans: "'Pretendard', 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', sans-serif",
    serif: "'Nanum Myeongjo', 'AppleMyungjo', 'Noto Serif KR', 'Batang', serif",
  };

  const MIME_CANDIDATES = [
    "video/mp4;codecs=avc1.640028,mp4a.40.2",
    "video/mp4;codecs=avc1,mp4a.40.2",
    "video/mp4;codecs=avc1",
    "video/mp4",
    "video/webm;codecs=vp9,opus",
    "video/webm;codecs=vp8,opus",
    "video/webm",
  ];

  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  const lerp = (a, b, p) => a + (b - a) * p;

  function pickMime() {
    if (typeof MediaRecorder === "undefined") return null;
    return MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m)) || "";
  }

  class Player {
    constructor(canvas) {
      this.canvas = canvas;
      canvas.width = W;
      canvas.height = H;
      this.ctx = canvas.getContext("2d");
      this.timeline = null;
      this.photos = new Map(); // id → 분석된 사진
      this.full = new Map(); // id → Promise<{bitmap, bg}>
      this.thumbs = new Map(); // id → HTMLImageElement
      this.music = null; // AudioBuffer
      this.time = 0;
      this.playing = false;
      this.onTime = null;
      this.onEnd = null;
    }

    get audio() {
      if (!this.audioContext) {
        const Ctx = root.AudioContext || root.webkitAudioContext;
        this.audioContext = new Ctx();
      }
      return this.audioContext;
    }

    get duration() {
      return this.timeline ? this.timeline.duration : 0;
    }

    setProject(timeline, photos, music) {
      this.timeline = timeline;
      this.music = music || null;
      this.photos = new Map(photos.map((p) => [p.id, p]));
      for (const id of [...this.full.keys()]) if (!this.photos.has(id)) this.evict(id);
      for (const p of photos) {
        if (!this.thumbs.has(p.id) && p.thumbUrl) {
          const img = new Image();
          img.src = p.thumbUrl;
          this.thumbs.set(p.id, img);
        }
      }
      this.time = Math.min(this.time, this.duration);
    }

    // ------------------------------------------------------------ 원본 디코딩

    load(id) {
      if (this.full.has(id)) return this.full.get(id);
      const photo = this.photos.get(id);
      // 세로 사진은 화면을 꽉 채우고(높이 기준), 가로 사진은 폭에 맞춰 띄운다
      const cover = photo.aspect <= 0.8;
      const options = cover
        ? { resizeHeight: Math.round(H * 1.15), resizeQuality: "high" }
        : { resizeWidth: Math.round(W * 1.15), resizeQuality: "high" };
      const promise = Replay.decode(photo.file, options)
        .then((bitmap) => {
          const bg = document.createElement("canvas");
          bg.width = 18;
          bg.height = 32;
          bg.getContext("2d").drawImage(bitmap, 0, 0, bg.width, bg.height);
          const entry = { bitmap, bg, cover };
          promise.entry = entry;
          return entry;
        })
        .catch(() => {
          promise.failed = true; // 썸네일로 대신 그린다
          return null;
        });
      this.full.set(id, promise);
      return promise;
    }

    evict(id) {
      const promise = this.full.get(id);
      this.full.delete(id);
      if (promise) promise.then((e) => e && e.bitmap.close && e.bitmap.close());
    }

    // t 근처 사진들만 메모리에 둔다
    prefetch(t) {
      const segments = this.timeline ? this.timeline.segments : [];
      let index = segments.findIndex((s) => t < s.end);
      if (index < 0) index = segments.length - 1;
      const keep = new Set();
      for (let i = index - 1; i <= index + 2; i++) if (segments[i]) keep.add(segments[i].photoId);
      for (const id of keep) this.load(id);
      for (const id of [...this.full.keys()]) if (!keep.has(id)) this.evict(id);
      return Promise.all([...keep].map((id) => this.full.get(id)));
    }

    // t ~ t+ahead 사이에 보일 사진 중 아직 디코딩 중인 것
    pending(t, ahead) {
      const waiting = [];
      for (const seg of this.timeline.segments) {
        if (seg.start >= t + ahead || seg.end <= t) continue;
        const promise = this.load(seg.photoId);
        if (!promise.entry && !promise.failed) waiting.push(promise);
      }
      return waiting;
    }

    // ------------------------------------------------------------ 그리기

    draw(t) {
      const ctx = this.ctx;
      const tl = this.timeline;
      ctx.globalAlpha = 1;
      ctx.fillStyle = "#000";
      ctx.fillRect(0, 0, W, H);
      if (!tl || !tl.segments.length) return;

      const active = Replay.activeSegments(tl, t);
      for (const seg of active) {
        ctx.globalAlpha = seg.fadeIn ? clamp01((t - seg.start) / seg.fadeIn) : 1;
        this.drawPhoto(seg, clamp01((t - seg.start) / (seg.end - seg.start)));
      }
      ctx.globalAlpha = 1;
      if (tl.mood.tint) {
        ctx.fillStyle = tl.mood.tint;
        ctx.fillRect(0, 0, W, H);
      }
      for (const seg of active) if (seg.caption) this.drawCaption(seg, t);
      this.drawTitle(t);
      this.drawEnd(t);
    }

    drawPhoto(seg, p) {
      const ctx = this.ctx;
      const promise = this.full.get(seg.photoId);
      const entry = promise && promise.entry;
      const source = entry ? entry.bitmap : this.thumbs.get(seg.photoId);
      if (!source || !(source.width || source.naturalWidth)) return;
      const sw = source.naturalWidth || source.width;
      const sh = source.naturalHeight || source.height;
      const zoom = lerp(seg.zoomFrom, seg.zoomTo, p);
      const panX = lerp(seg.panFrom[0], seg.panTo[0], p);
      const panY = lerp(seg.panFrom[1], seg.panTo[1], p);
      const photo = this.photos.get(seg.photoId);
      const cover = photo ? photo.aspect <= 0.8 : true;

      if (cover) {
        const scale = Math.max(W / sw, H / sh) * zoom;
        const dw = sw * scale;
        const dh = sh * scale;
        const x = (W - dw) / 2 + panX * ((dw - W) / 2);
        const y = (H - dh) / 2 + panY * ((dh - H) / 2);
        ctx.drawImage(source, x, y, dw, dh);
        return;
      }

      // 가로 사진: 흐린 배경 위에 폭 맞춤
      const bg = entry ? entry.bg : source;
      const alpha = ctx.globalAlpha;
      ctx.imageSmoothingQuality = "low";
      const bgScale = Math.max(W / (bg.width || sw), H / (bg.height || sh)) * 1.1;
      const bw = (bg.width || sw) * bgScale;
      const bh = (bg.height || sh) * bgScale;
      ctx.drawImage(bg, (W - bw) / 2, (H - bh) / 2, bw, bh);
      ctx.fillStyle = "rgba(0,0,0,0.35)";
      ctx.fillRect(0, 0, W, H);
      ctx.imageSmoothingQuality = "high";
      ctx.globalAlpha = alpha;
      const fg = 1 + (zoom - 1) * 0.5;
      const dw = W * fg;
      const dh = (sh / sw) * dw;
      ctx.drawImage(source, (W - dw) / 2 + panX * ((dw - W) / 2), (H - dh) / 2, dw, dh);
    }

    font(weight, size) {
      const family = FONTS[this.timeline.mood.font] || FONTS.sans;
      return `${weight} ${size}px ${family}`;
    }

    drawCaption(seg, t) {
      const title = this.timeline.title;
      const begin = Math.max(seg.start + 0.25, title ? title.end - 0.2 : 0);
      const show = seg.start + Math.min(2.85, seg.end - seg.start) - begin;
      const local = t - begin;
      if (show < 0.8 || local < 0 || local > show) return;
      const alpha = Math.min(clamp01(local / 0.35), clamp01((show - local) / 0.35));
      const ctx = this.ctx;
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.font = this.font(600, 50);
      ctx.textBaseline = "middle";
      const pad = 30;
      const width = ctx.measureText(seg.caption).width + pad * 2;
      const x = 72;
      const y = H - 300;
      ctx.fillStyle = "rgba(0,0,0,0.38)";
      roundRect(ctx, x, y - 44, width, 88, 44);
      ctx.fill();
      ctx.fillStyle = "#fff";
      ctx.fillText(seg.caption, x + pad, y + 2);
      ctx.restore();
    }

    drawTitle(t) {
      const title = this.timeline.title;
      if (!title || t >= title.end) return;
      const alpha = clamp01((title.end - t) / 0.7) * clamp01(t / 0.3 + 0.4);
      const ctx = this.ctx;
      ctx.save();
      ctx.globalAlpha = alpha;
      const gradient = ctx.createLinearGradient(0, H * 0.35, 0, H);
      gradient.addColorStop(0, "rgba(0,0,0,0)");
      gradient.addColorStop(1, "rgba(0,0,0,0.75)");
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = "#fff";
      ctx.textAlign = "center";
      ctx.textBaseline = "alphabetic";
      ctx.shadowColor = "rgba(0,0,0,0.4)";
      ctx.shadowBlur = 24;
      fitText(ctx, title.text, W / 2, H - 420, W - 160, (s) => this.font(800, s), 104);
      if (title.sub) {
        ctx.font = this.font(500, 46);
        ctx.globalAlpha = alpha * 0.85;
        ctx.fillText(title.sub, W / 2, H - 330);
      }
      ctx.restore();
    }

    drawEnd(t) {
      const end = this.timeline.end;
      if (!end || t < end.start) return;
      const alpha = clamp01((t - end.start) / end.fadeIn);
      const ctx = this.ctx;
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.fillStyle = "#0b0b0f";
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = "#fff";
      ctx.textAlign = "center";
      fitText(ctx, end.text, W / 2, H / 2, W - 160, (s) => this.font(800, s), 88);
      if (end.sub) {
        ctx.font = this.font(500, 36);
        ctx.globalAlpha = alpha * 0.6;
        ctx.fillText(end.sub, W / 2, H / 2 + 90);
      }
      ctx.restore();
    }

    // ------------------------------------------------------------ 재생

    async seek(t) {
      this.time = Math.max(0, Math.min(t, this.duration));
      await this.prefetch(this.time);
      this.draw(this.time);
      this.onTime && this.onTime(this.time);
    }

    /* from초부터 끝까지 재생. 끝나거나 pause()되면 resolve된다.
     * recording이 있으면 소리를 거기로도 흘리고, 다음 사진이 준비 안 됐을 땐
     * 녹화와 시계를 같이 멈췄다가 이어 간다 (느린 기기에서 화면이 멈춘 채 찍히지 않게). */
    async play(from = this.time, recording = null) {
      if (this.playing || !this.duration) return;
      const ac = this.audio;
      await ac.resume();
      if (from >= this.duration - 0.05) from = 0;
      await this.prefetch(from);
      this.playing = true;

      const startAt = ac.currentTime - from;
      let source = null;
      if (this.music) {
        source = ac.createBufferSource();
        source.buffer = this.music;
        source.loop = true;
        const gain = ac.createGain();
        const fadeStart = Math.max(ac.currentTime, startAt + this.duration - MUSIC_FADE);
        gain.gain.setValueAtTime(1, fadeStart);
        gain.gain.linearRampToValueAtTime(0, Math.max(fadeStart + 0.05, startAt + this.duration));
        source.connect(gain);
        gain.connect(ac.destination);
        if (recording && recording.output) gain.connect(recording.output);
        source.start(ac.currentTime, from % this.music.duration);
      }

      const nextFrame = () => new Promise((resolve) => requestAnimationFrame(resolve));
      let finished = false;
      while (this.playing) {
        let t = ac.currentTime - startAt;
        if (recording) {
          const waiting = this.pending(t, 0.5);
          if (waiting.length) {
            recording.recorder.pause();
            await ac.suspend();
            await Promise.all(waiting);
            await ac.resume();
            recording.recorder.resume();
            t = ac.currentTime - startAt;
          }
        }
        if (t >= this.duration) {
          this.time = this.duration;
          this.draw(this.duration - 0.001);
          this.onTime && this.onTime(this.time);
          finished = true;
          break;
        }
        this.time = t;
        this.prefetch(t);
        this.draw(t);
        this.onTime && this.onTime(t);
        await nextFrame();
      }

      if (source) source.stop();
      this.playing = false;
      if (finished && this.onEnd) this.onEnd();
    }

    pause() {
      this.playing = false;
    }

    /* 처음부터 끝까지 재생하면서 녹화한다. onProgress(t, duration) */
    async record(onProgress) {
      const mime = pickMime();
      if (mime === null || !this.canvas.captureStream) {
        throw new Error("이 브라우저는 영상 녹화를 지원하지 않아요. 크롬이나 사파리 최신 버전을 써 주세요.");
      }
      const ac = this.audio;
      await ac.resume();
      const stream = this.canvas.captureStream(FPS);
      let output = null;
      if (this.music) {
        output = ac.createMediaStreamDestination();
        output.stream.getAudioTracks().forEach((track) => stream.addTrack(track));
      }
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime, videoBitsPerSecond: 8_000_000 } : {});
      const chunks = [];
      recorder.ondataavailable = (e) => e.data && e.data.size && chunks.push(e.data);
      const stopped = new Promise((resolve) => (recorder.onstop = resolve));

      await this.seek(0);
      const previous = this.onTime;
      this.onTime = (t) => {
        previous && previous(t);
        onProgress && onProgress(t, this.duration);
      };
      recorder.start(1000);
      try {
        await this.play(0, { recorder, output });
        await new Promise((r) => setTimeout(r, 250)); // 마지막 프레임이 담기게
      } finally {
        this.onTime = previous;
        recorder.stop();
        await stopped;
        stream.getTracks().forEach((track) => track.stop());
      }
      const type = (recorder.mimeType || mime || "video/webm").split(";")[0];
      return { blob: new Blob(chunks, { type }), type, extension: type.includes("mp4") ? "mp4" : "webm" };
    }
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  // 긴 제목은 폭에 맞을 때까지 글자를 줄인다
  function fitText(ctx, text, x, y, maxWidth, fontFor, size) {
    let s = size;
    ctx.font = fontFor(s);
    while (s > 40 && ctx.measureText(text).width > maxWidth) {
      s -= 4;
      ctx.font = fontFor(s);
    }
    ctx.fillText(text, x, y);
  }

  Object.assign(Replay, { Player, pickMime, VIDEO_SIZE: { width: W, height: H } });
})(self);
