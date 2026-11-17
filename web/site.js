// Kathya pages. One file for the shelf and for every tool page: the tool page
// declares which tool it belongs to with <body data-tool="...">.

const WAVE_HEIGHTS = [6, 13, 21, 33, 24, 38, 16, 9, 27, 35, 40, 29, 15, 23, 36, 31, 11, 19, 34, 26, 13, 20, 7];

const state = {
  tool: null,
  picks: {},
  texts: {},
  startedAt: 0,
  timer: null,
};

function byId(id) {
  return document.getElementById(id);
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function fetchCatalogue() {
  const response = await fetch("/api/tools", { cache: "no-store" });
  if (!response.ok) throw new Error("कथ्य // Kathya could not load the tool list.");
  const payload = await response.json();
  return { tools: payload.tools || [], upcoming: payload.upcoming || [] };
}

async function fetchTools() {
  const { tools } = await fetchCatalogue();
  return tools;
}

function formatSize(bytes) {
  if (bytes >= 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  if (bytes >= 1024) return Math.round(bytes / 1024) + " KB";
  return bytes + " B";
}

function formatElapsed(seconds) {
  if (seconds < 60) return Math.round(seconds) + "s";
  return Math.floor(seconds / 60) + "m " + String(Math.round(seconds % 60)).padStart(2, "0") + "s";
}

function setStatus(text, isError = false) {
  const line = byId("status");
  line.textContent = text;
  line.classList.toggle("is-error", Boolean(isError) && text !== "");
}

// ------------------------------------------------------------------------- //
// Index: the tool shelf
// ------------------------------------------------------------------------- //

async function startIndex() {
  const shelf = byId("shelf");
  const note = byId("shelf-note");

  let tools, upcoming;
  try {
    ({ tools, upcoming } = await fetchCatalogue());
  } catch (error) {
    shelf.replaceChildren(element("p", "shelf-empty", error.message));
    return;
  }

  if (!tools.length && !upcoming.length) {
    shelf.replaceChildren(element("p", "shelf-empty", "No tools yet. Add one to registry.py."));
    return;
  }

  shelf.replaceChildren(...tools.map(buildTile), ...upcoming.map(buildUpcomingTile));

  const parts = [
    tools.length === 1 ? "1 tool available." : tools.length + " tools available.",
  ];
  if (upcoming.length) {
    parts.push(upcoming.length + (upcoming.length === 1 ? " more tool" : " more tools") + " under development.");
  }
  note.textContent = parts.join(" ");
}

function buildTile(tool) {
  const tile = element("a", "tile");
  tile.href = tool.page;
  tile.append(
    element("span", "tile-name", tool.name),
    element("span", "tile-note", tool.tagline),
  );
  return tile;
}

function buildUpcomingTile(tool) {
  const tile = element("div", "tile tile--soon");
  tile.append(
    element("span", "tile-status", tool.status),
    element("span", "tile-name", tool.name),
    element("span", "tile-note", tool.tagline),
    element("span", "tile-features", tool.features.join(" · ")),
  );
  return tile;
}

// ------------------------------------------------------------------------- //
// Tool page
// ------------------------------------------------------------------------- //

async function startTool() {
  const toolId = document.body.dataset.tool;

  let tools;
  try {
    tools = await fetchTools();
  } catch (error) {
    setStatus(error.message, true);
    return;
  }

  const tool = tools.find((candidate) => candidate.id === toolId);
  if (!tool) {
    setStatus("This tool is no longer registered. Go back to the tool list.", true);
    return;
  }

  state.tool = tool;
  document.title = tool.name + " — कथ्य // Kathya";
  byId("tool-name").textContent = tool.name;
  byId("tool-tagline").textContent = tool.tagline;

  byId("fields").replaceChildren(
    ...tool.inputs.map((input) => (input.kind === "file" ? buildStage(input) : buildText(input))),
  );

  const button = byId("submit");
  button.textContent = tool.action || "Generate";
  button.disabled = true;
  button.dataset.busy = "false";

  byId("form").addEventListener("submit", submitJob);
  byId("again").addEventListener("click", () => window.location.reload());
}

function videoIcon() {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", "tool-icon");
  svg.setAttribute("viewBox", "0 0 56 40");
  svg.setAttribute("aria-hidden", "true");

  const frame = document.createElementNS(ns, "rect");
  frame.setAttribute("x", "1");
  frame.setAttribute("y", "1");
  frame.setAttribute("width", "54");
  frame.setAttribute("height", "38");
  frame.setAttribute("fill", "none");
  frame.setAttribute("stroke", "currentColor");
  frame.setAttribute("stroke-width", "2");

  const play = document.createElementNS(ns, "path");
  play.setAttribute("d", "M23 12 L40 20 L23 28 Z");
  play.setAttribute("fill", "currentColor");

  svg.append(frame, play);
  return svg;
}

function stageIcon(input) {
  const accept = (input.accept || "").toLowerCase();
  return accept.includes("video/") && !accept.includes("audio/")
    ? videoIcon()
    : waveElement();
}

function waveElement() {
  const wave = element("span", "wave");
  wave.setAttribute("aria-hidden", "true");
  for (const height of WAVE_HEIGHTS) {
    const bar = document.createElement("i");
    bar.style.setProperty("--h", height + "px");
    wave.append(bar);
  }
  return wave;
}

function buildStage(input) {
  const stage = element("div", "stage");

  const drop = element("label", "drop");
  drop.htmlFor = "field-" + input.name;

  const picker = document.createElement("input");
  picker.type = "file";
  picker.id = "field-" + input.name;
  picker.className = "visually-hidden";
  picker.required = true;
  if (input.accept) picker.accept = input.accept;

  const title = element("span", "drop-title", "Drop your " + input.label.toLowerCase() + " here");
  const hint = element("span", "drop-hint", "or click to browse · " + (input.hint || "up to 100 MB"));
  const caption = element("span", "caption-line");
  caption.hidden = true;

  const choose = (file) => {
    if (!file) return;
    if (file.size > 100 * 1024 * 1024) {
      setStatus("That file is " + formatSize(file.size) + ". The limit is 100 MB.", true);
      return;
    }
    state.picks[input.name] = file;
    drop.classList.add("is-picked");
    title.textContent = "Ready to generate";
    hint.textContent = formatSize(file.size) + " · click to choose a different file";
    caption.textContent = file.name;
    caption.hidden = false;
    setStatus("");
    refreshSubmit();
  };

  picker.addEventListener("change", () => choose(picker.files[0]));

  stage.addEventListener("dragover", (event) => {
    event.preventDefault();
    drop.classList.add("is-over");
  });
  stage.addEventListener("dragleave", (event) => {
    if (!stage.contains(event.relatedTarget)) drop.classList.remove("is-over");
  });
  stage.addEventListener("drop", (event) => {
    event.preventDefault();
    drop.classList.remove("is-over");
    choose(event.dataTransfer.files[0]);
  });

  const player = element("video", "player");
  player.controls = true;
  player.playsInline = true;
  player.hidden = true;

  drop.append(stageIcon(input), title, hint, caption, picker);
  stage.append(drop, player);
  return stage;
}

function buildText(input) {
  const field = element("label", "field");
  field.htmlFor = "field-" + input.name;

  const area = document.createElement("textarea");
  area.id = "field-" + input.name;
  area.rows = 7;
  area.placeholder = input.hint || "";
  area.addEventListener("input", () => {
    state.texts[input.name] = area.value;
    refreshSubmit();
  });

  field.append(element("span", "field-label", input.label), area);
  return field;
}

function refreshSubmit() {
  const ready = (state.tool?.inputs || []).every((input) => {
    if (input.kind === "file") return Boolean(state.picks[input.name]);
    return Boolean((state.texts[input.name] || "").trim());
  });
  const button = byId("submit");
  button.disabled = !ready || button.dataset.busy === "true";
}

function resetResult() {
  const player = document.querySelector(".player");
  if (player) {
    player.hidden = true;
    player.removeAttribute("src");
  }
  const drop = document.querySelector(".drop");
  if (drop) drop.hidden = false;

  byId("download").hidden = true;
  byId("again").hidden = true;
  byId("progress").hidden = true;
  byId("progress-fill").style.setProperty("--value", "0");
  setStatus("");
}

function suggestedName() {
  const file = Object.values(state.picks)[0];
  const stem = file ? file.name.replace(/\.[^.]+$/, "") : "kathya";
  const types = {
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "image/png": "png",
    "image/jpeg": "jpg",
    "application/zip": "zip",
  };
  return stem + "." + (types[state.tool?.output_type] || "mp4");
}

function updateProgress(job) {
  const seconds = (Date.now() - state.startedAt) / 1000;
  const tail = job.status === "queued" ? "in line" : formatElapsed(seconds) + " elapsed";
  setStatus((job.activity || "Working") + " — " + tail);

  byId("progress").hidden = false;
  if (typeof job.progress === "number") {
    const fill = byId("progress-fill");
    const current = parseFloat(fill.style.getPropertyValue("--value")) || 0;
    fill.style.setProperty("--value", String(Math.min(Math.max(job.progress, current, 0), 1)));
  }
}

function showResult(job) {
  const player = document.querySelector(".player");
  const drop = document.querySelector(".drop");
  const url = job.output_url;
  const previewable = Boolean(url) && /^(video|audio|image)\//.test(job.output_type);

  if (player && previewable) {
    if (job.output_type.startsWith("image/")) {
      const image = element("img", "player");
      image.alt = "Result";
      image.src = url;
      player.replaceWith(image);
    } else if (job.output_type.startsWith("audio/")) {
      const audio = element("audio", "player");
      audio.controls = true;
      audio.src = url;
      player.replaceWith(audio);
    } else {
      player.src = url;
      player.hidden = false;
    }
  }
  if (drop && url) drop.hidden = true;

  const download = byId("download");
  download.href = url || "";
  download.download = suggestedName();
  download.hidden = !url;
  download.textContent = job.output_type === "application/zip" ? "Download ZIP" : "Download";

  const button = byId("submit");
  button.dataset.busy = "false";
  button.disabled = true;
  button.textContent = state.tool.action || "Generate";

  byId("again").hidden = false;
  byId("progress-fill").style.setProperty("--value", "1");
  const note = !url
    ? "."
    : previewable
      ? ". Preview above, or download it."
      : ". Your files are in the ZIP below.";
  setStatus("Done in " + formatElapsed(job.elapsed) + note);
}

function fail(message, detail) {
  setStatus([message, detail].filter(Boolean).join("\n\n"), true);
}

function stopTimer() {
  clearInterval(state.timer);
  state.timer = null;
}

function finishRun() {
  const button = byId("submit");
  button.dataset.busy = "false";
  button.disabled = false;
  button.textContent = state.tool.action || "Generate";
}

async function poll(jobId) {
  const response = await fetch("/api/jobs/" + jobId, { cache: "no-store" });
  if (!response.ok) throw new Error((await response.text()).trim() || "Lost track of the job.");
  const job = await response.json();

  if (job.status === "done") {
    stopTimer();
    showResult(job);
    return;
  }

  if (job.status === "failed") {
    stopTimer();
    finishRun();
    byId("progress-fill").style.setProperty("--value", "0");
    fail("The tool stopped before finishing.", job.error || "");
    return;
  }

  updateProgress(job);
}

async function submitJob(event) {
  event.preventDefault();
  if (byId("submit").dataset.busy === "true") return;

  const body = new FormData();
  body.append("tool", state.tool.id);
  for (const input of state.tool.inputs) {
    if (input.kind === "file") {
      const file = state.picks[input.name];
      if (file) body.append(input.name, file, file.name);
    } else {
      body.append(input.name, state.texts[input.name] || "");
    }
  }

  resetResult();

  const button = byId("submit");
  button.dataset.busy = "true";
  button.disabled = true;
  button.textContent = "Working…";
  byId("progress").hidden = false;
  byId("progress-fill").style.setProperty("--value", "0.02");
  state.startedAt = Date.now();
  setStatus("Uploading");

  let jobId;
  try {
    const response = await fetch("/api/jobs", { method: "POST", body });
    if (!response.ok) throw new Error((await response.text()).trim() || "The server refused the job.");
    jobId = (await response.json()).id;
  } catch (error) {
    finishRun();
    fail("Could not start the job.", error.message);
    return;
  }

  setStatus("Queued");

  const tick = async () => {
    try {
      await poll(jobId);
    } catch (error) {
      stopTimer();
      finishRun();
      fail("Lost contact with the server.", error.message);
    }
  };

  state.timer = setInterval(tick, 1200);
  tick();
}

// ------------------------------------------------------------------------- //

if (document.body.dataset.page === "index") {
  startIndex();
} else if (document.body.dataset.tool) {
  startTool();
}
