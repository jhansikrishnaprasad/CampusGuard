"use strict";
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ICON = {
  dash: '<path d="M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z"/>',
  up: '<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>',
  film: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4M3 16h4M17 8h4M17 16h4"/>',
  alert: '<path d="M12 3l10 18H2zM12 10v5M12 18h.01"/>',
  shirt: '<path d="M8 3l-5 4 3 3 2-1v12h8V9l2 1 3-3-5-4a4 4 0 0 1-8 0z"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
};
const NAV = [["dashboard", "Dashboard", "dash"], ["upload", "Upload", "up"], ["videos", "Videos", "film"], ["incidents", "Incidents", "alert"],
  ["uniform", "Uniform & ID", "shirt"], ["reports", "Reports", "chart"], ["settings", "Settings", "gear"]];
const CAT = { possible_physical_fighting: "Possible physical fighting", possible_smoking: "Possible smoking", uniform_possible_violation: "Possible uniform non-compliance" };
const LBL = {
  pending_review: "Pending review", confirmed: "Confirmed", dismissed: "Dismissed", inconclusive: "Inconclusive", predicted: "AI prediction", uncertain: "Uncertain",
  ok: "Colour in range", inconsistent: "Colour outside range", unable_to_verify: "Unable to verify",
  COMPLIANT: "Appears compliant", POSSIBLE_SHIRT_MISMATCH: "Possible shirt mismatch", POSSIBLE_TROUSER_MISMATCH: "Possible trouser mismatch",
  POSSIBLE_UNIFORM_MISMATCH: "Possible uniform mismatch", UNCERTAIN: "Uncertain", NOT_ASSESSED: "Not assessed",
  CARD_VISIBLE: "ID card visible", CARD_NOT_DETECTED: "Card not detected", completed_partial: "Completed (partial)",
  POSSIBLE_VIOLATION: "Possible violation", POSSIBLE_FIGHTING: "Possible fighting", POSSIBLE_SMOKING: "Possible smoking",
  NOT_DETECTED: "Nothing detected", LOADED: "Loaded", FILE_MISSING: "File missing", DEPENDENCY_MISSING: "Dependency missing", LOAD_FAILED: "Load failed",
  NOT_CONFIGURED: "Not configured", DISABLED: "Disabled", EVALUATED: "Evaluated", NOT_EVALUATED: "Not evaluated",
  uploaded: "Uploaded", queued: "Queued", processing: "Processing", running: "Running", completed: "Completed", failed: "Failed", cancelled: "Cancelled",
};
const chip = (s) => `<span class="chip ${esc(String(s).toLowerCase())}">${esc(LBL[s] || s)}</span>`;
const ts = (t) => { t = Math.floor(t || 0); const p = (n) => String(n).padStart(2, "0"); return `${p(Math.floor(t / 3600))}:${p(Math.floor((t % 3600) / 60))}:${p(t % 60)}`; };
const mb = (b) => (b / 1048576).toFixed(1) + " MB";
let ME = null, timer = null;

async function api(path, opts = {}) {
  const r = await fetch("/api" + path, { credentials: "same-origin", ...opts, headers: { ...(opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}), ...(opts.headers || {}) } });
  if (r.status === 401 && !path.startsWith("/auth/login")) { showLogin(); throw new Error("Please sign in"); }
  if (!r.ok) { let m = r.statusText; try { const j = await r.json(); m = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (e) {} throw new Error(m); }
  return r.status === 204 ? null : r.json();
}
const post = (p, b) => api(p, { method: "POST", body: b === undefined ? undefined : JSON.stringify(b) });
function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.remove("hidden"); setTimeout(() => t.classList.add("hidden"), 3200); }
function qs(o) { const p = new URLSearchParams(); Object.entries(o).forEach(([k, v]) => v && p.set(k, v)); const s = p.toString(); return s ? "?" + s : ""; }

function chart(el, type, labels, values, colors) {
  const pal = colors || ["#315EFB", "#22D3EE", "#8B5CF6", "#14B8A6", "#F59E0B", "#F0506E"];
  if (!values.length || values.every((v) => !v)) { el.innerHTML = '<p class="muted">No data yet.</p>'; return; }
  if (window.Chart) {
    el.innerHTML = "<canvas></canvas>";
    new Chart($("canvas", el), { type, data: { labels, datasets: [{ data: values, backgroundColor: pal, borderRadius: type === "bar" ? 6 : 0 }] },
      options: { plugins: { legend: { display: type !== "bar", position: "bottom" } }, scales: type === "bar" ? { y: { beginAtZero: true, ticks: { precision: 0 } } } : {}, maintainAspectRatio: false } });
    el.style.height = "240px";
  } else {  // offline fallback without Chart.js
    const mx = Math.max(...values);
    el.innerHTML = labels.map((l, i) => `<div style="margin:6px 0"><small>${esc(l)} — ${values[i]}</small><div class="bar"><i style="width:${(values[i] / mx) * 100}%"></i></div></div>`).join("");
  }
}

/* ---------- auth / shell ---------- */
function showLogin() { $("#app").classList.add("hidden"); $("#login").classList.remove("hidden"); clearInterval(timer); stopWatcher(); }
async function boot() {
  const th = localStorage.getItem("theme"); if (th) document.documentElement.dataset.theme = th;
  try { ME = await api("/auth/me"); if (ME.login_required === false) $("#logout").classList.add("hidden"); if (ME.can_shutdown) $("#quit").classList.remove("hidden"); enter(); } catch (e) { showLogin(); }
}
function enter() {
  $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
  $("#uname").textContent = ME.username; $("#urole").textContent = ME.role;
  $("#nav").innerHTML = NAV.map(([k, n, i]) => `<a data-k="${k}" href="#/${k}"><svg viewBox="0 0 24 24">${ICON[i]}</svg>${n}</a>`).join("");
  route();
  startWatcher();   // in-app completion notifications (silent baseline on the first poll)
}
$("#lbtn").onclick = async () => {
  $("#lerr").classList.add("hidden");
  try { ME = await post("/auth/login", { username: $("#lu").value, password: $("#lp").value }); $("#lp").value = ""; enter(); }
  catch (e) { $("#lerr").textContent = e.message; $("#lerr").classList.remove("hidden"); }
};
$("#lp").onkeydown = (e) => e.key === "Enter" && $("#lbtn").click();
$("#logout").onclick = async () => { await post("/auth/logout"); showLogin(); };
$("#quit").onclick = async () => {
  if (!confirm("Stop CampusGuard? Running analyses will be interrupted and resume on the next start.")) return;
  try { await post("/system/shutdown"); } catch (e) { return toast(e.message); }
  stopWatcher(); clearInterval(timer);
  document.body.innerHTML = '<div style="font:18px system-ui;padding:60px;text-align:center"><h2>CampusGuard has stopped</h2><p>You can close this tab. Start CampusGuard.exe again to continue.</p></div>';
};
$("#theme").onclick = () => { const d = document.documentElement; d.dataset.theme = d.dataset.theme === "dark" ? "light" : "dark"; localStorage.setItem("theme", d.dataset.theme); };
$("#menu").onclick = () => $("#side").classList.toggle("open");
window.addEventListener("hashchange", () => ME && route());
function modal(html) { $("#modalbody").innerHTML = html; $("#modal").classList.remove("hidden"); }
function closeModal() { $("#modal").classList.add("hidden"); $("#modalbody").innerHTML = ""; }
$("#modal").onclick = (e) => e.target.id === "modal" && closeModal();

const PAGES = { dashboard: pgDashboard, upload: pgUpload, videos: pgVideos, video: pgVideo, incidents: pgIncidents, uniform: pgUniform, reports: pgReports, settings: pgSettings };
function route() {
  clearInterval(timer); $("#side").classList.remove("open");
  const [path, query] = (location.hash.slice(2) || "dashboard").split("?");
  const [page, arg] = path.split("/");
  PAGE = page; CUR_VIDEO = null;
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.k === (page === "video" ? "videos" : page)));
  $("#topact").innerHTML = "";
  (PAGES[page] || pgDashboard)(arg, new URLSearchParams(query || "")).catch((e) => { $("#view").innerHTML = `<div class="alert err">${esc(e.message)}</div>`; });
}
const setTitle = (t) => ($("#title").textContent = t);

/* ---------- dashboard ---------- */
async function pgDashboard() {
  setTitle("Dashboard");
  const d = await api("/dashboard");
  const co = await api("/compliance/overview").catch(() => null);   // never lets a compliance error break the dashboard
  const S = (n, l, c) => `<div class="card stat" style="--c:${c}"><b>${n}</b><span>${l}</span></div>`;
  $("#view").innerHTML = (d.model_warnings.length ? `<div class="alert warn"><b>Model availability</b><br>${d.model_warnings.map(esc).join("<br>")}<br><a href="#/settings">Details in Settings</a></div>` : "") + complianceOverviewHtml(co) + `<div class="grid g4">${S(d.videos_total, "Videos uploaded", "var(--blue)")}${S(d.analyses_completed, "Completed analyses", "var(--teal)")}
    ${S(d.videos_processing, "Currently processing", "var(--cyan)")}${S(d.analyses_partial, "Partial analyses (AI modules skipped)", "var(--amber)")}${S(d.pending_review, "Pending review", "var(--amber)")}${S(d.confirmed, "Confirmed incidents", "var(--coral)")}${S(d.analyses_failed, "Failed analyses", "var(--violet)")}</div>
    <div class="grid g2" style="margin-top:16px"><div class="card"><h3>Incident categories (all findings, incl. unreviewed)</h3><div id="c1"></div></div>
    <div class="card"><h3>Review outcomes</h3><div id="c2"></div></div></div>
    <div class="grid g2" style="margin-top:16px"><div class="card"><h3>Recent processing jobs</h3>${d.recent_jobs.length ? `<div class="tw"><table><tr><th>Video</th><th>Status</th><th>Progress</th></tr>${d.recent_jobs.map((j) => `<tr class="click" onclick="location.hash='#/video/${j.video_id}'"><td>${esc(j.video_name)}</td><td>${chip(j.status)}</td><td>${Math.round(j.progress * 100)}%</td></tr>`).join("")}</table></div>` : '<p class="muted">No jobs yet. Upload a video to begin.</p>'}</div>
    <div class="card"><h3>Recent review activity</h3>${d.recent_reviews.length ? `<table>${d.recent_reviews.map((r) => `<tr><td>Event #${r.event_id}</td><td>${chip(r.decision)}</td><td>${esc(r.reviewer)}</td><td class="muted">${esc((r.at || "").slice(0, 16).replace("T", " "))}</td></tr>`).join("")}</table>` : '<p class="muted">No reviews recorded yet.</p>'}</div></div>`;
  const bn = $("#cg-bn"); if (bn) bn.onclick = enableBrowserNotifications;
  chart($("#c1"), "doughnut", Object.keys(d.by_category).map((k) => d.category_labels[k]), Object.values(d.by_category));
  chart($("#c2"), "bar", ["Pending", "Confirmed", "Dismissed", "Inconclusive"], [d.pending_review, d.confirmed, d.dismissed, d.inconclusive], ["#F59E0B", "#F0506E", "#14B8A6", "#8B5CF6"]);
}

/* ---------- upload ---------- */
async function pgUpload() {
  setTitle("Upload footage");
  const st = await api("/settings"); const p = st.processing; const mm = await api("/system/models");
  $("#view").innerHTML = (mm.warnings.length ? `<div class="alert warn"><b>Heads-up — this analysis will be PARTIAL / limited:</b><br>${mm.warnings.map(esc).join("<br>")}</div>` : "") + `<div class="grid g2"><div class="card"><div class="drop" id="drop"><h2>Drag &amp; drop a video here</h2><p class="muted">MP4, AVI or MOV · up to ${p.max_file_mb} MB · ${p.min_duration_s} s – ${Math.round(p.max_duration_s / 60)} min<br>(designed for 10–60 min CCTV recordings)</p><button class="btn" id="browse">Browse files</button><input type="file" id="file" accept=".mp4,.avi,.mov" class="hidden"></div>
    <div id="sel" style="margin-top:14px"></div><div id="uerr"></div></div>
    <div class="card"><h3>Analysis settings</h3><p class="muted">Applied from the Settings page. Current values:</p><dl class="kv"><dt>Person sampling</dt><dd>${p.person_fps} frames/s</dd><dt>Activity sampling</dt><dd>${p.activity_fps} frames/s (only if a model is installed)</dd><dt>Fighting threshold</dt><dd>${st.activity.fight.threshold}</dd><dt>Smoking threshold</dt><dd>${st.activity.smoking.threshold}</dd></dl>
    <label style="display:flex;gap:8px;margin-top:14px"><input type="checkbox" id="auto" checked style="width:auto"> Start analysis immediately after upload</label>
    <button class="btn primary w100" id="go" style="margin-top:14px" disabled>Upload &amp; analyse</button><div id="prog" class="hidden" style="margin-top:12px"><div class="bar"><i id="pbar" style="width:0"></i></div><small id="ptxt" class="muted"></small></div></div></div>`;
  let file = null;
  const pick = (f) => {
    file = f; $("#uerr").innerHTML = "";
    const ext = f.name.split(".").pop().toLowerCase();
    if (!["mp4", "avi", "mov"].includes(ext)) { $("#uerr").innerHTML = '<div class="alert err">Unsupported type. Use MP4, AVI or MOV.</div>'; $("#go").disabled = true; return; }
    if (f.size > p.max_file_mb * 1048576) { $("#uerr").innerHTML = `<div class="alert err">File exceeds ${p.max_file_mb} MB.</div>`; $("#go").disabled = true; return; }
    $("#sel").innerHTML = `<div class="alert info"><b>${esc(f.name)}</b> · ${mb(f.size)} · <span id="dur">reading duration…</span></div>`;
    const v = document.createElement("video"); v.preload = "metadata"; v.src = URL.createObjectURL(f);
    v.onloadedmetadata = () => { $("#dur").textContent = `${(v.duration / 60).toFixed(1)} min`; URL.revokeObjectURL(v.src); };
    v.onerror = () => { $("#dur").textContent = "preview unavailable (server will still validate)"; };
    $("#go").disabled = false;
  };
  const drop = $("#drop");
  $("#browse").onclick = () => $("#file").click(); $("#file").onchange = (e) => e.target.files[0] && pick(e.target.files[0]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); }; drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); e.dataTransfer.files[0] && pick(e.dataTransfer.files[0]); };
  $("#go").onclick = () => {
    const fd = new FormData(); fd.append("file", file); fd.append("start_analysis", $("#auto").checked ? "true" : "false");
    const x = new XMLHttpRequest(); x.open("POST", "/api/videos"); $("#go").disabled = true; $("#prog").classList.remove("hidden");
    x.upload.onprogress = (e) => { if (e.lengthComputable) { $("#pbar").style.width = (e.loaded / e.total) * 100 + "%"; $("#ptxt").textContent = `Uploading ${mb(e.loaded)} / ${mb(e.total)}`; } };
    x.onload = () => {
      if (x.status === 201) { const v = JSON.parse(x.responseText); toast(v.duplicate_of && v.duplicate_of.length ? "Uploaded (same content as video #" + v.duplicate_of[0] + ")" : "Upload complete"); location.hash = `#/video/${v.id}`; }
      else { let m = x.statusText; try { m = JSON.parse(x.responseText).detail; } catch (e) {} $("#uerr").innerHTML = `<div class="alert err">${esc(m)}</div>`; $("#go").disabled = false; $("#prog").classList.add("hidden"); }
    };
    x.onerror = () => { $("#uerr").innerHTML = '<div class="alert err">Network error during upload.</div>'; $("#go").disabled = false; };
    x.send(fd);
  };
}

/* ---------- videos ---------- */
async function pgVideos() {
  setTitle("Video processing history");
  $("#view").innerHTML = `<div class="card"><div class="row"><div class="field"><label>Search filename</label><input id="vq"></div><div class="field"><label>Status</label><select id="vs"><option value="">All</option>${["uploaded", "queued", "processing", "completed", "failed", "cancelled"].map((s) => `<option value="${s}">${LBL[s]}</option>`).join("")}</select></div><button class="btn primary" id="vgo">Search</button></div><div id="vl"></div></div>`;
  const load = async () => {
    const r = await api("/videos" + qs({ q: $("#vq").value, status: $("#vs").value }));
    $("#vl").innerHTML = r.items.length ? `<div class="tw"><table><tr><th>Name</th><th>Uploaded</th><th>Length</th><th>Size</th><th>Status</th><th>Events</th></tr>${r.items.map((v) => `<tr class="click" onclick="location.hash='#/video/${v.id}'"><td>${esc(v.filename)}</td><td>${esc(v.uploaded_at.slice(0, 16).replace("T", " "))}</td><td>${ts(v.duration_s)}</td><td>${mb(v.size_bytes)}</td><td>${chip(v.status)}</td><td>${v.event_count}</td></tr>`).join("")}</table></div>` : '<p class="muted">No videos found.</p>';
  };
  $("#vgo").onclick = load; load();
}

/* ---------- video analysis ---------- */
async function pgVideo(id, q) {
  setTitle("Video analysis");
  const render = async (keepPlayer) => {
    const v = await api(`/videos/${id}`); const evs = await api(`/videos/${id}/events`);
    const job = v.jobs[0]; const active = job && ["queued", "running"].includes(job.status);
    if (!keepPlayer) {
      $("#view").innerHTML = `<div id="compliance"></div><div class="grid g2" style="grid-template-columns:minmax(0,2fr) minmax(300px,1fr)"><div><div class="card"><video id="pl" controls preload="metadata" src="${v.stream_url}"></video><div class="timeline" id="tl"><div class="ph" id="ph"></div></div>
        <p class="muted" style="margin:6px 0 0">Timeline markers = AI findings awaiting/after review (click to jump). Evidence frames contain the detection overlays.${v.has_preview ? "" : " If the video won't play, your browser may not support its codec (install ffmpeg to auto-create a preview)."}</p></div><div class="card" style="margin-top:16px" id="meta"></div></div>
        <div><div class="card" id="job"></div><div class="card evlist" style="margin-top:16px" id="evs"></div></div></div>`;
    }
    $("#meta").innerHTML = `${v.duplicate_of && v.duplicate_of.length ? `<div class="alert info">Same file content as video #${v.duplicate_of.join(", #")} (duplicate upload).</div>` : ""}<h3>${esc(v.filename)}</h3><dl class="kv"><dt>Status</dt><dd>${chip(v.status)}</dd><dt>Duration</dt><dd>${ts(v.duration_s)}</dd><dt>Resolution</dt><dd>${v.width}×${v.height} @ ${v.fps} fps</dd><dt>Size</dt><dd>${mb(v.size_bytes)}</dd><dt>Uploaded</dt><dd>${esc(v.uploaded_at.slice(0, 16).replace("T", " "))}</dd></dl>
      <h3 style="margin-top:14px">Processing runs</h3>${v.jobs.length ? `<table>${v.jobs.map((j) => `<tr><td>#${j.id} <small class="muted">run ${j.attempt}</small></td><td>${chip(j.status)}</td><td>${j.is_current ? '<span class="chip loaded">current</span>' : '<span class="chip">history</span>'}</td></tr>`).join("")}</table><p class="muted">Findings shown are from the current run. Earlier runs are kept in the database.</p>` : '<p class="muted">None yet.</p>'}`;
    $("#job").innerHTML = `<h3>Processing</h3>${job ? `<div>${chip(job.status)} <small class="muted">job #${job.id}</small></div>${job.partial ? '<div class="alert warn"><b>Partial analysis.</b> Some requested AI modules did not run, so the absence of findings does not mean nothing happened. See modules below.</div>' : ""}<div class="bar" style="margin:10px 0"><i style="width:${job.progress * 100}%"></i></div><small class="muted">${Math.round(job.progress * 100)}%${job.processing_seconds ? " · took " + job.processing_seconds.toFixed(1) + " s" : ""}</small>` : '<p class="muted">Not analysed yet.</p>'}
      ${job && job.modules && job.modules.length ? `<details open><summary>Module outcomes of this run</summary><div class="tw"><table><tr><th>Module</th><th>Ran</th><th>Result</th><th>Evaluation</th></tr>${job.modules.map((m) => `<tr><td>${esc(m.module)}</td><td>${m.ran ? chip("LOADED") : (m.requested ? chip(m.state) : chip("DISABLED"))}</td><td>${m.ran ? `<small>${esc(LBL[m.result] || m.result || "")}</small>` : chip("NOT_ASSESSED")}</td><td>${m.ran ? chip(m.evaluation || "NOT_EVALUATED") : ""}</td></tr>`).join("")}</table></div><p class="muted">“Not assessed” means the module did not run: it says nothing about whether such events happened.</p></details>` : ""}${job && job.error ? `<div class="alert err">${esc(job.error)}</div>` : ""}${(job?.warnings || []).map((w) => `<div class="alert warn">${esc(w)}</div>`).join("")}
      <div class="row" style="margin-top:10px">${!active ? `<button class="btn primary" id="start">${job ? "Reprocess" : "Start analysis"}</button>` : `<button class="btn danger" id="cancel">Cancel</button>`}</div>`;
    $("#evs").innerHTML = `<h3>Detected events (${evs.length})</h3>` + (evs.length ? evs.map((e) => `<div class="evi" data-t="${e.start_s}"><b>${esc(e.category_label)}</b> ${chip(e.review_status)}<br><small class="muted">${e.start}–${e.end}${e.track_ref ? " · " + esc(e.track_ref) : ""}${e.confidence != null ? " · conf " + e.confidence.toFixed(2) : ""}</small><br><a href="#" data-open="${e.id}">Details &amp; review</a></div>`).join("") : `<p class="muted">${job && job.status === "completed" ? "No events found by the enabled models." : "No events yet."}</p>`);
    const pl = $("#pl"), tl = $("#tl"); tl.querySelectorAll(".mk").forEach((n) => n.remove());
    evs.forEach((e) => { const m = document.createElement("div"); m.className = "mk " + e.category; m.style.left = (e.start_s / v.duration_s) * 100 + "%"; m.style.width = Math.max(0.6, ((e.end_s - e.start_s) / v.duration_s) * 100) + "%"; m.title = `${e.category_label} ${e.start}`; m.onclick = (ev) => { ev.stopPropagation(); pl.currentTime = e.start_s; }; tl.appendChild(m); });
    tl.onclick = (ev) => { const r = tl.getBoundingClientRect(); pl.currentTime = ((ev.clientX - r.left) / r.width) * v.duration_s; };
    pl.ontimeupdate = () => ($("#ph").style.left = (pl.currentTime / v.duration_s) * 100 + "%");
    document.querySelectorAll(".evi").forEach((n) => (n.onclick = () => { pl.currentTime = +n.dataset.t; pl.play(); }));
    document.querySelectorAll("[data-open]").forEach((a) => (a.onclick = (ev) => { ev.preventDefault(); ev.stopPropagation(); openEvent(+a.dataset.open, () => render(true)); }));
    const s = $("#start"), c = $("#cancel");
    if (s) s.onclick = async () => { try { await post(`/videos/${id}/analyze`); toast("Analysis queued"); render(true); } catch (e) { toast(e.message); } };
    if (c) c.onclick = async () => { await post(`/jobs/${job.id}/cancel`); toast("Cancel requested"); render(true); };
    if (!active || !keepPlayer) renderCompliance(id, false).catch(() => {});   // redraws only when the stored result changed
    clearInterval(timer); if (active) timer = setInterval(() => render(true).catch(() => {}), 2500);
    if (!keepPlayer && q.get("t")) pl.currentTime = +q.get("t");
  };
  CUR_VIDEO = { id: +id, refresh: async () => { await render(true); await renderCompliance(id, true); } };
  await render(false);
  if (q.get("section") === "compliance") setTimeout(() => $("#compliance")?.scrollIntoView({ behavior: "smooth", block: "start" }), 500);
}

/* ---------- incidents ---------- */
async function pgIncidents() {
  setTitle("Incident management");
  const vids = await api("/videos?limit=200");
  $("#view").innerHTML = `<div class="card"><div class="row"><div class="field"><label>Search</label><input id="iq" placeholder="video, track, notes"></div>
    <div class="field"><label>Video</label><select id="iv"><option value="">All</option>${vids.items.map((v) => `<option value="${v.id}">${esc(v.filename)}</option>`).join("")}</select></div>
    <div class="field"><label>Category</label><select id="ic"><option value="">All</option>${Object.entries(CAT).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div>
    <div class="field"><label>Review status</label><select id="is"><option value="">All</option>${["pending_review", "confirmed", "dismissed", "inconclusive"].map((s) => `<option value="${s}">${LBL[s]}</option>`).join("")}</select></div>
    <div class="field"><label>From</label><input type="date" id="id1"></div><div class="field"><label>To</label><input type="date" id="id2"></div><label style="flex:0 0 auto;display:flex;gap:6px;align-items:center"><input type="checkbox" id="ih" style="width:auto"> earlier runs</label><button class="btn primary" id="igo">Filter</button></div><div id="il"></div></div>`;
  const load = async () => {
    const r = await api("/events" + qs({ q: $("#iq").value, video_id: $("#iv").value, category: $("#ic").value, review_status: $("#is").value, date_from: $("#id1").value, date_to: $("#id2").value, include_history: $("#ih").checked ? "true" : "", limit: 100 }));
    $("#il").innerHTML = r.items.length ? `<div class="tw"><table><tr><th>ID</th><th>Video</th><th>Time</th><th>Category</th><th>Track</th><th>Conf.</th><th>AI status</th><th>Review</th><th>Evidence</th><th>Notes</th></tr>${r.items.map((e) => `<tr class="click" data-e="${e.id}"><td>#${e.id}</td><td>${esc(e.video)}</td><td>${e.start}</td><td>${esc(e.category_label)}</td><td>${esc(e.track_ref || "—")}</td><td>${e.confidence != null ? e.confidence.toFixed(2) : "—"}</td><td>${chip(e.automated_status)}</td><td>${chip(e.review_status)}</td><td>${e.evidence_available ? "Yes" : "No"}</td><td>${esc((e.review_notes || "").slice(0, 40))}</td></tr>`).join("")}</table></div><p class="muted">${r.total} finding(s). Predictions are not confirmed incidents until a reviewer confirms them.</p>` : '<p class="muted" style="margin-top:14px">No findings match these filters.</p>';
    document.querySelectorAll("tr[data-e]").forEach((tr) => (tr.onclick = () => openEvent(+tr.dataset.e, load)));
  };
  $("#igo").onclick = load; load();
}
async function openEvent(id, after) {
  const e = await api(`/events/${id}`);
  const frames = e.evidence.filter((x) => x.kind === "frame"), clips = e.evidence.filter((x) => x.kind === "clip");
  modal(`<div class="row" style="align-items:center"><h2 style="flex:1">${esc(e.category_label)} <small class="muted">#${e.id}</small></h2><button class="btn sm" onclick="closeModal()">Close</button></div>
   <div>${chip(e.automated_status)} ${chip(e.review_status)}</div>
   <dl class="kv" style="margin:12px 0"><dt>Video</dt><dd><a href="#/video/${e.video_id}?t=${Math.floor(e.start_s)}" onclick="closeModal()">${esc(e.video)}</a></dd><dt>Interval</dt><dd>${e.start} – ${e.end}</dd><dt>Tracking ref</dt><dd>${esc(e.track_ref || "not attributed")} <small class="muted">(temporary, not an identity)</small></dd><dt>Predicted class</dt><dd>${esc(e.predicted_class || "—")} <small class="muted">(original AI output, never overwritten by review)</small></dd><dt>Confidence</dt><dd>${e.confidence != null ? e.confidence.toFixed(2) : "not supplied by model"}</dd>${e.reviewed_at ? `<dt>Last review</dt><dd>${esc(e.reviewed_by)} · ${esc(e.reviewed_at.slice(0, 16).replace("T", " "))}</dd>` : ""}<dt>Model</dt><dd>${esc(e.model)}</dd><dt>Summary</dt><dd>${esc(e.summary || "")}</dd></dl>
   ${clips.map((c) => c.file_available ? `<video controls preload="metadata" src="${c.url}" style="margin-bottom:10px"></video>` : '<div class="alert warn">Evidence clip is no longer available (removed or missing).</div>').join("")}
   ${frames.length ? `<div class="imgs">${frames.map((f) => f.file_available ? `<a href="${f.url}" target="_blank"><img src="${f.url}" alt="evidence ${ts(f.timestamp_s)}"></a>` : '<div class="alert warn">Frame file missing</div>').join("")}</div>` : '<p class="muted">No evidence frames stored.</p>'}
   <div class="alert info">This is an AI prediction. Inspect the footage and decide. Confirmation is a human judgement and must precede any action.</div>
   <div class="field"><label>Reviewer notes</label><textarea id="rn" rows="3" maxlength="2000">${esc(e.review_notes || "")}</textarea></div>
   <div class="row"><button class="btn primary" data-d="confirmed">Confirm</button><button class="btn" data-d="dismissed">Dismiss</button><button class="btn" data-d="inconclusive">Inconclusive</button></div>
   ${e.reviews.length ? `<h3 style="margin-top:16px">Review history</h3>${e.reviews.map((r) => `<div class="muted">${esc((r.at || "").slice(0, 16).replace("T", " "))} · ${esc(r.reviewer)} · ${chip(r.decision)} ${esc(r.notes || "")}</div>`).join("")}` : ""}`);
  document.querySelectorAll("#modalbody [data-d]").forEach((b) => (b.onclick = async () => {
    try { await post(`/events/${id}/review`, { decision: b.dataset.d, notes: $("#rn").value || null }); toast("Review saved"); closeModal(); after && after(); } catch (er) { toast(er.message); }
  }));
}
window.closeModal = closeModal;

/* ---------- uniform ---------- */
const hsv2rgb = (h, s, v) => { h = (h * 2) / 360; s /= 255; v /= 255; const f = (n) => { const k = (n + h * 6) % 6; return v - v * s * Math.max(0, Math.min(k, 4 - k, 1)); }; return `rgb(${Math.round(f(5) * 255)},${Math.round(f(3) * 255)},${Math.round(f(1) * 255)})`; };
async function pgUniform() {
  setTitle("Uniform & ID-card compliance");
  const [people, st, refs] = await Promise.all([api("/people"), api("/settings"), api("/reference-images")]);
  const u = st.uniform; const R = (nm, r) => ["h", "s", "v"].map((c) => `<div class="field"><label>${nm} ${c.toUpperCase()} min / max</label><div class="row"><input type="number" data-p="${nm}.${c}_min" value="${r[c + "_min"]}"><input type="number" data-p="${nm}.${c}_max" value="${r[c + "_max"]}"></div></div>`).join("");
  $("#view").innerHTML = `<div class="alert info"><b>How to read this:</b> A colour-range baseline checks shirt (beige) and trousers (navy) separately. “Uncertain” / “Not assessed” are <b>not</b> violations. “Card not detected” only means the detector did not see a card — it is <b>never proof</b> that no card is worn. College membership is <b>unverified</b>: uniform and ID visibility do not prove it.</div>
  <div class="card"><div class="row"><div class="field"><label>Uniform result</label><select id="fu"><option value="">All</option>${["COMPLIANT", "POSSIBLE_SHIRT_MISMATCH", "POSSIBLE_TROUSER_MISMATCH", "POSSIBLE_UNIFORM_MISMATCH", "UNCERTAIN", "NOT_ASSESSED"].map((s) => `<option value="${s}">${LBL[s]}</option>`).join("")}</select></div>
  <div class="field"><label>ID status</label><select id="fi"><option value="">All</option>${["CARD_VISIBLE", "CARD_NOT_DETECTED", "UNCERTAIN", "NOT_ASSESSED"].map((s) => `<option value="${s}">${LBL[s]}</option>`).join("")}</select></div><button class="btn primary" id="fgo">Filter</button></div></div>
  <div id="pl" class="pgrid" style="margin-top:16px"></div>
  <div class="grid g2" style="margin-top:16px"><div class="card"><h3>Uniform reference settings (HSV)</h3><p class="muted">OpenCV HSV: H 0–179, S/V 0–255. Widen ranges for more lighting tolerance. ${ME.role !== "admin" ? "Admin role required to save." : ""}</p>
  <div>Beige <span class="swatch" style="background:${hsv2rgb((u.beige.h_min + u.beige.h_max) / 2, (u.beige.s_min + u.beige.s_max) / 2, (u.beige.v_min + u.beige.v_max) / 2)}"></span> Navy <span class="swatch" style="background:${hsv2rgb((u.navy.h_min + u.navy.h_max) / 2, (u.navy.s_min + u.navy.s_max) / 2, (u.navy.v_min + u.navy.v_max) / 2)}"></span></div>
  <div class="grid g2" style="margin-top:10px"><div>${R("beige", u.beige)}</div><div>${R("navy", u.navy)}</div></div>
  <div class="row"><div class="field"><label>OK fraction</label><input type="number" step="0.01" data-p="ok_fraction" value="${u.ok_fraction}"></div><div class="field"><label>Violation fraction (≤)</label><input type="number" step="0.01" data-p="bad_fraction" value="${u.bad_fraction}"></div><div class="field"><label>Min person height (px)</label><input type="number" data-p="min_person_height_px" value="${u.min_person_height_px}"></div></div>
  <button class="btn primary" id="usave">Save (applies to new analyses)</button></div>
  <div class="card"><h3>Reference images</h3><p class="muted">Place approved reference photos in <code>reference_images/</code> or upload below. Avoid images showing personal ID details; crop or blur names/photos. They are for documentation and calibration — two photos are not a training set.</p>
  ${refs.length ? `<ul>${refs.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : '<p class="muted">No reference images stored.</p>'}<input type="file" id="rf" accept=".jpg,.jpeg,.png"><button class="btn" id="rup" style="margin-top:8px">Upload reference image</button></div></div>`;
  const draw = (rows) => ($("#pl").innerHTML = rows.length ? rows.map((p) => `<div class="card pcard">
    ${p.evidence[0] && p.evidence[0].file_available ? `<img src="${p.evidence[0].url}" alt="evidence frame for ${esc(p.track_ref)}">` : '<div class="noimg">No evidence frame</div>'}
    <div class="phead"><b>${esc(p.track_ref)}</b><span class="muted">${esc(p.video)}</span><span class="muted">${p.first_seen} – ${p.last_seen}</span></div>
    <div class="chiprow">${chip(p.uniform_overall)}<span class="chip">${esc(LBL[p.uniform_simple] || p.uniform_simple)}</span></div>
    <dl class="kv2">
      <dt>Shirt</dt><dd>${chip(p.shirt_status)}${p.shirt_fraction != null ? `<small class="muted">${Math.round(p.shirt_fraction * 100)}%</small>` : ""}</dd>
      <dt>Trousers</dt><dd>${chip(p.trouser_status)}${p.trouser_fraction != null ? `<small class="muted">${Math.round(p.trouser_fraction * 100)}%</small>` : ""}</dd>
      <dt>ID card</dt><dd>${chip(p.id_status)}${p.id_status === "CARD_NOT_DETECTED" ? '<small class="muted">not proof of absence</small>' : ""}${p.id_confidence != null ? `<small class="muted">conf ${p.id_confidence.toFixed(2)}</small>` : ""}</dd>
      <dt>Membership</dt><dd><span class="chip">Membership unverified</span></dd>
      <dt>Method</dt><dd><small class="muted">${esc(p.uniform_method || "—")} ${esc(p.uniform_version || "")}${p.uniform_score != null ? " · score " + p.uniform_score.toFixed(2) : ""}</small></dd>
      <dt>Samples</dt><dd><small class="muted">${p.uniform_samples} observations</small></dd>
    </dl></div>`).join("") : '<div class="card"><p class="muted">No tracked people yet. Analyse a video first.</p></div>');
  draw(people);
  $("#fgo").onclick = async () => draw(await api("/people" + qs({ uniform: $("#fu").value, id_status: $("#fi").value })));
  $("#usave").onclick = async () => {
    const patch = { uniform: {} };
    document.querySelectorAll("[data-p]").forEach((i) => { const [a, b] = i.dataset.p.split("."); if (b) (patch.uniform[a] ??= {})[b] = +i.value; else patch.uniform[a] = +i.value; });
    try { await api("/settings", { method: "PUT", body: JSON.stringify(patch) }); toast("Saved"); } catch (e) { toast(e.message); }
  };
  $("#rup").onclick = async () => { const f = $("#rf").files[0]; if (!f) return; const fd = new FormData(); fd.append("file", f); try { await api("/reference-images", { method: "POST", body: fd }); toast("Uploaded"); pgUniform(); } catch (e) { toast(e.message); } };
}

/* ---------- reports ---------- */
async function pgReports() {
  setTitle("Reports & analytics");
  const vids = await api("/videos?limit=200");
  $("#view").innerHTML = `<div class="card"><div class="row"><div class="field"><label>From</label><input type="date" id="r1"></div><div class="field"><label>To</label><input type="date" id="r2"></div>
  <div class="field"><label>Video</label><select id="rv"><option value="">All</option>${vids.items.map((v) => `<option value="${v.id}">${esc(v.filename)}</option>`).join("")}</select></div>
  <div class="field"><label>Category</label><select id="rc"><option value="">All</option>${Object.entries(CAT).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div>
  <div class="field"><label>Review status</label><select id="rs"><option value="">All</option>${["pending_review", "confirmed", "dismissed", "inconclusive"].map((s) => `<option value="${s}">${LBL[s]}</option>`).join("")}</select></div>
  <label style="flex:0 0 auto;display:flex;gap:6px;align-items:center"><input type="checkbox" id="rh" style="width:auto"> include earlier runs</label><button class="btn primary" id="rgo">Apply</button></div><div class="row" style="margin-top:8px"><a class="btn" id="pdf" href="#">Download PDF</a><a class="btn" id="csv" href="#">Download CSV</a><a class="btn" id="ccsv" href="#" title="One row per tracked person (uniform + ID-card compliance)">Download compliance CSV (people)</a></div></div><div id="rb"></div>`;
  const F = () => qs({ date_from: $("#r1").value, date_to: $("#r2").value, video_id: $("#rv").value, category: $("#rc").value, review_status: $("#rs").value, include_history: $("#rh").checked ? "true" : "" });
  const load = async () => {
    const s = await api("/reports/summary" + F());
    $("#pdf").href = "/api/reports/report.pdf" + F(); $("#csv").href = "/api/reports/events.csv" + F();
    $("#ccsv").href = "/api/reports/compliance.csv" + qs({ video_id: $("#rv").value, include_history: $("#rh").checked ? "true" : "" });
    const kv = (o) => Object.keys(o).length ? Object.entries(o).map(([k, v]) => `<tr><td>${chip(k)}</td><td>${v}</td></tr>`).join("") : '<tr><td class="muted">No data</td></tr>';
    $("#rb").innerHTML = (s.coverage_warning ? `<div class="alert warn" style="margin-top:16px"><b>Coverage:</b> ${esc(s.coverage_warning)}</div>` : "") + `<div class="alert info" style="margin-top:16px">${s.total_events} finding(s) · <b>${s.confirmed} confirmed</b> · ${s.dismissed} dismissed. Only human-confirmed events count as incidents.</div>
    <div class="grid g2"><div class="card"><h3>Findings by category</h3><div id="g1"></div></div><div class="card"><h3>Review-status distribution</h3><div id="g2"></div></div>
    <div class="card"><h3>Findings over time</h3><div id="g3"></div></div><div class="card"><h3>Confirmed vs dismissed</h3><div id="g4"></div></div>
    <div class="card"><h3>Uniform summary (tracked people)</h3><table>${kv(s.uniform)}</table><p class="muted">Simplified: ${Object.entries(s.uniform_simple || {}).map(([k, v]) => `${esc(LBL[k] || k)} ${v}`).join(" · ") || "no data"}</p></div><div class="card"><h3>ID-card detection summary</h3><table>${kv(s.id_card)}</table><p class="muted">“ID not detected” ≠ “no ID worn”.</p></div>
    <div class="card"><h3>Module coverage</h3>${Object.keys(s.modules || {}).length ? `<table><tr><th>Module</th><th>Ran</th><th>Not run</th></tr>${Object.entries(s.modules).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v.ran}</td><td>${v.not_run ? `<b>${v.not_run}</b>` : 0}</td></tr>`).join("")}</table>` : '<p class="muted">No completed analyses in this selection.</p>'}</div>
    <div class="card"><h3>Processing performance</h3><dl class="kv"><dt>Completed jobs</dt><dd>${s.processing.completed_jobs}</dd><dt>Failed jobs</dt><dd>${s.processing.failed_jobs}</dd><dt>Cancelled</dt><dd>${s.processing.cancelled_jobs}</dd><dt>Avg time</dt><dd>${s.processing.avg_seconds_per_footage_minute ?? "n/a"} s per footage-minute (this machine)</dd></dl></div></div>`;
    chart($("#g1"), "doughnut", Object.keys(s.by_category).map((k) => CAT[k] || k), Object.values(s.by_category));
    chart($("#g2"), "bar", Object.keys(s.by_review_status).map((k) => LBL[k]), Object.values(s.by_review_status), ["#F59E0B", "#F0506E", "#14B8A6", "#8B5CF6"]);
    chart($("#g3"), "bar", Object.keys(s.events_per_day), Object.values(s.events_per_day));
    chart($("#g4"), "bar", ["Confirmed", "Dismissed"], [s.confirmed, s.dismissed], ["#F0506E", "#14B8A6"]);
  };
  $("#rgo").onclick = load; load();
}

/* ---------- settings ---------- */
function flat(o, p = "") { return Object.entries(o).flatMap(([k, v]) => (v && typeof v === "object" ? flat(v, p + k + ".") : [[p + k, v]])); }
async function pgSettings() {
  setTitle("Settings & system status");
  const [s, st, ev] = await Promise.all([api("/system/status"), api("/settings"), api("/system/evaluations")]);
  const isA = ME.role === "admin";
  const badge = (x) => chip(x === true ? "ok" : x === false ? "failed" : x);
  $("#view").innerHTML = `${s.model_warnings.length ? `<div class="alert warn">${s.model_warnings.map(esc).join("<br>")}</div>` : '<div class="alert good">All requested models are loaded.</div>'}
  <div class="card" style="margin-bottom:16px"><h3>Model registry</h3><div class="tw"><table><tr><th>Module</th><th>State</th><th>Evaluation</th><th>Name / version</th><th>Detail</th></tr>${s.models.map((m) => `<tr><td>${esc(m.title)}${m.active ? "" : ' <small class="muted">(not in use)</small>'}</td><td>${chip(m.state)}</td><td>${chip(m.evaluation.state)}${m.evaluation.f1 != null ? ` <small>F1 ${m.evaluation.f1.toFixed(2)}</small>` : ""}</td><td>${esc(m.name || "—")} ${esc(m.version || "")}</td><td class="muted">${esc(m.detail || "")}</td></tr>`).join("")}</table></div>
  <p class="muted">“Not evaluated” = no labelled evaluation has been recorded; predictions of that module are unvalidated. Membership verification: ${esc(s.membership_verification.displayed_as)}.</p></div>
  <div class="grid g2"><div class="card"><h3>Device & environment</h3><dl class="kv"><dt>App / schema</dt><dd>${esc(s.app_version)} / v${esc(s.schema_version)}</dd><dt>Python</dt><dd>${esc(s.python)}</dd><dt>OpenCV</dt><dd>${esc(s.opencv)}</dd><dt>PyTorch</dt><dd>${s.torch.installed ? esc(s.torch.version) + " · " + esc(s.torch.device_name) : "not installed"}</dd><dt>CUDA GPU</dt><dd>${s.torch.cuda ? "available" : "not available (CPU inference)"}</dd><dt>FFmpeg</dt><dd>${s.ffmpeg ? "found" : "not found (needed for AVI/MOV preview &amp; browser-playable clips)"}</dd></dl></div>
  <div class="card"><h3>Storage & backup</h3><dl class="kv"><dt>Videos</dt><dd>${s.storage.videos_mb} MB</dd><dt>Evidence</dt><dd>${s.storage.evidence_mb} MB</dd><dt>Backups</dt><dd>${s.storage.backups_mb} MB</dd><dt>Disk free</dt><dd>${s.storage.disk_free_gb} GB</dd></dl><p class="muted">${esc(s.backup_instructions)}</p>${isA ? '<div class="row"><button class="btn" id="bk">Create backup now</button><button class="btn" id="bv">Validate latest backup</button><button class="btn" id="ret">Run retention cleanup</button></div>' : ""}</div>
  <div class="card"><h3>Model evaluation results</h3>${ev.length ? `<div class="tw"><table><tr><th>Model</th><th>Dataset</th><th>P</th><th>R</th><th>F1</th><th>Notes</th></tr>${ev.map((e) => `<tr><td>${esc(e.model)} ${esc(e.model_version)}</td><td>${esc(e.dataset)} ${esc(e.dataset_version)}</td><td>${e.precision ?? "—"}</td><td>${e.recall ?? "—"}</td><td>${e.f1 ?? "—"}</td><td>${esc(e.notes || "")}</td></tr>`).join("")}</table></div>` : '<div class="alert warn">No labelled evaluation has been recorded. Accuracy is unknown until you run <code>python scripts/evaluate.py</code> on labelled test data.</div>'}</div></div>
  <div class="card" style="margin-top:16px"><h3>Configuration</h3><p class="muted">Confidence thresholds, sampling, tracking, retention. ${isA ? "" : "Admin role required to save."}</p><div id="sf" class="grid g4"></div><button class="btn primary" id="ssave" style="margin-top:12px" ${isA ? "" : "disabled"}>Save settings</button></div>`;
  $("#sf").innerHTML = flat(st).filter(([k]) => !k.startsWith("uniform.beige") && !k.startsWith("uniform.navy")).map(([k, v]) => `<div class="field"><label>${esc(k)}</label>${typeof v === "boolean" ? `<select data-k="${esc(k)}" data-t="b"><option ${v ? "selected" : ""}>true</option><option ${!v ? "selected" : ""}>false</option></select>` : `<input data-k="${esc(k)}" data-t="${typeof v === "number" ? "n" : "s"}" value="${esc(v)}">`}</div>`).join("");
  $("#ssave").onclick = async () => {
    const patch = {};
    document.querySelectorAll("#sf [data-k]").forEach((i) => { const ks = i.dataset.k.split("."); let o = patch; ks.slice(0, -1).forEach((k) => (o = o[k] ??= {})); o[ks.at(-1)] = i.dataset.t === "n" ? +i.value : i.dataset.t === "b" ? i.value === "true" : i.value; });
    try { await api("/settings", { method: "PUT", body: JSON.stringify(patch) }); toast("Settings saved"); } catch (e) { toast(e.message); }
  };
  if (isA) { const di = await api("/system/db"); $("#view").insertAdjacentHTML("beforeend", `<div class="card" style="margin-top:16px"><h3>Database in use</h3><dl class="kv"><dt>File</dt><dd>${esc(di.path)}</dd><dt>Size / schema</dt><dd>${di.size_mb} MB · schema v${di.schema_version}</dd><dt>Integrity</dt><dd>${di.foreign_key_violations === 0 ? "no foreign-key violations" : esc(di.foreign_key_violations) + " violation(s)"}</dd><dt>Other .db files</dt><dd>${di.other_database_files.length ? esc(di.other_database_files.join(", ")) + " (check: a second database may exist)" : "none found"}</dd><dt>Row counts</dt><dd>${Object.entries(di.tables).map(([k, v]) => `${esc(k)} ${v}`).join(" · ")}</dd></dl></div>`); }
  if (isA) { $("#bv").onclick = async () => { const l = await api("/system/backups"); if (!l.length) return toast("No backups yet"); const r = await post("/system/backups/validate", { name: l[0] }); toast(r.ok ? `Backup OK (${l[0]})` : "Backup INVALID: " + r.errors.join("; ")); }; $("#bk").onclick = async () => toast("Backup created: " + (await post("/system/backup")).file); $("#ret").onclick = async () => toast(JSON.stringify(await post("/system/retention/run"))); }
}
/* ====================================================================================================
   VIDEO COMPLIANCE ALERTS, PERSON REVIEW, IN-APP NOTIFICATIONS  (v1.3)
   All numbers come from GET /api/videos/{id}/compliance-summary and /compliance-people (stored results).
   ==================================================================================================== */
Object.assign(LBL, {
  needs_manual_check: "Manual check recommended", not_applicable: "—",
  both: "Both issues", uniform_only: "Uniform issue only", id_only: "ID card not detected only", compliant_both: "Apparently compliant",
  not_assessed: "Not assessed",
});
ICON.warn = '<path d="M12 3l10 18H2zM12 10v5M12 18h.01"/>';
ICON.people = '<circle cx="9" cy="8" r="3.2"/><path d="M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5M16 5.2a3.2 3.2 0 0 1 0 5.6M18.5 14.8c1.7.7 2.8 2.3 3 5.2"/>';
ICON.idc = '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="11" r="2"/><path d="M6 16c.5-1.5 1.7-2 3-2s2.5.5 3 2M15 10h3M15 13h3M3 3l18 18"/>';
ICON.two = '<path d="M12 3l10 18H2zM12 10v5M12 18h.01"/><path d="M5 5l14 14" />';
ICON.ok = '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/>';
ICON.q = '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17h.01"/>';
const svg = (k) => `<svg viewBox="0 0 24 24">${ICON[k]}</svg>`;
const ID_UNRELIABLE_TXT = "ID-card visibility could not be reliably verified for some people. Please review the evidence manually.";
const TERMINAL = ["completed", "completed_partial", "failed", "cancelled"];
let PAGE = "", CUR_VIDEO = null;

function plural(n, one, many) { return `${n} ${n === 1 ? one : many}`; }
function animateCount(el, n) {
  if (!el) return;
  const t0 = performance.now(), dur = 600;
  const step = (now) => { const p = Math.min(1, (now - t0) / dur); el.textContent = Math.round(n * (1 - Math.pow(1 - p, 3))); if (p < 1) requestAnimationFrame(step); };
  n > 0 ? requestAnimationFrame(step) : (el.textContent = "0");
}

/* ---------- in-app notifications (toast cards) ---------- */
function goto(hash) {
  if (location.hash === hash) { route(); } else { location.hash = hash; }
  setTimeout(() => { const [, q] = hash.split("?"); if (q && new URLSearchParams(q).get("section") === "compliance") $("#compliance")?.scrollIntoView({ behavior: "smooth", block: "start" }); }, 450);
}
window.goto = goto;
function notify({ level = "info", title, lines = [], link, linkLabel }) {
  const box = $("#notify"); if (!box) return;
  const n = document.createElement("div"); n.className = `notify ${level}`; n.setAttribute("role", "status");
  n.innerHTML = `<button class="x" aria-label="Dismiss">&times;</button><b class="t">${esc(title)}</b>${lines.map((l) => `<p>${esc(l)}</p>`).join("")}${link ? `<a class="lk" href="${esc(link)}">${esc(linkLabel || "Open")}</a>` : ""}`;
  const close = () => { n.classList.add("out"); setTimeout(() => n.remove(), 320); };
  $(".x", n).onclick = close;
  const a = $(".lk", n); if (a) a.onclick = (e) => { e.preventDefault(); goto(link); close(); };
  box.appendChild(n);
  while (box.children.length > 4) box.firstChild.remove();
  setTimeout(close, 22000);
}
function browserNotify(title, body, hash) {
  try {
    if (!("Notification" in window) || Notification.permission !== "granted" || localStorage.getItem("cg_browser_notify") !== "1") return;
    const n = new Notification(title, { body }); n.onclick = () => { window.focus(); goto(hash); n.close(); };
  } catch (e) { /* optional feature: never break the app */ }
}
async function enableBrowserNotifications() {   // only ever called from a click handler (explicit user action)
  if (!("Notification" in window)) return toast("This browser does not support desktop notifications");
  const r = await Notification.requestPermission();
  try { localStorage.setItem("cg_browser_notify", r === "granted" ? "1" : "0"); } catch (e) {}
  toast(r === "granted" ? "Desktop notifications enabled" : "Desktop notifications not enabled");
  if (PAGE === "dashboard") pgDashboard().catch(() => {});
}
const canAskBrowserNotify = () => "Notification" in window && Notification.permission === "default";

/* ---------- transition detector (pure: easy to test) ----------
   A notification fires ONLY when a job is seen moving from queued/running to a finished state (or a job created after
   this page loaded is first seen already finished). The first poll after page load is a silent baseline, so a refresh or
   page navigation never replays old completions; `notified` is also kept in sessionStorage. */
function detectTransitions(state, jobs) {
  const out = [];
  if (state.seen === null) {
    state.seen = new Map(jobs.map((j) => [j.id, j.status]));
    state.baseMax = jobs.reduce((m, j) => Math.max(m, j.id), 0);
    return out;
  }
  for (const j of jobs) {
    const prev = state.seen.get(j.id);
    const wasActive = prev === "queued" || prev === "running";
    const createdAfterLoad = prev === undefined && j.id > state.baseMax;
    if (TERMINAL.includes(j.status) && (wasActive || createdAfterLoad) && !state.notified.has(j.id)) { out.push(j); state.notified.add(j.id); }
    state.seen.set(j.id, j.status);
  }
  return out;
}
function loadNotified() { try { return new Set(JSON.parse(sessionStorage.getItem("cg_notified") || "[]")); } catch (e) { return new Set(); } }
function saveNotified(s) { try { sessionStorage.setItem("cg_notified", JSON.stringify([...s].slice(-200))); } catch (e) {} }
const WATCH = { seen: null, baseMax: 0, notified: loadNotified(), timer: null, busy: false };
async function watchTick() {
  if (WATCH.busy || document.hidden || !ME) return;
  WATCH.busy = true;
  try {
    const jobs = await api("/jobs?limit=30");
    const done = detectTransitions(WATCH, jobs);
    if (done.length) saveNotified(WATCH.notified);
    for (const j of done) await onJobFinished(j);
  } catch (e) { /* offline / signed out: try again next tick */ } finally { WATCH.busy = false; }
}
function startWatcher() { stopWatcher(); WATCH.seen = null; WATCH.timer = setInterval(watchTick, 4000); watchTick(); }
function stopWatcher() { clearInterval(WATCH.timer); WATCH.timer = null; WATCH.seen = null; }
async function onJobFinished(job) {
  const name = job.video_name || `video #${job.video_id}`, hash = `#/video/${job.video_id}?section=compliance`;
  if (job.status === "failed") {
    notify({ level: "error", title: "VIDEO ANALYSIS FAILED", lines: [name, job.error || "The analysis could not be completed."], link: `#/video/${job.video_id}`, linkLabel: "Open video \u2192" });
  } else if (job.status === "cancelled") {
    notify({ level: "info", title: "VIDEO ANALYSIS CANCELLED", lines: [name, "No compliance results were produced by this run."], link: `#/video/${job.video_id}`, linkLabel: "Open video \u2192" });
  } else {
    try {
      const s = await api(`/videos/${job.video_id}/compliance-summary?job_id=${job.id}`);   // real numbers from the database
      const nt = s.notification || { title: "VIDEO ANALYSIS COMPLETED", lines: [] };
      notify({ level: s.alert.level, title: nt.title, lines: [name, ...nt.lines], link: hash, linkLabel: nt.link_label || "Open compliance report \u2192" });
      browserNotify(nt.title, [name, ...nt.lines].join("\n"), hash);
    } catch (e) {
      notify({ level: "info", title: "VIDEO ANALYSIS COMPLETED", lines: [name, "Compliance summary could not be loaded."], link: hash, linkLabel: "Open video \u2192" });
    }
  }
  // refresh whatever the user is looking at
  if (PAGE === "video" && CUR_VIDEO && CUR_VIDEO.id === job.video_id) CUR_VIDEO.refresh().catch(() => {});
  else if (PAGE === "dashboard") pgDashboard().catch(() => {});
}

/* ---------- compliance panel on the video page ---------- */
const CMP = { filter: "all" };
const FILTERS = [["all", "All people", "total_people"], ["uniform_issue", "Possible uniform non-compliance", "uniform_non_compliant"], ["id_issue", "ID card not detected", "id_not_detected"],
  ["both", "Both issues", "both_issues"], ["compliant", "Apparently compliant", "compliant_both"], ["uncertain", "Uncertain", "uncertain"], ["not_assessed", "Not assessed", "not_assessed"]];
function cgCard(key, icon, color, label, n, cap, cls = "") {
  return `<div class="cg-card ${cls}" style="--c:${color}" id="cgc-${key}">${svg(icon)}<div class="lbl">${esc(label)}</div><div class="num" data-n="${n}">0</div><div class="cap">${cap}</div></div>`;
}
function splitBar(s) {
  const parts = [["uniform_only", "Uniform issue only", "#8B5CF6"], ["id_only", "ID-card issue only", "#F59E0B"], ["both_issues", "Both issues", "#F0506E"],
    ["compliant_both", "Apparently compliant", "#14B8A6"], ["uncertain", "Uncertain", "#94A3B8"], ["not_assessed", "Not assessed", "#CBD5E1"]];
  const tot = s.total_people || 1;
  return `<div class="cg-split" role="img" aria-label="Mutually exclusive breakdown of tracked people">${parts.map(([k, l, c]) => `<i style="width:${(s[k] / tot) * 100}%;background:${c}" title="${esc(l)}: ${s[k]}"></i>`).join("")}</div>
    <div class="cg-legend">${parts.map(([k, l, c]) => `<span style="--c:${c}">${esc(l)} <b>${s[k]}</b></span>`).join("")}</div>
    <p class="cg-note">Each tracked person is in exactly one of these six groups (they add up to ${s.total_people}). The uniform and ID-card cards above overlap by the “both issues” group.</p>`;
}
function bannerHtml(s) {
  const ic = { attention: "warn", caution: "q", clear: "ok", none: "q" }[s.alert.level] || "q";
  const flagged = s.uniform_non_compliant || s.id_not_detected;
  return `<div class="cg-banner ${esc(s.alert.level)}" role="alert">${svg(ic)}<div><h3>${esc(s.alert.title)}</h3><p>${esc(s.alert.message)}</p>
    <div class="row" style="margin-top:10px;align-items:center">${s.total_people ? `<button class="btn ${flagged ? "primary" : ""} sm" id="cg-review">${flagged ? "Review flagged people" : "Review people"}</button>` : ""}
    <a class="btn sm" href="/api/reports/compliance.csv?job_id=${s.job_id}" id="cg-csv">Download people CSV</a>${canAskBrowserNotify() ? '<button class="btn ghost sm" id="cg-bn">Enable desktop notifications</button>' : ""}</div></div></div>`;
}
async function renderCompliance(vid, force) {
  const box = $("#compliance"); if (!box) return;
  let s;
  try { s = await api(`/videos/${vid}/compliance-summary`); } catch (e) { box.innerHTML = `<div class="alert err">${esc(e.message)}</div>`; return; }
  const key = [s.job_id, s.status, s.available, s.total_people, s.finished_at, s.newer_job && s.newer_job.status].join("|");
  if (!force && box.dataset.key === key) return;            // nothing changed: do not redraw (keeps filter/scroll while polling)
  box.dataset.key = key;
  const head = `<div class="cg-head"><h2>${svg("warn")} Video compliance alerts</h2><span class="sp"></span>${s.available ? `<span class="chip ${s.is_current ? "loaded" : ""}">${s.is_current ? "current run" : "earlier run"} · job #${s.job_id}${s.partial ? " · partial" : ""}</span>` : ""}</div>`;
  if (!s.available) { box.innerHTML = `<div class="card cg-section">${head}<div class="alert info" style="margin:0">${esc(s.message)}</div></div>`; return; }
  box.innerHTML = `<div class="card cg-section">${head}
    <div class="cg-cards">
      ${cgCard("total", "people", "var(--blue)", "Total people tracked", s.total_people, "unique tracked people in this analysis")}
      ${cgCard("uni", "shirt", "#8B5CF6", "Uniform non-compliance", s.uniform_non_compliant, "people with a possible shirt, trouser or full mismatch")}
      ${cgCard("id", "idc", "#F59E0B", "ID card not detected", s.id_not_detected, "detector returned “card not detected” — not proof that no card is worn")}
      ${cgCard("both", "two", "#F0506E", "Both issues", s.both_issues, "overlapping subset of the two cards before — <b>not</b> additional people", "overlap")}
      ${cgCard("ok", "ok", "#14B8A6", "Apparently compliant", s.compliant_both, "both checks conclusive and compliant")}
      ${cgCard("unc", "q", "#64748B", "Uncertain / not assessed", s.inconclusive, `${s.uncertain} uncertain · ${s.not_assessed} not assessed — never counted as compliant`)}
    </div>
    ${splitBar(s)}
    ${bannerHtml(s)}
    <div class="cg-warns">${s.warnings.map((w) => `<div class="alert ${w.level === "warn" ? "warn" : w.level === "error" ? "err" : "info"}">${esc(w.message)}</div>`).join("")}</div>
    <details><summary>Methods and limitations</summary><ul>${s.limitations.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>
      <p class="muted">Modules in this run: ${s.modules.map((m) => `${esc(m.module)} ${m.ran ? "ran" : (m.requested ? "did NOT run (" + esc(m.state) + ")" : "disabled")}`).join(" · ") || "no per-module record (older analysis)"}</p></details>
    <h3 style="margin-top:18px">Person-wise review</h3>
    <div class="cg-filters" id="cg-filters">${FILTERS.map(([k, l, f]) => `<button data-f="${k}" class="${CMP.filter === k ? "on" : ""}">${esc(l)}<small>${s[f]}</small></button>`).join("")}</div>
    <div id="cg-people"></div>
    <p class="cg-note">Tracking references (T1, T2, …) are temporary labels for this video only — not identities. No face recognition is used.</p></div>`;
  box.querySelectorAll(".cg-card .num").forEach((el) => animateCount(el, +el.dataset.n));
  box.querySelectorAll("#cg-filters button").forEach((b) => (b.onclick = () => { CMP.filter = b.dataset.f; box.querySelectorAll("#cg-filters button").forEach((x) => x.classList.toggle("on", x === b)); loadPeople(vid, s.job_id); }));
  const rv = $("#cg-review", box);
  if (rv) rv.onclick = () => { CMP.filter = s.uniform_non_compliant ? "uniform_issue" : s.id_not_detected ? "id_issue" : s.uncertain ? "uncertain" : "all";
    box.querySelectorAll("#cg-filters button").forEach((x) => x.classList.toggle("on", x.dataset.f === CMP.filter)); loadPeople(vid, s.job_id); $("#cg-people", box).scrollIntoView({ behavior: "smooth", block: "center" }); };
  const bn = $("#cg-bn", box); if (bn) bn.onclick = enableBrowserNotifications;
  loadPeople(vid, s.job_id);
}
function jumpTo(t) { const pl = $("#pl"); if (!pl) return; closeModal(); pl.currentTime = +t || 0; pl.scrollIntoView({ behavior: "smooth", block: "center" }); pl.play().catch(() => {}); }
window.cgJump = jumpTo;
async function loadPeople(vid, jobId) {
  const el = $("#cg-people"); if (!el) return;
  let r;
  try { r = await api(`/videos/${vid}/compliance-people?job_id=${jobId}&filter=${encodeURIComponent(CMP.filter)}`); } catch (e) { el.innerHTML = `<div class="alert err">${esc(e.message)}</div>`; return; }
  if (!r.items.length) { el.innerHTML = '<p class="muted">No people in this group.</p>'; return; }
  el.innerHTML = `<div class="tw"><table><tr><th>Ref</th><th>Evidence</th><th>First seen</th><th>Last seen</th><th>Shirt</th><th>Trousers</th><th>Uniform</th><th>ID card</th><th>Method</th><th>Obs.</th><th>Review</th></tr>
    ${r.items.map((p) => `<tr class="click" data-p="${p.person_id}"><td><b>${esc(p.track_ref)}</b></td>
      <td>${p.evidence && p.evidence.file_available ? `<img class="cg-thumb" loading="lazy" src="${p.evidence.url}" alt="evidence ${esc(p.track_ref)}">` : '<div class="cg-thumb none">no image</div>'}</td>
      <td>${p.first_seen}</td><td>${p.last_seen}</td><td>${chip(p.shirt_status)}</td><td>${chip(p.trouser_status)}</td><td>${chip(p.uniform_overall)}</td>
      <td>${chip(p.id_status)}${p.id_status === "CARD_NOT_DETECTED" ? '<br><small class="muted">not proof of absence</small>' : ""}</td>
      <td><small class="muted">${esc(p.uniform_method || "—")}<br>${esc(p.id_method || "—")}</small></td><td>${p.observations}</td><td>${chip(p.review_status)}</td></tr>`).join("")}</table></div>
    <p class="cg-note">${r.items.length} ${r.items.length === 1 ? "person" : "people"} shown. Click a row for the evidence image and video timestamp.</p>`;
  const byId = Object.fromEntries(r.items.map((p) => [p.person_id, p]));
  el.querySelectorAll("tr[data-p]").forEach((tr) => (tr.onclick = () => openPerson(byId[tr.dataset.p])));
}
function openPerson(p) {
  const ev = p.evidence;
  modal(`<div class="row" style="align-items:center"><h2 style="flex:1">${esc(p.track_ref)} <small class="muted">temporary tracking reference</small></h2><button class="btn sm" onclick="closeModal()">Close</button></div>
    <div class="chiprow">${chip(p.uniform_overall)} ${chip(p.id_status)} <span class="chip">${esc(p.category_label)}</span></div>
    ${ev && ev.file_available ? `<div style="margin:12px 0"><a href="${ev.url}" target="_blank"><img src="${ev.url}" alt="evidence" style="width:100%;max-height:60vh;object-fit:contain;border-radius:10px;background:#000"></a><p class="muted">Evidence frame at ${esc(ev.time)} (annotated with this person's box).</p></div>` : '<div class="alert warn">No evidence image is available for this person (not stored, or removed).</div>'}
    <dl class="kv"><dt>First / last seen</dt><dd>${p.first_seen} – ${p.last_seen}</dd><dt>Shirt</dt><dd>${chip(p.shirt_status)}</dd><dt>Trousers</dt><dd>${chip(p.trouser_status)}</dd>
    <dt>ID card</dt><dd>${chip(p.id_status)} ${p.id_confidence != null ? `<small class="muted">conf ${p.id_confidence.toFixed(2)}</small>` : ""}</dd><dt>Methods</dt><dd>${esc(p.uniform_method || "—")} · ${esc(p.id_method || "—")}</dd>
    <dt>Observations</dt><dd>${p.observations} detections · ${p.uniform_samples} uniform samples · ${p.id_samples} ID samples</dd><dt>Review</dt><dd>${chip(p.review_status)}${p.event_id ? ` <a href="#" id="cg-ev">Open review item #${p.event_id}</a>` : ""}</dd></dl>
    <div class="row" style="margin-top:12px"><button class="btn primary" onclick="cgJump(${p.jump_to_s})">Jump to ${ts(p.jump_to_s)} in the video</button></div>
    <div class="alert info">Automated colour/visibility check only. A human must verify before any action. “Card not detected” is never proof that no ID card is worn.</div>`);
  const a = $("#cg-ev"); if (a) a.onclick = (e) => { e.preventDefault(); openEvent(p.event_id, () => CUR_VIDEO && CUR_VIDEO.refresh()); };
}

/* ---------- dashboard compliance overview ---------- */
function complianceOverviewHtml(co) {
  if (!co) return "";
  const L = co.latest;
  const mini = (n, l, c) => `<div style="--c:${c}"><b>${n}</b><span>${esc(l)}</span></div>`;
  const body = L ? `<p style="margin:0 0 6px"><b>Latest completed analysis:</b> <a href="#/video/${L.video_id}?section=compliance">${esc(L.video_filename)}</a> <span class="muted">· job #${L.job_id} · ${chip(L.status)} · ${esc((L.finished_at || "").slice(0, 16).replace("T", " "))}</span></p>
    <div class="cg-mini">${mini(L.total_people, "People tracked", "var(--blue)")}${mini(L.uniform_non_compliant, "Possible uniform mismatch", "#8B5CF6")}${mini(L.id_not_detected, "ID card not detected", "#F59E0B")}${mini(L.both_issues, "Both issues", "#F0506E")}${mini(L.pending_reviews, "Pending manual reviews", "var(--amber)")}${mini(co.partial_analyses, "Partial analyses", "var(--cyan)")}</div>
    <div class="cg-banner ${esc(L.alert_level)}" style="margin:8px 0">${svg(L.alert_level === "attention" ? "warn" : L.alert_level === "clear" ? "ok" : "q")}<div><p>${esc(L.alert_message)}</p></div></div>
    ${!L.id_reliable && L.total_people ? `<div class="alert warn">${esc(ID_UNRELIABLE_TXT)}</div>` : ""}
    ${L.partial ? '<div class="alert warn">This analysis was <b>partial</b>: some requested modules did not run (see the video page).</div>' : ""}`
    : '<p class="muted">No analysis has completed yet. Upload a video to generate compliance results.</p>';
  const al = co.recent_alerts.length ? `<h3 style="margin:14px 0 8px">Recent compliance alerts</h3><div class="tw"><table><tr><th>Video</th><th>Finished</th><th>Uniform</th><th>ID card</th><th>Both</th><th>Pending</th><th>Level</th></tr>
    ${co.recent_alerts.map((a) => `<tr class="click" onclick="goto('#/video/${a.video_id}?section=compliance')"><td>${esc(a.video_filename)}${a.partial ? ' <span class="chip completed_partial">partial</span>' : ""}</td><td>${esc((a.finished_at || "").slice(0, 16).replace("T", " "))}</td><td>${a.uniform_non_compliant}</td><td>${a.id_not_detected}</td><td>${a.both_issues}</td><td>${a.pending_reviews}</td><td>${chip(a.alert_level === "attention" ? "POSSIBLE_VIOLATION" : a.alert_level === "caution" ? "UNCERTAIN" : "COMPLIANT")}</td></tr>`).join("")}</table></div>` : "";
  return `<div class="card cg-section" style="margin-bottom:16px"><div class="cg-head"><h2>${svg("warn")} Compliance overview</h2><span class="sp"></span>${canAskBrowserNotify() ? '<button class="btn ghost sm" id="cg-bn">Enable desktop notifications</button>' : ""}</div>${body}${al}
    <p class="cg-note">Person-level counts from stored analysis results (latest successful run of each video). Predictions need human review.</p></div>`;
}

boot();
