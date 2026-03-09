const state = {
  pollingMs: 500,
  running: false,
  finished: false,
  startTs: null,
  finishTs: null,
  crackTs: null,
  crackMark: null,
  latest: null,
  points: [],
  profiles: [],
  selectedProfileId: null,
  autoFinish: { enabled: true, drop_c: 18, window_sec: 25, min_temp_c: 140 },
  rorEmaAlpha: null,
};

const el = {
  serverStatus: document.getElementById("serverStatus"),
  tempValue: document.getElementById("tempValue"),
  tempRaw: document.getElementById("tempRaw"),
  rorValue: document.getElementById("rorValue"),
  recommendation: document.getElementById("recommendation"),
  sessionClock: document.getElementById("sessionClock"),
  crackClock: document.getElementById("crackClock"),
  weightLoss: document.getElementById("weightLoss"),
  stageName: document.getElementById("stageName"),
  profileSelect: document.getElementById("profileSelect"),
  startBtn: document.getElementById("startBtn"),
  crackBtn: document.getElementById("crackBtn"),
  finishBtn: document.getElementById("finishBtn"),
  resetBtn: document.getElementById("resetBtn"),
  chart: document.getElementById("chart"),
};

const chart = {
  ctx: el.chart.getContext("2d"),
  margin: { left: 58, right: 58, top: 26, bottom: 42 },
};
const fixedTempUpperBoundC = 212 * 1.15;
const defaultTempGuides = [
  { tempC: 205, color: "#265f3d", label: "charge guide (205C)" },
  { tempC: 208, color: "#7e5a11", label: "1st crack guide (208C)" },
  { tempC: 212, color: "#7b2b1f", label: "drop guide (212C)" },
];
let tempGuides = [...defaultTempGuides];

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

function fmtClock(sec) {
  if (!Number.isFinite(sec) || sec < 0) return "--:--";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function estimateWeightLoss(tempC, devSec) {
  if (!Number.isFinite(tempC) || !Number.isFinite(devSec) || devSec < 0) return null;
  const est = 8.0 + (tempC - 150) * 0.037 + devSec * 0.018;
  return clamp(est, 7, 20);
}

function profileById(id) {
  return state.profiles.find((p) => p.id === id) || null;
}

function selectedProfileEndSec() {
  const p = profileById(state.selectedProfileId);
  if (!p || !Array.isArray(p.stages) || p.stages.length === 0) return 0;
  return p.stages.reduce((maxEnd, s) => Math.max(maxEnd, Number(s.end_sec) || 0), 0);
}

function currentStage(sessionSec) {
  if (!Number.isFinite(sessionSec) || !state.selectedProfileId) return null;
  const p = profileById(state.selectedProfileId);
  if (!p) return null;
  return p.stages.find((s) => sessionSec >= s.start_sec && sessionSec < s.end_sec) || null;
}

function computeRor(nowSec) {
  if (state.points.length < 2) return 0;
  const lookback = 30;
  const latest = state.points[state.points.length - 1];
  let anchor = null;
  for (let i = state.points.length - 1; i >= 0; i -= 1) {
    const pt = state.points[i];
    if (latest.tSec - pt.tSec >= lookback) {
      anchor = pt;
      break;
    }
  }
  if (!anchor) anchor = state.points[0];
  const dt = latest.tSec - anchor.tSec;
  if (dt <= 0) return 0;
  const ror = ((latest.tempC - anchor.tempC) / dt) * 60;
  return ror;
}

function updateRecommendation(sessionSec, ror) {
  const stage = currentStage(sessionSec);
  if (!stage) {
    el.stageName.textContent = "Stage: -";
    el.recommendation.textContent = "Select profile and press Start";
    return;
  }
  el.stageName.textContent = `Stage: ${stage.name}`;
  if (ror < stage.ror_min) {
    el.recommendation.textContent = `RoR low (${ror.toFixed(1)}). Increase heat.`;
  } else if (ror > stage.ror_max) {
    el.recommendation.textContent = `RoR high (${ror.toFixed(1)}). Lower heat.`;
  } else {
    el.recommendation.textContent = `RoR on target (${ror.toFixed(1)}).`;
  }
}

function inferCrackTemp() {
  if (!state.crackTs || state.points.length === 0) return null;
  let nearest = state.points[0];
  for (const p of state.points) {
    if (Math.abs(p.ts - state.crackTs) < Math.abs(nearest.ts - state.crackTs)) nearest = p;
  }
  return nearest.tempC;
}

function axisBounds() {
  const temps = state.points.map((p) => p.tempC);
  const rors = state.points.map((p) => p.ror);

  const tMin = temps.length ? Math.min(...temps) : 0;
  const tMax = temps.length ? Math.max(...temps) : 220;
  const rMin = rors.length ? Math.min(...rors) : -5;
  const rMax = rors.length ? Math.max(...rors) : 25;

  const profileEndSec = state.running || state.finished ? selectedProfileEndSec() : 0;
  return {
    xMaxSec: Math.max(600, profileEndSec, state.points.length ? state.points[state.points.length - 1].tSec + 20 : 600),
    tMin: Math.floor(Math.min(0, tMin - 5) / 5) * 5,
    tMax: Math.ceil(Math.max(tMax + 5, fixedTempUpperBoundC) / 5) * 5,
    rMin: Math.floor(Math.min(-5, rMin - 1)),
    rMax: Math.ceil(Math.max(25, rMax + 1)),
  };
}

function drawChart() {
  const ctx = chart.ctx;
  const dpr = window.devicePixelRatio || 1;
  const cssWidth = el.chart.clientWidth;
  const cssHeight = Math.max(320, Math.min(window.innerHeight * 0.62, 650));
  el.chart.width = Math.floor(cssWidth * dpr);
  el.chart.height = Math.floor(cssHeight * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const w = cssWidth;
  const h = cssHeight;
  const m = chart.margin;
  const pw = w - m.left - m.right;
  const ph = h - m.top - m.bottom;

  const b = axisBounds();
  const xToPx = (sec) => m.left + (sec / b.xMaxSec) * pw;
  const tToPx = (v) => m.top + ((b.tMax - v) / (b.tMax - b.tMin || 1)) * ph;
  const rToPx = (v) => m.top + ((b.rMax - v) / (b.rMax - b.rMin || 1)) * ph;

  ctx.clearRect(0, 0, w, h);

  ctx.fillStyle = "#f8fbf8";
  ctx.fillRect(0, 0, w, h);

  ctx.strokeStyle = "rgba(16, 55, 42, 0.15)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i <= 6; i += 1) {
    const y = m.top + (i / 6) * ph;
    ctx.moveTo(m.left, y);
    ctx.lineTo(w - m.right, y);
  }
  for (let i = 0; i <= 10; i += 1) {
    const x = m.left + (i / 10) * pw;
    ctx.moveTo(x, m.top);
    ctx.lineTo(x, h - m.bottom);
  }
  ctx.stroke();

  for (const guide of tempGuides) {
    if (guide.tempC < b.tMin || guide.tempC > b.tMax) continue;
    const y = tToPx(guide.tempC);
    ctx.strokeStyle = guide.color;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 5]);
    ctx.beginPath();
    ctx.moveTo(m.left, y);
    ctx.lineTo(w - m.right, y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = guide.color;
    ctx.fillText(guide.label, m.left + 8, y - 6);
  }

  if (state.running || state.finished) {
    const p = profileById(state.selectedProfileId);
    if (p) {
      ctx.fillStyle = "rgba(31, 111, 158, 0.12)";
      for (const s of p.stages) {
        const x0 = clamp(xToPx(s.start_sec), m.left, w - m.right);
        const x1 = clamp(xToPx(s.end_sec), m.left, w - m.right);
        const y0 = rToPx(s.ror_max);
        const y1 = rToPx(s.ror_min);
        ctx.fillRect(x0, y0, Math.max(0, x1 - x0), Math.max(0, y1 - y0));
      }
    }
  }

  if (state.crackMark) {
    const x = xToPx(state.crackMark.tSec);
    ctx.strokeStyle = "#278a3f";
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    ctx.moveTo(x, m.top);
    ctx.lineTo(x, h - m.bottom);
    ctx.stroke();
    ctx.setLineDash([]);

    if (Number.isFinite(state.crackMark.tempC)) {
      const y = tToPx(state.crackMark.tempC);
      ctx.fillStyle = "#278a3f";
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillText(`1st crack @ ${state.crackMark.tempC}C`, x + 6, y - 6);
    }
  }

  if (state.points.length > 1) {
    ctx.strokeStyle = "#ba3a2f";
    ctx.lineWidth = 2;
    ctx.beginPath();
    state.points.forEach((p, idx) => {
      const x = xToPx(p.tSec);
      const y = tToPx(p.tempC);
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    ctx.strokeStyle = "#1f6f9e";
    ctx.lineWidth = 2;
    ctx.setLineDash([7, 4]);
    ctx.beginPath();
    state.points.forEach((p, idx) => {
      const x = xToPx(p.tSec);
      const y = rToPx(p.ror);
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.setLineDash([]);
  }

  ctx.strokeStyle = "#153127";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(m.left, h - m.bottom);
  ctx.lineTo(w - m.right, h - m.bottom);
  ctx.moveTo(m.left, m.top);
  ctx.lineTo(m.left, h - m.bottom);
  ctx.moveTo(w - m.right, m.top);
  ctx.lineTo(w - m.right, h - m.bottom);
  ctx.stroke();

  ctx.fillStyle = "#153127";
  ctx.font = "12px Trebuchet MS";
  for (let i = 0; i <= 6; i += 1) {
    const y = m.top + (i / 6) * ph;
    const tv = b.tMax - (i / 6) * (b.tMax - b.tMin);
    const rv = b.rMax - (i / 6) * (b.rMax - b.rMin);
    ctx.fillText(tv.toFixed(0), 8, y + 4);
    const txt = rv.toFixed(0);
    ctx.fillText(txt, w - m.right + 12, y + 4);
  }

  for (let i = 0; i <= 10; i += 1) {
    const x = m.left + (i / 10) * pw;
    const min = ((i / 10) * b.xMaxSec) / 60;
    ctx.fillText(min.toFixed(1), x - 10, h - m.bottom + 18);
  }

  ctx.fillStyle = "#ba3a2f";
  ctx.fillText("Temp (C)", 8, m.top - 6);
  ctx.fillStyle = "#1f6f9e";
  ctx.fillText("RoR (C/min)", w - m.right + 6, m.top - 6);
  ctx.fillStyle = "#153127";
  ctx.fillText("Time (min)", w / 2 - 24, h - 8);
}

function updateClocks(nowTs) {
  if (state.startTs && (state.running || state.finished)) {
    const endTs = state.finished ? state.finishTs : nowTs;
    const elapsed = (endTs - state.startTs) / 1000;
    el.sessionClock.textContent = fmtClock(elapsed);
  } else {
    el.sessionClock.textContent = "00:00";
  }

  if (state.crackTs && (state.running || state.finished)) {
    const endTs = state.finished ? state.finishTs : nowTs;
    const elapsed = Math.max(0, (endTs - state.crackTs) / 1000);
    el.crackClock.textContent = fmtClock(elapsed);
    const wl = estimateWeightLoss(state.latest?.adjusted_c, elapsed);
    el.weightLoss.textContent = wl ? `WL est: ${wl.toFixed(1)}%` : "WL est: --%";
  } else {
    el.crackClock.textContent = "--:--";
    el.weightLoss.textContent = "WL est: --%";
  }
}

function updateControls() {
  el.startBtn.disabled = state.running;
  el.crackBtn.disabled = !state.running || Boolean(state.crackTs);
  el.finishBtn.disabled = !state.running;
  el.profileSelect.disabled = state.running;
}

function autoFinishCheck() {
  if (!state.running || !state.autoFinish?.enabled || state.points.length < 6) return;

  const latest = state.points[state.points.length - 1];
  if (latest.tempC < (state.autoFinish.min_temp_c || 120)) return;

  const windowSec = state.autoFinish.window_sec || 20;
  const dropC = state.autoFinish.drop_c || 18;
  const cutoff = latest.tSec - windowSec;

  let peak = -Infinity;
  for (const p of state.points) {
    if (p.tSec >= cutoff) {
      peak = Math.max(peak, p.tempC);
    }
  }

  if (Number.isFinite(peak) && peak - latest.tempC >= dropC) {
    finishSession("auto");
  }
}

async function readTemperature() {
  const r = await fetch("/api/temperature");
  const data = await r.json();
  if (!data.ok) throw new Error(data.error || "sensor error");
  return data;
}

function pushPoint(data) {
  const nowTs = Date.parse(data.timestamp) || Date.now();
  if (!state.startTs) state.startTs = nowTs;
  const tSec = (nowTs - state.startTs) / 1000;
  state.latest = data;

  const point = {
    ts: nowTs,
    tSec,
    tempC: data.adjusted_c,
    rawC: data.raw_c,
    ror: 0,
  };
  state.points.push(point);
  const serverRor = Number(data.ror_c_per_min);
  const ror = Number.isFinite(serverRor) ? serverRor : computeRor(tSec);
  point.ror = ror;

  el.tempValue.textContent = data.adjusted_c.toFixed(1);
  el.tempRaw.textContent = `raw ${data.raw_c.toFixed(1)} C`;
  el.rorValue.textContent = ror.toFixed(1);

  updateRecommendation(tSec, ror);
  updateClocks(nowTs);
  drawChart();
  autoFinishCheck();
}

async function pollLoop() {
  while (true) {
    try {
      const data = await readTemperature();
      el.serverStatus.textContent = `Sensor: ${data.sensor_mode}`;
      if (state.running) {
        pushPoint(data);
      } else if (state.finished) {
        state.latest = data;
        el.tempValue.textContent = data.adjusted_c.toFixed(1);
        el.tempRaw.textContent = `raw ${data.raw_c.toFixed(1)} C`;
      }
    } catch (err) {
      el.serverStatus.textContent = `Server error: ${err.message}`;
    }
    updateClocks(Date.now());
    await new Promise((resolve) => setTimeout(resolve, state.pollingMs));
  }
}

function exportPng(nameStem) {
  const link = document.createElement("a");
  link.download = `${nameStem}.png`;
  link.href = el.chart.toDataURL("image/png");
  link.click();
}

function exportCsv(nameStem) {
  const header = "t_sec,temp_c,ror_c_per_min\n";
  const rows = state.points.map((p) => `${p.tSec.toFixed(2)},${p.tempC.toFixed(3)},${p.ror.toFixed(3)}`);
  const blob = new Blob([header, ...rows].join("\n"), { type: "text/csv" });
  const link = document.createElement("a");
  link.download = `${nameStem}.csv`;
  link.href = URL.createObjectURL(blob);
  link.click();
  URL.revokeObjectURL(link.href);
}

async function persistSession(reason) {
  const payload = {
    reason,
    profile_id: state.selectedProfileId,
    started_at: new Date(state.startTs || Date.now()).toISOString(),
    finished_at: new Date(state.finishTs || Date.now()).toISOString(),
    crack_at: state.crackTs ? new Date(state.crackTs).toISOString() : null,
    crack_temp_c: state.crackMark?.tempC ?? null,
    points: state.points,
  };
  try {
    await fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    // UI export still works without server persistence.
  }
}

function finishSession(reason = "manual") {
  if (!state.running) return;
  state.running = false;
  state.finished = true;
  state.finishTs = Date.now();
  updateControls();

  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const stem = `roast_${stamp}`;
  exportPng(stem);
  exportCsv(stem);
  persistSession(reason);
}

function startSession() {
  if (state.running) return;
  state.running = true;
  state.finished = false;
  state.startTs = Date.now();
  state.finishTs = null;
  state.crackTs = null;
  state.crackMark = null;
  state.points = [];
  el.recommendation.textContent = "Roast running";
  updateControls();
  drawChart();
}

function markFirstCrack() {
  if (!state.running || state.crackTs) return;
  state.crackTs = Date.now();
  const crackTemp = inferCrackTemp();
  const tSec = state.points.length ? state.points[state.points.length - 1].tSec : 0;
  state.crackMark = {
    tSec,
    tempC: crackTemp,
  };
  drawChart();
}

function resetSession() {
  state.running = false;
  state.finished = false;
  state.startTs = null;
  state.finishTs = null;
  state.crackTs = null;
  state.crackMark = null;
  state.points = [];
  state.latest = null;

  el.tempValue.textContent = "--";
  el.tempRaw.textContent = "raw -- C";
  el.rorValue.textContent = "--";
  el.recommendation.textContent = "Select profile and press Start";
  el.stageName.textContent = "Stage: -";
  updateClocks(Date.now());
  updateControls();
  drawChart();
}

async function loadConfig() {
  const r = await fetch("/api/config");
  const data = await r.json();
  if (!data.ok) throw new Error("Failed to load config");
  state.pollingMs = Math.max(200, Math.floor((data.poll_interval_sec || 0.5) * 1000));
  state.autoFinish = data.auto_finish || state.autoFinish;
  state.rorEmaAlpha = Number(data.ror?.ema_alpha);

  const guides = [];
  const chargeC = Number(data.temp_guides?.charge_c);
  const crackC = Number(data.temp_guides?.first_crack_c);
  const dropC = Number(data.temp_guides?.drop_c);
  if (Number.isFinite(chargeC)) guides.push({ tempC: chargeC, color: "#265f3d", label: `charge guide (${chargeC}C)` });
  if (Number.isFinite(crackC)) guides.push({ tempC: crackC, color: "#7e5a11", label: `1st crack guide (${crackC}C)` });
  if (Number.isFinite(dropC)) guides.push({ tempC: dropC, color: "#7b2b1f", label: `drop guide (${dropC}C)` });
  tempGuides = guides.length ? guides : [...defaultTempGuides];
  el.serverStatus.textContent = `Connected (${data.sensor_mode})`;
}

async function loadProfiles() {
  const r = await fetch("/api/profiles");
  const data = await r.json();
  if (!data.ok) throw new Error("Failed to load profiles");

  state.profiles = data.profiles || [];
  el.profileSelect.innerHTML = "";
  if (!state.profiles.length) {
    const opt = document.createElement("option");
    opt.textContent = "No profiles";
    opt.value = "";
    el.profileSelect.appendChild(opt);
    return;
  }

  state.profiles.forEach((p, idx) => {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.name;
    el.profileSelect.appendChild(opt);
    if (idx === 0) state.selectedProfileId = p.id;
  });

  el.profileSelect.value = state.selectedProfileId;
}

function bindEvents() {
  el.startBtn.addEventListener("click", startSession);
  el.crackBtn.addEventListener("click", markFirstCrack);
  el.finishBtn.addEventListener("click", () => finishSession("manual"));
  el.resetBtn.addEventListener("click", resetSession);
  el.profileSelect.addEventListener("change", (e) => {
    state.selectedProfileId = e.target.value;
    drawChart();
  });

  window.addEventListener("resize", drawChart);
}

async function init() {
  bindEvents();
  updateControls();
  drawChart();

  try {
    await loadConfig();
    await loadProfiles();
  } catch (err) {
    el.serverStatus.textContent = `Init error: ${err.message}`;
  }

  pollLoop();
}

init();
