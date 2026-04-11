/**
 * GuardianLens dashboard — matched to v2 clickable alerts mockup.
 *
 * SSE-driven, vanilla JS, no framework. Shield hero, platform-colored
 * timeline, severity-keyed alert cards, status ribbon.
 */

(() => {
  "use strict";

  // ----------------------------------------------------------------- DOM refs

  const els = {
    shell: document.getElementById("shell"),
    headerStatus: document.getElementById("header-status"),
    headerModel: document.getElementById("header-model"),

    shieldSub: document.getElementById("shield-sub"),

    captureCard: document.getElementById("capture-card"),
    captureScreen: document.getElementById("capture-screen"),
    captureBarIcon: document.getElementById("capture-bar-icon"),
    captureBarTitle: document.getElementById("capture-bar-title"),
    captureBarSub: document.getElementById("capture-bar-sub"),
    captureBarTime: document.getElementById("capture-bar-time"),

    ribbon: document.getElementById("ribbon"),
    timeline: document.getElementById("timeline"),
    lastRefresh: document.getElementById("last-refresh"),

    historyLabel: document.getElementById("history-label"),
    alertHistory: document.getElementById("alert-history"),

    overviewPanel: document.getElementById("overview-panel"),
    detailPanel: document.getElementById("detail-panel"),
    analysisBack: document.getElementById("analysis-back"),
    // analysisTimestampLabel removed — no longer in HTML
    analysisCard: document.getElementById("analysis-card"),
    reasoningChain: document.getElementById("reasoning-chain"),
    whyThisMatters: document.getElementById("why-this-matters"),
    flaggedMessages: document.getElementById("flagged-messages"),
    recommendedAction: document.getElementById("recommended-action"),

    footerModel: document.getElementById("footer-model"),
    footerBytesCheck: document.getElementById("footer-bytes-check"),
  };

  // ----------------------------------------------------------------- helpers

  const esc = (str) => {
    if (str == null) return "";
    return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  };
  const trunc = (str, n) => {
    if (!str) return "";
    str = str.replace(/\s+/g," ").trim();
    return str.length > n ? str.slice(0,n-1).trimEnd()+"..." : str;
  };
  const setText = (el, t) => { if (el && el.textContent !== String(t)) el.textContent = t; };
  const fmtTime = (d) => (d || new Date()).toTimeString().slice(0,8);

  // ----------------------------------------------------------------- platform helpers

  const PLATFORM_COLORS = {
    discord: "#7F77DD", minecraft: "#639922", tiktok: "#D4537E",
    instagram: "#D85A30", roblox: "#e2231a", snapchat: "#fffc00",
    telegram: "#26a5e4", unknown: "#888",
  };

  function pKey(text) {
    if (!text) return "unknown";
    const l = text.toLowerCase();
    if (l.includes("instagram")) return "instagram";
    if (l.includes("tiktok")) return "tiktok";
    if (l.includes("discord")) return "discord";
    if (l.includes("minecraft")) return "minecraft";
    if (l.includes("roblox")) return "roblox";
    if (l.includes("snap")) return "snapchat";
    if (l.includes("telegram")) return "telegram";
    return "unknown";
  }

  function platformBadge(text) {
    const k = pKey(text);
    const t = esc(text || "Unknown");
    if (k === "unknown") return `<span class="gl-platform-badge gl-platform-badge-unknown" title="${t}">?</span>`;
    return `<span class="gl-platform-badge gl-platform-badge-${k}" title="${t}"><img src="/static/icons/${k}.svg" alt=""></span>`;
  }

  // Alert card SVG icons per threat type
  // Grooming: warning triangle — universal danger
  const CARD_ICON_GROOMING = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L1 21h22L12 2z"/><path d="M12 9v4"/><circle cx="12" cy="17" r="0.5" fill="currentColor"/></svg>';
  // Bullying: speech bubble with X — toxic communication
  const CARD_ICON_BULLYING = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/><path d="M9 8l6 6M15 8l-6 6"/></svg>';
  // Inappropriate: eye off — shouldn't be seen
  const CARD_ICON_CONTENT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
  // Default: circle alert
  const CARD_ICON_DEFAULT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><circle cx="12" cy="16" r="0.5" fill="currentColor"/></svg>';

  // ----------------------------------------------------------------- view state machine

  // Persist seen alerts in localStorage so they survive page refresh
  const SEEN_KEY = "gl_seen_alerts";
  function loadSeen() {
    try { const v = localStorage.getItem(SEEN_KEY); return v ? new Set(JSON.parse(v)) : new Set(); }
    catch(_) { return new Set(); }
  }
  function saveSeen(s) {
    // Keep only the most recent 50 IDs to prevent unbounded growth
    const arr = [...s];
    const trimmed = arr.length > 50 ? arr.slice(arr.length - 50) : arr;
    try { localStorage.setItem(SEEN_KEY, JSON.stringify(trimmed)); } catch(_) {}
  }

  const uiState = {
    selectedAnalysis: null,
    seenAlerts: loadSeen(),
  };

  async function selectAlert(id) {
    try {
      const r = await fetch(`/api/analysis/${id}`);
      if (!r.ok) return;
      const a = await r.json();
      uiState.seenAlerts.add(String(id));
      saveSeen(uiState.seenAlerts);
      uiState.selectedAnalysis = a;
      render(window.__lastState || {});
      // Scroll sidebar to top so the hero card is visible
      const sidebar = document.querySelector(".gl-sidebar");
      if (sidebar) sidebar.scrollTo({ top: 0, behavior: "smooth" });
    } catch(_) {}
  }

  function showOverview() {
    uiState.selectedAnalysis = null;
    els.detailPanel.style.display = "none";
    els.overviewPanel.style.display = "";
    renderRightPanel(window.__lastState || {});
    const sidebar = document.querySelector(".gl-sidebar");
    if (sidebar) sidebar.scrollTo({ top: 0, behavior: "smooth" });
  }

  // ----------------------------------------------------------------- shield hero (filled SVG, matching mockup)

  // Shield hero icons — clean, minimal inner symbols
  const SHIELD_SAFE =
    '<svg viewBox="0 0 80 90">' +
    '<path fill="#1D9E75" d="M40 5 L72 20 L72 50 Q72 75 40 87 Q8 75 8 50 L8 20 Z"/>' +
    '<path fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" d="M27 44 L36 53 L54 35"/>' +
    '</svg>';

  const SHIELD_ALERT =
    '<svg viewBox="0 0 80 90">' +
    '<path fill="#E24B4A" d="M40 5 L72 20 L72 50 Q72 75 40 87 Q8 75 8 50 L8 20 Z"/>' +
    '<path fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" d="M40 28 L40 50"/>' +
    '<circle cx="40" cy="60" r="3" fill="#fff"/>' +
    '</svg>';

  const SHIELD_CAUTION =
    '<svg viewBox="0 0 80 90">' +
    '<path fill="#BA7517" d="M40 5 L72 20 L72 50 Q72 75 40 87 Q8 75 8 50 L8 20 Z"/>' +
    '<path fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" d="M26 42 Q33 36 40 42 Q47 48 54 42"/>' +
    '<circle cx="40" cy="42" r="4" fill="#fff"/>' +
    '</svg>';

  function renderShield(state) {
    const latest = state.latest;
    const h = state.session_health || {};
    const streak = state.safe_streak || 0;
    const isAlert = latest && (latest.threat_level === "alert" || latest.threat_level === "critical");
    const isCaution = latest && (latest.threat_level === "caution" || latest.threat_level === "warning");
    const pCount = h.platform_count || 0;

    let mode, icon, title, sub;
    const dur = h.session_duration || "0m 00s";
    if (isAlert) {
      mode = "alert"; icon = SHIELD_ALERT;
      title = "Threat detected";
      sub = `Session: ${dur}`;
    } else if (isCaution) {
      mode = "caution"; icon = SHIELD_CAUTION;
      title = "Watch closely";
      sub = `Session: ${dur}`;
    } else {
      mode = "safe"; icon = SHIELD_SAFE;
      title = "All clear";
      sub = `Session: ${dur}`;
    }
    // Session duration in stats row
    const sessionEl = els.shieldSub;
    if (sessionEl) {
      const valEl = sessionEl.querySelector(".gl-stat-val");
      if (valEl) valEl.textContent = dur;
    }

    // Populate metric counters
    const scansEl = document.getElementById("status-scans");
    const safePctEl = document.getElementById("status-safe-pct");
    const platsEl = document.getElementById("status-platforms");
    const alertsEl = document.getElementById("status-alerts");
    const respEl = document.getElementById("status-response");
    const scans = h.scans || 0;
    const safeCount = h.safe || 0;
    if (scansEl) scansEl.querySelector(".gl-stat-val").textContent = scans;
    if (safePctEl) {
      const pct = scans > 0 ? Math.round(100 * safeCount / scans) : 0;
      const val = safePctEl.querySelector(".gl-stat-val");
      val.textContent = scans > 0 ? `${pct}%` : "\u2014";
      val.style.color = pct >= 90 ? "var(--safe)" : pct >= 70 ? "var(--caution)" : pct > 0 ? "var(--alert)" : "";
    }
    if (platsEl) platsEl.querySelector(".gl-stat-val").textContent = pCount;
    if (alertsEl) {
      const aCount = h.alerts || 0;
      const val = alertsEl.querySelector(".gl-stat-val");
      val.textContent = aCount;
      val.style.color = aCount > 0 ? "var(--alert)" : "";
    }
    if (respEl) {
      const avg = h.avg_inference_label || "\u2014";
      respEl.querySelector(".gl-stat-val").textContent = avg.replace(" avg", "");
    }
  }

  // ----------------------------------------------------------------- header

  function renderHeader(state) {
    const mon = state.monitoring;
    const paused = state.paused;
    const latest = state.latest;
    const isAlert = latest && (latest.threat_level === "alert" || latest.threat_level === "critical");
    let shieldColor, label, extra = "";
    if (paused) { shieldColor = "var(--text-dim)"; label = "Paused"; }
    else if (!mon) { shieldColor = "var(--text-dim)"; label = "Stopped"; }
    else if (isAlert) { shieldColor = "var(--alert)"; label = "Threat detected"; extra = "gl-header-status-alert"; }
    else { shieldColor = "var(--safe)"; label = "Active"; }
    els.headerStatus.className = `gl-header-status ${extra}`.trim();
    els.headerStatus.innerHTML = `<svg class="gl-header-shield" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="${shieldColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L4 6v6c0 5.25 3.75 9.75 8 10 4.25-0.25 8-4.75 8-10V6l-8-4z"/></svg><span class="status-text" style="color:${shieldColor}">${esc(label)}</span>`;
    setText(els.headerModel, state.model_name || "");

    // LIVE tag + paused overlay
    const liveTag = document.getElementById("capture-live-tag");
    if (liveTag) liveTag.style.display = paused ? "none" : "";
    els.captureCard.classList.toggle("gl-capture-paused", !!paused);

    // Pause button state
    const pauseBtn = document.getElementById("header-pause");
    if (pauseBtn) {
      const lbl = pauseBtn.querySelector(".gl-pause-label");
      if (paused) {
        pauseBtn.classList.add("gl-paused");
        if (lbl) lbl.textContent = "Resume";
      } else {
        pauseBtn.classList.remove("gl-paused");
        if (lbl) lbl.textContent = "Pause";
      }
    }
  }

  // ----------------------------------------------------------------- capture

  const CAP_CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>';
  const CAP_WARN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L1 21h22L12 2zm0 7v5m0 3v1"/></svg>';
  const CAP_EYE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z"/><circle cx="12" cy="12" r="2.5" fill="currentColor"/></svg>';

  let _lastCaptureTs = "";

  function renderCapture(state) {
    const a = state.latest;
    if (a && a.timestamp === _lastCaptureTs) return;
    _lastCaptureTs = a ? a.timestamp : "";
    if (!a) {
      els.captureCard.classList.remove("gl-capture-caution", "gl-capture-alert");
      els.captureCard.classList.add("gl-capture", "gl-capture-safe");
      els.captureScreen.innerHTML = '<div class="gl-capture-placeholder"><div class="gl-skeleton gl-skeleton-block" style="width:100%;height:100%;position:absolute;inset:0"></div></div>';
      els.captureBarIcon.innerHTML = CAP_CHECK;
      setText(els.captureBarTitle, "Initializing");
      setText(els.captureBarSub, "");
      setText(els.captureBarTime, "--:--:--");
      return;
    }
    const level = a.threat_level || "safe";
    const isAlert = level === "alert" || level === "critical";
    const isCaution = level === "caution" || level === "warning";
    const mode = isAlert ? "alert" : isCaution ? "caution" : "safe";
    // Use classList to preserve gl-capture-paused set by renderHeader
    els.captureCard.classList.remove("gl-capture-safe", "gl-capture-caution", "gl-capture-alert");
    els.captureCard.classList.add("gl-capture", `gl-capture-${mode}`);

    // Always store the screenshot URL for the lightbox
    const screenshotSrc = a.screenshot_url ? `${a.screenshot_url}?t=${encodeURIComponent(a.timestamp||Date.now())}` : "";
    els.captureScreen.dataset.screenshot = screenshotSrc;

    const hasChat = (a.chat_messages||[]).length > 0;
    if ((isAlert||isCaution) && hasChat) {
      els.captureScreen.innerHTML = renderChat(a);
    } else if (a.screenshot_url) {
      els.captureScreen.innerHTML = `<img class="gl-capture-img" src="${screenshotSrc}" alt="">`;
    } else {
      els.captureScreen.innerHTML = `<div class="gl-capture-placeholder">${esc(a.platform||"")}</div>`;
    }

    if (isAlert) {
      els.captureBarIcon.innerHTML = CAP_WARN;
      const lbl = (a.category_label||"Threat").trim();
      const stg = a.stage_segments && a.stage_segments.current_index >= 0 ? ` \u00b7 Stage ${a.stage_segments.current_index+1}/5` : "";
      setText(els.captureBarTitle, `${lbl} \u00b7 ${a.confidence}%${stg}`);
    } else if (isCaution) {
      els.captureBarIcon.innerHTML = CAP_EYE;
      setText(els.captureBarTitle, `${(a.category_label||"Caution").trim()} \u00b7 watch closely`);
    } else {
      els.captureBarIcon.innerHTML = CAP_CHECK;
      setText(els.captureBarTitle, `${a.platform||"Unknown"} \u00b7 No threats`);
    }
    setText(els.captureBarSub, "");
    setText(els.captureBarTime, a.time_label || "--:--:--");
  }

  function renderChat(a) {
    const conv = a.conversation || {};
    const msgs = a.chat_messages || [];
    const user = conv.username || a.platform || "Conversation";
    const k = conv.platform_key || a.platform_key || "unknown";
    const avatar = k !== "unknown" ? `<img src="/static/icons/${k}.svg" alt="">` : user.charAt(0).toUpperCase();

    const header = `<div class="gl-capture-chat-header"><div class="gl-capture-chat-avatar">${avatar}</div><div class="gl-capture-chat-titles"><div class="gl-capture-chat-username">${esc(user)}</div><div class="gl-capture-chat-status">Active now</div></div></div>`;
    const bubbles = msgs.map(m => {
      const lo = (m.sender||"").toLowerCase();
      const isMe = lo==="me"||lo==="self"||lo==="child";
      const side = isMe ? "gl-capture-msg-me" : "gl-capture-msg-them";
      const flag = m.flag ? "gl-capture-msg-flagged" : "";
      const tag = m.flag ? `<div class="gl-capture-msg-flag-tag">${esc(m.flag)}</div>` : "";
      return `<div class="gl-capture-msg ${side} ${flag}"><div class="gl-capture-msg-bubble">${esc(m.text)}</div>${tag}</div>`;
    }).join("");
    return `<div class="gl-capture-chat">${header}<div class="gl-capture-chat-body">${bubbles}</div></div>`;
  }

  // ----------------------------------------------------------------- ribbon + timeline

  function renderRibbon(state) {
    if (!els.ribbon) return;
    const hist = state.scan_history || [];
    const slots = 20;
    const padded = hist.slice(-slots);
    while (padded.length < slots) padded.unshift({tone:"empty"});
    els.ribbon.innerHTML = padded.map(e => `<div class="gl-ribbon-seg gl-ribbon-seg-${e.tone||"empty"}"></div>`).join("");
  }

  let _lastTimelineKey = "";

  function renderTimeline(state) {
    const rawEntries = state.timeline || [];
    const tlKey = rawEntries.map(e => e.timestamp || e.time_label).join(",");
    if (tlKey === _lastTimelineKey) return;
    _lastTimelineKey = tlKey;

    if (!rawEntries.length) {
      els.timeline.innerHTML = '<div class="gl-empty">Waiting for the first capture...</div>';
      return;
    }

    // Collapse consecutive safe entries into a single group row.
    // Runs of 2+ safe scans become one "N safe scans (14:30 – 14:45)" entry.
    // Single safe scans render normally so the UI isn't too aggressive.
    const entries = [];
    let i = 0;
    while (i < rawEntries.length) {
      const curr = rawEntries[i];
      if (curr.threat_level === "safe") {
        let j = i;
        while (j < rawEntries.length && rawEntries[j].threat_level === "safe") j++;
        const runLen = j - i;
        if (runLen >= 2) {
          // entries are newest-first, so newest of the run is at i, oldest at j-1
          entries.push({
            is_group: true,
            count: runLen,
            time_start: rawEntries[j - 1].time_label,
            time_end: rawEntries[i].time_label,
            platform: rawEntries[i].platform,
            platform_key: rawEntries[i].platform_key,
          });
          i = j;
          continue;
        }
      }
      entries.push(curr);
      i++;
    }

    // Compute escalation runs — mark entries that are part of a worsening sequence
    // Entries are newest-first, so we scan bottom-up (oldest to newest) to find progression
    const levelNum = (l) => l === "safe" ? 0 : (l === "caution" || l === "warning") ? 1 : 2;
    const escalation = new Array(entries.length).fill(false);
    // Walk oldest→newest (end→start of array)
    for (let i = entries.length - 2; i >= 0; i--) {
      if (entries[i].is_group || entries[i + 1].is_group) continue;
      const curr = levelNum(entries[i].threat_level);
      const prev = levelNum(entries[i + 1].threat_level);
      if (curr > 0 && prev > 0 && curr >= prev) {
        escalation[i] = true;
        escalation[i + 1] = true;
      }
    }

    els.timeline.innerHTML = entries.map((e, i) => {
      // Collapsed group row — consecutive safe scans
      if (e.is_group) {
        const range = e.time_start === e.time_end ? e.time_end : `${e.time_start} – ${e.time_end}`;
        return `<div class="gl-timeline-entry gl-timeline-group" data-tl-idx="${i}">
          <span class="gl-timeline-group-icon">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
          </span>
          <div class="gl-timeline-body">
            <div class="gl-timeline-row1">
              <span class="gl-timeline-group-text">${e.count} safe scans</span>
              <span class="gl-timeline-time">${esc(range)}</span>
            </div>
          </div>
        </div>`;
      }
      const level = e.threat_level;
      const k = e.platform_key || pKey(e.platform);
      const levelCls = level === "alert" || level === "critical" ? "alert" :
                       level === "caution" || level === "warning" ? "caution" : "safe";
      const time = e.time_label || "";
      const iconInner = k !== "unknown"
        ? `<img src="/static/icons/${k}.svg" alt="">`
        : `<span class="gl-timeline-icon-letter">${(e.platform||"?").charAt(0).toUpperCase()}</span>`;
      const isClickable = levelCls !== "safe";
      const escCls = escalation[i] ? " gl-timeline-escalation" : "";
      const escStart = escalation[i] && (i === 0 || !escalation[i - 1]);
      const escStartCls = escStart ? " gl-timeline-esc-start" : "";
      return `<div class="gl-timeline-entry gl-timeline-entry-${levelCls}${isClickable?" gl-timeline-clickable":""}${escCls}${escStartCls}" data-tl-idx="${i}">
        <div class="gl-timeline-esc-bar"></div>
        <span class="gl-timeline-icon" data-platform="${k}">${iconInner}</span>
        <div class="gl-timeline-body">
          <div class="gl-timeline-row1">
            <span class="gl-timeline-platform">${esc(e.platform||"Unknown")}</span>
            <span class="gl-timeline-time">${esc(time)}</span>
            <span class="gl-timeline-badge gl-timeline-badge-${levelCls}">${esc(level)}</span>
          </div>
          <div class="gl-timeline-row2">${levelCls === "safe"
            ? "No threats detected"
            : (e.indicators||[]).slice(0,3).map(p => `<span class="gl-timeline-tag gl-timeline-tag-${levelCls}">${esc(p)}</span>`).join("") || esc(trunc(e.reasoning,40))
          }</div>
        </div>
      </div>`;
    }).join("");
    // All timeline rows are clickable — alerts open detail, safe shows inline analysis
    window.__timelineData = entries;
    els.timeline.querySelectorAll(".gl-timeline-entry").forEach(row => {
      row.addEventListener("click", () => {
        const idx = parseInt(row.getAttribute("data-tl-idx"), 10);
        const entry = entries[idx];
        if (!entry || entry.is_group) return;
        // Match by ISO timestamp (unique per analysis) with time_label fallback
        const hist = (window.__lastState && window.__lastState.alert_history) || [];
        const match = hist.find(a => a.timestamp === entry.timestamp) ||
                      hist.find(a => a.time_label === entry.time_label);
        if (match && match.analysis_id) {
          selectAlert(match.analysis_id);
        }
      });
    });
  }

  // ----------------------------------------------------------------- right: SAFE overview

  function renderRightPanel(state) {
    renderAlertHistory(state.alert_history || [], state.current_session_id);
  }

  let _lastHistoryKey = "";

  function renderAlertHistory(history, sessionId) {
    // Build a fingerprint to skip re-render when nothing changed
    const ids = history.map(a => a.analysis_id).join(",");
    const seenCount = history.filter(a => uiState.seenAlerts.has(String(a.analysis_id))).length;
    const key = `${ids}|${seenCount}`;
    if (key === _lastHistoryKey) return;
    _lastHistoryKey = key;

    if (!history.length) {
      els.historyLabel.innerHTML = `Alerts`;
      els.alertHistory.innerHTML =
        `<div class="gl-history-empty">
          <div class="gl-history-empty-shield"><svg viewBox="0 0 80 90"><path fill="#1D9E75" d="M40 5 L72 20 L72 50 Q72 75 40 87 Q8 75 8 50 L8 20 Z"/><path fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" d="M25 45 L35 55 L55 35"/></svg></div>
          <div class="gl-history-empty-title">All clear</div>
          <div class="gl-history-empty-sub">No threats detected yet.<br>GuardianLens is actively monitoring.</div>
        </div>`;
      return;
    }
    const newAlerts = history.filter(a => !uiState.seenAlerts.has(String(a.analysis_id)));
    const seenAlerts = history.filter(a => uiState.seenAlerts.has(String(a.analysis_id)));
    const newCount = newAlerts.length;
    const allSeen = newCount === 0;
    const total = (window.__lastState && window.__lastState.alert_total) || history.length;
    const showing = history.length;
    const totalHint = total > showing ? `<span class="gl-history-total">${showing} of ${total}</span>` : "";
    if (newCount > 0) {
      els.historyLabel.innerHTML = `Alerts <span class="gl-history-counter">${newCount} new</span><button class="gl-history-dismiss" id="mark-all-read">Dismiss all</button>${totalHint}`;
    } else {
      els.historyLabel.innerHTML = `Alerts <span class="gl-history-allreviewed">All reviewed</span>${totalHint}`;
    }

    let html = "";
    html += newAlerts.map(a => renderAlertCard(a, "new")).join("");
    if (newAlerts.length > 0 && seenAlerts.length > 0) {
      html += '<div class="gl-history-divider">Reviewed</div>';
    }
    if (allSeen) {
      html += '<div class="gl-history-allseen"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>No new alerts</div>';
    }
    html += seenAlerts.map(a => renderAlertCard(a, allSeen ? "reviewed" : "seen")).join("");
    els.alertHistory.innerHTML = html;
  }

  // state: "new" | "seen" (dimmed, mixed with new) | "reviewed" (all seen, full opacity)
  function renderAlertCard(a, state) {
    const type = a.threat_type || "";
    const threatKey = (type === "grooming" || type === "bullying" || type === "inappropriate_content") ? type : "other";
    let icon = CARD_ICON_DEFAULT;
    if (type === "grooming") icon = CARD_ICON_GROOMING;
    else if (type === "bullying") icon = CARD_ICON_BULLYING;
    else if (type === "inappropriate_content") icon = CARD_ICON_CONTENT;

    const stateClass = state === "seen" ? "gl-alert-card-seen" : state === "new" ? "gl-alert-card-new" : state === "reviewed" ? "gl-alert-card-reviewed" : "";

    const badgeHtml = state === "new"
      ? `<span class="gl-alert-card-badge">NEW</span>`
      : "";

    const pills = (a.indicators||[]).slice(0,4).map(p =>
      `<span class="gl-alert-card-pill">${esc(p)}</span>`
    ).join("");

    // Grooming stage mini-bar
    let stageHtml = "";
    const stageIdx = a.grooming_stage_index || 0;
    if (type === "grooming" && stageIdx > 0) {
      let segs = "";
      for (let i = 0; i < 5; i++) {
        const cls = i < stageIdx - 1 ? "gl-alert-card-stage-seg-filled" :
                    i === stageIdx - 1 ? "gl-alert-card-stage-seg-current" : "";
        segs += `<div class="gl-alert-card-stage-seg ${cls}"></div>`;
      }
      stageHtml = `<div class="gl-alert-card-stage-mini">${segs}<span class="gl-alert-card-stage-label">Stage ${stageIdx}/5</span></div>`;
    }

    return `<div class="gl-alert-card ${stateClass}" data-threat="${threatKey}" data-analysis-id="${a.analysis_id}">
      <div class="gl-alert-card-icon-wrap">${icon}</div>
      <div class="gl-alert-card-top">
        <span class="gl-alert-card-title">${esc(a.threat_label)}</span>
        <span class="gl-alert-card-conf">${a.confidence}%</span>
        ${badgeHtml}
      </div>
      <span class="gl-alert-card-time">${esc(a.time_ago)}</span>
      <div class="gl-alert-card-mid">
        <span class="gl-alert-card-plat" data-platform="${a.platform_key||"unknown"}">${a.platform_key && a.platform_key !== "unknown" ? `<img src="/static/icons/${a.platform_key}.svg" alt="">` : ""}</span>
        <span class="gl-alert-card-user">${esc(a.user)}</span>
        <span class="gl-alert-card-sep">\u2022</span>
        <span class="gl-alert-card-platform-name">${esc(a.platform||"Unknown")}</span>
      </div>
      <div class="gl-alert-card-bottom">${pills}${stageHtml}</div>
      <span class="gl-alert-card-arrow">\u203a</span>
    </div>`;
  }

  // ----------------------------------------------------------------- right: FULL ANALYSIS

  function renderRightAnalysis(state) {
    const a = uiState.selectedAnalysis;
    if (!a) { els.analysisCard.innerHTML = '<div class="gl-empty">No analysis.</div>'; return; }
    renderAnalysisCard(a);
    renderReasoning(a);
    renderWhy(a);
    renderFlagged(a);
    renderAction(a);
  }

  function renderAnalysisCard(a) {
    const cat = a.category || "";
    const threatKey = (cat === "grooming" || cat === "bullying" || cat === "inappropriate_content") ? cat : "other";
    const title = a.category_label ? `${a.category_label} detected` : "Threat detected";
    const conv = a.conversation || {};
    const pk = conv.platform_key || a.platform_key || "unknown";

    let icon = CARD_ICON_DEFAULT;
    if (cat === "grooming") icon = CARD_ICON_GROOMING;
    else if (cat === "bullying") icon = CARD_ICON_BULLYING;
    else if (cat === "inappropriate_content") icon = CARD_ICON_CONTENT;

    const platIcon = pk !== "unknown"
      ? `<span class="gl-detail-hero-plat" style="background:${PLATFORM_COLORS[pk]||"#334155"}"><img src="/static/icons/${pk}.svg" alt=""></span>`
      : "";
    const meta = `${platIcon}${esc(conv.username||"\u2014")} \u00b7 ${esc(a.platform||"Unknown")}`;

    const pills = (a.indicator_pills||a.indicators||[]).slice(0,6).map(p => {
      const l = typeof p==="string"?p:p.label;
      return `<span class="gl-detail-hero-pill">${esc(l)}</span>`;
    }).join("");

    let stagebar = "";
    if (cat === "grooming" && a.stage_segments && a.stage_segments.current_index >= 0 && Array.isArray(a.stage_segments.segments)) {
      stagebar = `<div class="gl-detail-hero-stagebar">${a.stage_segments.segments.map(s => {
        const c = s.state==="active"?"gl-detail-hero-stage-active":s.state==="current"?"gl-detail-hero-stage-current":"";
        return `<div class="gl-detail-hero-stage-seg ${c}"></div>`;
      }).join("")}</div>`;
    }

    els.analysisCard.setAttribute("data-threat", threatKey);
    els.analysisCard.innerHTML = `
      <div class="gl-detail-hero-top">
        <div class="gl-detail-hero-left">
          <div class="gl-detail-hero-icon">${icon}</div>
          <div class="gl-detail-hero-titles">
            <div class="gl-detail-hero-title">${esc(title)}</div>
            <div class="gl-detail-hero-meta">${meta}</div>
          </div>
        </div>
        <div class="gl-detail-hero-conf">
          <div class="gl-detail-hero-conf-val">${a.confidence}%</div>
          <div class="gl-detail-hero-conf-lbl">confidence</div>
        </div>
      </div>
      <div class="gl-detail-hero-pills">${pills}</div>
      ${stagebar}`;

    // Render screenshot in its own section
    const capSec = document.getElementById("capture-section");
    const capEl = document.getElementById("detail-capture");
    if (a.screenshot_url && capSec && capEl) {
      capEl.innerHTML = `<div class="gl-detail-capture-frame" id="capture-frame"><img src="${a.screenshot_url}?t=${encodeURIComponent(a.timestamp||"")}" alt="Captured screenshot"></div>`;
      capSec.style.display = "";
    } else if (capSec) {
      capSec.style.display = "none";
    }
  }

  function renderReasoning(a) {
    const steps = (a&&a.reasoning_chain)||[];
    if (!steps.length) { els.reasoningChain.innerHTML = '<div class="gl-empty">No reasoning.</div>'; return; }
    els.reasoningChain.innerHTML = steps.map(s => {
      if (s.type==="verdict") return `<span class="gl-reasoning-step-verdict">${esc(s.text)}</span>`;
      if (s.type==="flag") return `<span class="gl-reasoning-step-flag">${esc(s.text)}</span>`;
      const lbl = s.label ? `<span class="gl-reasoning-step-label">${esc(s.label)}</span> ` : "";
      return `<div>${lbl}<span class="gl-reasoning-step-text">${esc(s.text)}</span></div>`;
    }).join("");
  }

  function renderWhy(a) {
    const t = a&&a.why_this_matters;
    const sec = document.getElementById("why-section");
    if (!t) { if (sec) sec.style.display="none"; return; }
    if (sec) sec.style.display="";
    els.whyThisMatters.innerHTML = `<div class="gl-why-text">${esc(t).replace(/\n/g, "<br>")}</div>`;
  }

  function renderFlagged(a) {
    const bd = (a&&a.threat_breakdown)||[];
    const wq = bd.filter(b=>b.quote);
    const sec = document.getElementById("flagged-section");
    if (!wq.length) { if (sec) sec.style.display="none"; return; }
    if (sec) sec.style.display="";
    const cat = a.category||"";
    const color = cat==="grooming"?"var(--alert)":cat==="bullying"?"var(--caution)":"var(--orange)";
    els.flaggedMessages.innerHTML = wq.map(item =>
      `<div class="gl-flagged-msg">
        <div class="gl-flagged-msg-body">
          <span class="gl-flagged-msg-quote" style="color:${color}">\u201c${esc(item.quote)}\u201d</span>
          <span class="gl-flagged-msg-explanation">${esc(item.explanation||item.title||"")}</span>
        </div>
      </div>`
    ).join("");
  }

  function renderAction(a) {
    const action = a&&a.recommended_action;
    if (!action) { els.recommendedAction.innerHTML=''; return; }
    const cat = a.category||"";
    const color = cat==="grooming"?"#E24B4A":cat==="bullying"?"#BA7517":cat==="inappropriate_content"?"#D85A30":"#7F77DD";
    const bg = cat==="grooming"?"#2a1a1a":cat==="bullying"?"#1f1a0f":cat==="inappropriate_content"?"#2a1a0f":"#1e1e32";
    const steps = (action.steps||[]).map((s,i) =>
      `<div class="gl-action-step"><span class="gl-action-num" style="background:${bg};color:${color}">${i+1}</span><span class="gl-action-text">${esc(s)}</span></div>`
    ).join("");
    els.recommendedAction.innerHTML = steps;
  }


  // ----------------------------------------------------------------- notifications

  const notify = (() => {
    let ctx=null,unlocked=false,lastTs=null,init=false,permReq=false;
    const mkCtx=()=>{if(ctx)return ctx;const C=window.AudioContext||window.webkitAudioContext;if(!C)return null;try{ctx=new C;return ctx}catch(_){return null}};
    const unlock=async()=>{if(unlocked)return;const c=mkCtx();if(!c)return;if(c.state==="suspended")try{await c.resume()}catch(_){}unlocked=c.state==="running"};
    document.addEventListener("click",unlock,{once:false});
    document.addEventListener("keydown",unlock,{once:false});
    const ding=()=>{if(!ctx||ctx.state!=="running")return;const t=ctx.currentTime;[{f:880,s:0,d:.35},{f:1320,s:.1,d:.4}].forEach(v=>{const o=ctx.createOscillator(),g=ctx.createGain();o.type="sine";o.frequency.value=v.f;o.connect(g);g.connect(ctx.destination);const s=t+v.s;g.gain.setValueAtTime(0,s);g.gain.linearRampToValueAtTime(.25,s+.02);g.gain.exponentialRampToValueAtTime(.001,s+v.d);o.start(s);o.stop(s+v.d+.05)})};
    const handle=(state)=>{if(!permReq){permReq=true;if(typeof Notification!=="undefined"&&Notification.permission==="default")try{Notification.requestPermission()}catch(_){}}const a=state&&state.latest;const isA=a&&(a.threat_level==="alert"||a.threat_level==="critical");const ts=isA?a.timestamp:null;if(!init){init=true;lastTs=ts;return}if(!ts||ts===lastTs)return;lastTs=ts;ding();if(typeof Notification!=="undefined"&&Notification.permission==="granted"){const pa=(a.parent_alert||{});try{const n=new Notification(pa.title?`GuardianLens \u2014 ${pa.title}`:"GuardianLens \u2014 alert",{body:pa.summary||`${a.category_label||"Threat"} on ${a.platform||"app"}`,tag:"gl",silent:false});n.onclick=()=>{window.focus();n.close()};setTimeout(()=>{try{n.close()}catch(_){}},8e3)}catch(_){}}};
    return{handle,test:async()=>{await unlock();ding()}};
  })();
  window.notify = notify;

  // ----------------------------------------------------------------- render

  function render(state) {
    if (!state) return;
    window.__lastState = state;
    document.body.classList.toggle("loaded", true);
    notify.handle(state);

    const latest = state.latest;
    const isAlert = latest && (latest.threat_level==="alert"||latest.threat_level==="critical");
    els.shell.classList.toggle("gl-alert-active", !!isAlert);
    els.shell.classList.toggle("gl-shell-paused", !!state.paused);

    renderHeader(state);
    renderShield(state);
    renderCapture(state);
    renderTimeline(state);

    if (els.footerBytesCheck && state.metrics && state.metrics.screenshots > 0) {
      els.footerBytesCheck.classList.add("gl-footer-check-visible");
    }

    if (uiState.selectedAnalysis) {
      // Detail view — hide overview, show detail
      els.overviewPanel.style.display = "none";
      els.detailPanel.style.display = "";
      renderRightAnalysis(state);
    } else {
      // Overview — show alert list, hide detail
      els.overviewPanel.style.display = "";
      els.detailPanel.style.display = "none";
      renderRightPanel(state);
    }

    setText(els.lastRefresh, fmtTime());
    setText(els.footerModel, state.model_name);
  }

  // ----------------------------------------------------------------- bootstrap

  function connectStream() {
    let retryDelay = 1000;
    const maxDelay = 30000;
    let src;

    function connect() {
      src = new EventSource("/api/stream");
      src.onopen = () => { retryDelay = 1000; };
      src.onmessage = (e) => { try { render(JSON.parse(e.data)); } catch(err) { console.error("SSE",err); } };
      src.onerror = () => {
        src.close();
        console.warn(`SSE dropped, reconnecting in ${retryDelay/1000}s...`);
        setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, maxDelay);
      };
    }
    connect();
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (els.analysisBack) {
      els.analysisBack.addEventListener("click", showOverview);
    }
    // Pause/Resume button
    const pauseBtn = document.getElementById("header-pause");
    if (pauseBtn) {
      pauseBtn.addEventListener("click", async () => {
        const isPaused = pauseBtn.classList.contains("gl-paused");
        await fetch(isPaused ? "/api/resume" : "/api/pause", { method: "POST" });
        // Fetch fresh state immediately so UI updates without waiting for SSE tick
        try {
          const r = await fetch("/api/state");
          if (r.ok) render(await r.json());
        } catch(_) {}
      });
    }
    // Lightbox — reusable for any image click
    function openLightbox(imgSrc) {
      const overlay = document.createElement("div");
      overlay.className = "gl-lightbox";
      overlay.innerHTML = `<img src="${imgSrc}" alt=""><div class="gl-lightbox-hint">Click anywhere or press Esc to close</div><div class="gl-lightbox-close">\u00d7</div>`;
      document.body.appendChild(overlay);
      requestAnimationFrame(() => overlay.classList.add("gl-lightbox-open"));
      const close = () => { overlay.classList.remove("gl-lightbox-open"); setTimeout(() => overlay.remove(), 200); };
      overlay.addEventListener("click", close);
      document.addEventListener("keydown", function esc(ev) { if (ev.key === "Escape") { close(); document.removeEventListener("keydown", esc); } });
    }
    // Detail panel capture lightbox
    document.addEventListener("click", (e) => {
      const frame = e.target.closest("#capture-frame");
      if (!frame) return;
      const img = frame.querySelector("img");
      if (img) openLightbox(img.src);
    });
    // Main capture lightbox — always opens the real screenshot
    if (els.captureScreen) {
      els.captureScreen.addEventListener("click", () => {
        const src = els.captureScreen.dataset.screenshot;
        if (src) openLightbox(src);
      });
    }
    // Event delegation for alert history clicks — survives innerHTML re-renders
    if (els.alertHistory) {
      els.alertHistory.addEventListener("click", (e) => {
        const card = e.target.closest("[data-analysis-id]");
        if (card) {
          const id = card.getAttribute("data-analysis-id");
          if (id) selectAlert(id);
        }
      });
    }
    // Mark all read button (event delegation — button is recreated on render)
    document.addEventListener("click", (e) => {
      if (e.target.id === "mark-all-read" || e.target.closest("#mark-all-read")) {
        const history = (window.__lastState && window.__lastState.alert_history) || [];
        history.forEach(a => uiState.seenAlerts.add(String(a.analysis_id)));
        saveSeen(uiState.seenAlerts);
        _lastHistoryKey = "";
        render(window.__lastState || {});
      }
    });
    // ---------------- Settings drawer ----------------
    const gearBtn = document.getElementById("header-gear");
    const drawer = document.getElementById("settings-drawer");
    const drawerBackdrop = document.getElementById("drawer-backdrop");
    const drawerClose = document.getElementById("drawer-close");
    const modelPicker = document.getElementById("model-picker");
    const intervalPills = document.getElementById("interval-pills");

    async function openDrawer() {
      drawer.classList.add("gl-drawer-open");
      drawerBackdrop.classList.add("gl-drawer-open");
      // Update current interval pills + active state from last state
      const currentInterval = (window.__lastState && window.__lastState.capture_interval_seconds) || 30;
      if (intervalPills) {
        intervalPills.querySelectorAll(".gl-drawer-pill").forEach(b => {
          const s = parseFloat(b.getAttribute("data-seconds"));
          b.classList.toggle("gl-drawer-pill-active", Math.abs(s - currentInterval) < 1);
        });
      }
      // Fetch available models
      modelPicker.innerHTML = '<option>Loading models...</option>';
      try {
        const r = await fetch("/api/models");
        if (r.ok) {
          const data = await r.json();
          const current = data.current || "";
          const models = data.models || [];
          if (models.length === 0) {
            modelPicker.innerHTML = '<option>No models found</option>';
          } else {
            modelPicker.innerHTML = models.map(m =>
              `<option value="${m}"${m === current ? " selected" : ""}>${m}</option>`
            ).join("");
          }
          updateDrawerFooter(current);
        }
      } catch(err) {
        modelPicker.innerHTML = '<option>Failed to load models</option>';
        console.error("Failed to fetch models:", err);
      }
    }
    function updateDrawerFooter(modelName) {
      const footer = document.querySelector(".gl-drawer-footer");
      if (footer && modelName) {
        footer.innerHTML = `Active model: <strong style="color:var(--purple);font-family:var(--font-mono)">${modelName}</strong> \u00b7 On-device`;
      }
    }
    function closeDrawer() {
      drawer.classList.remove("gl-drawer-open");
      drawerBackdrop.classList.remove("gl-drawer-open");
    }
    if (gearBtn) gearBtn.addEventListener("click", openDrawer);
    if (drawerClose) drawerClose.addEventListener("click", closeDrawer);
    if (drawerBackdrop) drawerBackdrop.addEventListener("click", closeDrawer);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && drawer && drawer.classList.contains("gl-drawer-open")) closeDrawer();
    });
    if (modelPicker) {
      modelPicker.addEventListener("change", async () => {
        const model = modelPicker.value;
        try {
          const r = await fetch("/api/config/model", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({model}),
          });
          if (r.ok) {
            // Update header chip and drawer footer immediately
            setText(els.headerModel, model);
            updateDrawerFooter(model);
          }
        } catch(err) {
          console.error("Failed to switch model:", err);
        }
      });
    }
    if (intervalPills) {
      intervalPills.addEventListener("click", async (e) => {
        const btn = e.target.closest(".gl-drawer-pill");
        if (!btn) return;
        const seconds = parseFloat(btn.getAttribute("data-seconds"));
        if (!seconds) return;
        intervalPills.querySelectorAll(".gl-drawer-pill").forEach(b => b.classList.remove("gl-drawer-pill-active"));
        btn.classList.add("gl-drawer-pill-active");
        try {
          await fetch("/api/config/interval", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({seconds}),
          });
        } catch(_) {}
      });
    }

    const node = document.getElementById("initial-state");
    if (node) try { render(JSON.parse(node.textContent)); } catch(_) {}
    connectStream();
  });
})();
