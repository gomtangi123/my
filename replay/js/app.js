/* 화면 연결: 사진 고르기 → 분석 → 편집·미리보기 → 영상 만들기 */
(function () {
  const R = window.Replay;
  const $ = (id) => document.getElementById(id);
  const DAY = 24 * 60 * 60 * 1000;

  const state = {
    photos: [],
    kept: [],
    rejected: [],
    outOfRange: 0,
    order: null, // 사용자가 순서를 바꾼 경우 id 배열
    forceIn: new Set(),
    forceOut: new Set(),
    mood: "emotional",
    period: "all",
    from: null,
    to: null,
    maxCount: 30,
    music: null,
    musicName: "",
    fitMusic: true,
    timeline: null,
    resultUrl: "",
  };

  const player = new R.Player($("stage"));

  // ------------------------------------------------------------ 단계 전환

  function show(step) {
    for (const id of ["step-pick", "step-analyze", "step-edit"]) $(id).hidden = id !== step;
    $("restart").hidden = step === "step-pick";
  }

  // ------------------------------------------------------------ 1. 사진 고르기

  async function takeFiles(fileList) {
    const files = [...fileList].filter(R.isImageFile);
    if (!files.length) {
      alert("사진 파일이 없어요.");
      return;
    }
    show("step-analyze");
    $("analyze-title").textContent = `사진 ${files.length.toLocaleString()}장을 살펴보는 중…`;
    const started = performance.now();
    state.photos = await R.analyzeAll(files, (done, total) => {
      $("analyze-bar").style.width = `${(done / total) * 100}%`;
      $("analyze-count").textContent = `${done.toLocaleString()} / ${total.toLocaleString()}`;
    });
    console.info(`분석 ${Math.round(performance.now() - started)}ms`);
    resetEdits();
    setupDateInputs();
    show("step-edit");
    refresh();
    await player.seek(Math.min(1.2, player.duration));
  }

  $("file-input").addEventListener("change", (e) => takeFiles(e.target.files));
  $("folder-input").addEventListener("change", (e) => takeFiles(e.target.files));
  const drop = $("drop-zone");
  for (const target of [document.body]) {
    target.addEventListener("dragover", (e) => {
      e.preventDefault();
      drop.classList.add("over");
    });
    target.addEventListener("dragleave", () => drop.classList.remove("over"));
    target.addEventListener("drop", (e) => {
      e.preventDefault();
      drop.classList.remove("over");
      if (!$("step-pick").hidden && e.dataTransfer.files.length) takeFiles(e.dataTransfer.files);
    });
  }

  $("restart").addEventListener("click", () => {
    player.pause();
    for (const p of state.photos) if (p.thumbUrl) URL.revokeObjectURL(p.thumbUrl);
    state.photos = [];
    $("file-input").value = "";
    $("folder-input").value = "";
    clearResult();
    show("step-pick");
  });

  function resetEdits() {
    state.order = null;
    state.forceIn.clear();
    state.forceOut.clear();
    state.period = "all";
    markChip($("period"), "all");
    $("custom-range").hidden = true;
    clearResult();
  }

  // ------------------------------------------------------------ 3. 편집

  function reliableDates() {
    return state.photos.filter((p) => p.date != null && p.dateSource !== "file").map((p) => p.date);
  }

  function toInputDate(ms) {
    const d = new Date(ms);
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  function setupDateInputs() {
    const dates = reliableDates();
    const all = dates.length ? dates : state.photos.filter((p) => p.date != null).map((p) => p.date);
    if (!all.length) return;
    $("from").value = toInputDate(Math.min(...all));
    $("to").value = toInputDate(Math.max(...all));
  }

  function periodRange() {
    if (state.period === "month") {
      const dates = reliableDates();
      if (!dates.length) return [null, null];
      const last = Math.max(...dates);
      const end = new Date(last);
      end.setHours(23, 59, 59, 999);
      return [+end - 30 * DAY, +end];
    }
    if (state.period === "custom") {
      const from = $("from").value ? +new Date(`${$("from").value}T00:00:00`) : null;
      const to = $("to").value ? +new Date(`${$("to").value}T23:59:59.999`) : null;
      return [from, to];
    }
    return [null, null];
  }

  function refresh() {
    const [from, to] = periodRange();
    const selection = R.selectPhotos(state.photos, {
      from,
      to,
      maxCount: state.maxCount,
      forceIn: state.forceIn,
      forceOut: state.forceOut,
    });
    state.kept = R.applyCustomOrder(selection.kept, state.order);
    state.rejected = selection.rejected;
    state.outOfRange = selection.outOfRange;

    state.timeline = R.buildTimeline(state.kept, state.mood, {
      title: $("title").value.trim(),
      sub: $("sub").value.trim() || undefined,
      musicDuration: state.music ? state.music.duration : 0,
      fitMusic: state.fitMusic,
    });
    player.setProject(state.timeline, state.kept, state.music);

    const fallback = R.defaultTitle(state.kept);
    $("title").placeholder = `${fallback.title} (자동)`;
    $("sub").placeholder = fallback.sub ? `${fallback.sub} (자동)` : "부제";

    const total = state.photos.length;
    $("summary").textContent = state.kept.length
      ? `사진 ${total.toLocaleString()}장 중 ${state.kept.length}장으로 ${formatTime(state.timeline.duration)} 영상을 만들어요`
      : "넣을 사진이 없어요. 기간을 넓히거나 뺀 사진을 다시 넣어 보세요.";
    $("export").disabled = !state.kept.length;

    const unknown = state.photos.filter((p) => p.dateSource === "file").length;
    $("date-warning").hidden = unknown < Math.max(3, total * 0.3);
    $("date-warning").textContent =
      `${unknown}장은 찍은 날짜 정보가 없어요 (메신저로 받은 사진 등). 순서가 실제와 다를 수 있어요.`;

    renderKept();
    renderRejected();
    updateClock(player.time);
  }

  let redrawTimer = 0;
  function refreshAndRedraw() {
    clearResult();
    refresh();
    clearTimeout(redrawTimer);
    redrawTimer = setTimeout(() => !player.playing && player.seek(player.time), 30);
  }

  function markChip(container, value) {
    for (const chip of container.querySelectorAll(".chip")) chip.classList.toggle("on", chip.dataset.value === value);
  }

  // 분위기 칩은 MOODS에서 만든다
  for (const [key, mood] of Object.entries(R.MOODS)) {
    const chip = document.createElement("button");
    chip.className = "chip" + (key === state.mood ? " on" : "");
    chip.dataset.value = key;
    chip.textContent = mood.label;
    $("mood").append(chip);
  }
  $("mood").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    state.mood = chip.dataset.value;
    markChip($("mood"), state.mood);
    refreshAndRedraw();
  });

  $("period").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    state.period = chip.dataset.value;
    markChip($("period"), state.period);
    $("custom-range").hidden = state.period !== "custom";
    state.order = null;
    refreshAndRedraw();
  });
  for (const id of ["from", "to"]) $(id).addEventListener("change", refreshAndRedraw);
  for (const id of ["title", "sub"]) $(id).addEventListener("input", refreshAndRedraw);

  $("max-count").addEventListener("input", (e) => {
    state.maxCount = +e.target.value;
    $("max-count-value").textContent = `${state.maxCount}장`;
    refreshAndRedraw();
  });
  $("max-count-value").textContent = `${state.maxCount}장`;

  $("music-input").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      state.music = await player.audio.decodeAudioData(await file.arrayBuffer());
      state.musicName = file.name;
    } catch (err) {
      alert("이 음악 파일은 열 수 없어요. mp3나 m4a 파일로 해 보세요.");
      return;
    }
    $("music-name").textContent = `♪ ${file.name}`;
    $("music-clear").hidden = false;
    $("fit-music-label").hidden = false;
    refreshAndRedraw();
  });
  $("music-clear").addEventListener("click", () => {
    state.music = null;
    $("music-input").value = "";
    $("music-name").textContent = "음악 고르기";
    $("music-clear").hidden = true;
    $("fit-music-label").hidden = true;
    refreshAndRedraw();
  });
  $("fit-music").addEventListener("change", (e) => {
    state.fitMusic = e.target.checked;
    refreshAndRedraw();
  });

  // ------------------------------------------------------------ 사진 목록

  function shortDate(photo) {
    if (photo.date == null || photo.dateSource === "file") return "";
    const d = new Date(photo.date);
    return `${d.getMonth() + 1}.${d.getDate()}`;
  }

  function tile(photo, extra) {
    const figure = document.createElement("figure");
    figure.className = "tile";
    figure.dataset.id = photo.id;
    if (photo.thumbUrl) {
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = photo.name;
      img.src = photo.thumbUrl;
      figure.append(img);
    } else {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = photo.name;
      figure.append(empty);
    }
    extra(figure);
    return figure;
  }

  function renderKept() {
    const box = $("kept");
    box.replaceChildren(
      ...state.kept.map((photo) =>
        tile(photo, (figure) => {
          figure.insertAdjacentHTML(
            "beforeend",
            `<div class="tools"><span><button data-act="left" aria-label="앞으로">◀</button>
             <button data-act="right" aria-label="뒤로">▶</button></span>
             <button data-act="remove" aria-label="빼기">✕</button></div>
             <div class="date">${shortDate(photo)}</div>`
          );
        })
      )
    );
  }

  const REJECT_LIMIT = 300;
  function renderRejected() {
    const list = state.rejected.filter((r) => r.photo.thumbUrl || r.photo.error);
    const counts = {};
    for (const r of state.rejected) counts[r.reason] = (counts[r.reason] || 0) + 1;
    const parts = Object.entries(counts).map(([reason, n]) => `${reason} ${n}`);
    if (state.outOfRange) parts.push(`기간 밖 ${state.outOfRange}`);
    $("rejected-summary").textContent = `뺀 사진 ${state.rejected.length + state.outOfRange}장` + (parts.length ? ` · ${parts.join(" · ")}` : "");
    if (!$("rejected-box").open) return; // 열었을 때만 그린다 (수천 장일 수 있음)
    $("rejected").replaceChildren(
      ...list.slice(0, REJECT_LIMIT).map(({ photo, reason }) =>
        tile(photo, (figure) => {
          figure.classList.add("rejected");
          const badge = document.createElement("span");
          badge.className = "badge";
          badge.textContent = photo.error && photo.error !== reason ? photo.error : reason;
          figure.append(badge);
          if (!photo.error) figure.insertAdjacentHTML("beforeend", `<button class="add" data-act="add">+ 넣기</button>`);
        })
      )
    );
  }
  $("rejected-box").addEventListener("toggle", renderRejected);

  function onTileClick(e) {
    const figure = e.target.closest(".tile");
    if (!figure) return;
    const id = +figure.dataset.id;
    const act = e.target.closest("button")?.dataset.act;
    if (act === "remove") {
      state.forceIn.delete(id);
      state.forceOut.add(id);
    } else if (act === "add") {
      state.forceOut.delete(id);
      state.forceIn.add(id);
      if (state.kept.length >= state.maxCount) {
        state.maxCount = Math.min(60, state.kept.length + 1);
        $("max-count").value = state.maxCount;
        $("max-count-value").textContent = `${state.maxCount}장`;
      }
    } else if (act === "left" || act === "right") {
      const order = state.kept.map((p) => p.id);
      const i = order.indexOf(id);
      const j = act === "left" ? i - 1 : i + 1;
      if (j < 0 || j >= order.length) return;
      [order[i], order[j]] = [order[j], order[i]];
      state.order = order;
    } else {
      const seg = state.timeline.segments.find((s) => s.photoId === id);
      if (seg) player.seek(seg.start + Math.min(0.4, seg.end - seg.start));
      return;
    }
    refreshAndRedraw();
  }
  $("kept").addEventListener("click", onTileClick);
  $("rejected").addEventListener("click", onTileClick);

  // ------------------------------------------------------------ 재생

  function formatTime(s) {
    s = Math.max(0, Math.round(s));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  let currentTile = null;
  function updateClock(t) {
    const d = player.duration;
    $("clock").textContent = `${formatTime(t)} / ${formatTime(d)}`;
    if (!scrubbing) $("scrub").value = d ? Math.round((t / d) * 1000) : 0;
    const seg = state.timeline && R.activeSegments(state.timeline, t).pop();
    const next = seg ? $("kept").querySelector(`[data-id="${seg.photoId}"]`) : null;
    if (next !== currentTile) {
      currentTile && currentTile.classList.remove("current");
      next && next.classList.add("current");
      currentTile = next;
    }
  }
  player.onTime = updateClock;
  player.onEnd = () => ($("play").textContent = "▶");

  $("play").addEventListener("click", () => {
    if (player.playing) {
      player.pause();
      $("play").textContent = "▶";
    } else {
      $("play").textContent = "❚❚";
      player.play();
    }
  });

  let scrubbing = false;
  $("scrub").addEventListener("input", (e) => {
    scrubbing = true;
    player.pause();
    $("play").textContent = "▶";
    player.seek((e.target.value / 1000) * player.duration);
  });
  $("scrub").addEventListener("change", () => (scrubbing = false));

  // ------------------------------------------------------------ 영상 만들기

  function clearResult() {
    if (state.resultUrl) URL.revokeObjectURL(state.resultUrl);
    state.resultUrl = "";
    $("result").hidden = true;
  }

  function setBusy(busy) {
    for (const el of document.querySelectorAll(".settings-col button, .settings-col input, #play, #scrub, #export")) {
      el.disabled = busy;
    }
  }

  $("export").addEventListener("click", async () => {
    player.pause();
    clearResult();
    setBusy(true);
    $("export-status").hidden = false;
    $("export-bar").style.width = "0";
    let result;
    try {
      result = await player.record((t, d) => {
        $("export-bar").style.width = `${(t / d) * 100}%`;
        $("export-text").textContent = `영상을 만드는 중… ${formatTime(t)} / ${formatTime(d)} · 이 화면을 띄워 두세요`;
      });
    } catch (err) {
      alert(err.message || String(err));
      return;
    } finally {
      setBusy(false);
      $("export-status").hidden = true;
      $("play").textContent = "▶";
    }

    state.resultUrl = URL.createObjectURL(result.blob);
    const name = `${(state.timeline.title.text || "replay").replace(/[\\/:*?"<>|\s]+/g, "_")}.${result.extension}`;
    $("result-video").src = state.resultUrl;
    $("download").href = state.resultUrl;
    $("download").download = name;
    $("result-note").textContent =
      `${name} · ${(result.blob.size / 1024 / 1024).toFixed(1)}MB` +
      (result.extension === "webm" ? " · 이 브라우저는 WebM으로만 저장돼요. 인스타에 올리려면 크롬이나 사파리를 쓰세요." : "");
    const file = new File([result.blob], name, { type: result.type });
    $("share").hidden = !(navigator.canShare && navigator.canShare({ files: [file] }));
    $("share").onclick = () => navigator.share({ files: [file], title: state.timeline.title.text }).catch(() => {});
    $("result").hidden = false;
    $("result").scrollIntoView({ behavior: "smooth", block: "nearest" });
  });

  // 테스트에서 상태를 들여다볼 수 있게
  window.__replay = { state, player };
})();
