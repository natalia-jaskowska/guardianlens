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
    headerDuration: document.getElementById("header-duration"),
    headerModel: document.getElementById("header-model"),
    headerStreak: document.getElementById("header-streak"),
    headerStreakText: document.getElementById("header-streak-text"),

    shieldHero: document.getElementById("shield-hero"),
    shieldIcon: document.getElementById("shield-icon"),
    shieldTitle: document.getElementById("shield-title"),
    shieldSub: document.getElementById("shield-sub"),

    captureCard: document.getElementById("capture-card"),
    captureScreen: document.getElementById("capture-screen"),
    captureBarIcon: document.getElementById("capture-bar-icon"),
    captureBarTitle: document.getElementById("capture-bar-title"),
    captureBarSub: document.getElementById("capture-bar-sub"),
    captureBarTime: document.getElementById("capture-bar-time"),
    captureBarBadge: document.getElementById("capture-bar-badge"),

    ribbon: document.getElementById("ribbon"),
    timeline: document.getElementById("timeline"),
    lastRefresh: document.getElementById("last-refresh"),

    statsLine: document.getElementById("stats-line"),
    historyLabel: document.getElementById("history-label"),
    alertHistory: document.getElementById("alert-history"),

    overviewPanel: document.getElementById("overview-panel"),
    detailPanel: document.getElementById("detail-panel"),
    analysisBack: document.getElementById("analysis-back"),
    // analysisTimestampLabel removed — no longer in HTML
    analysisCard: document.getElementById("analysis-card"),
    reasoningChain: document.getElementById("reasoning-chain"),
    whyThisMatters: document.getElementById("why-this-matters"),
    flaggedLabel: document.getElementById("flagged-label"),
    flaggedMessages: document.getElementById("flagged-messages"),
    recommendedAction: document.getElementById("recommended-action"),
    telegramBlock: document.getElementById("telegram-block"),

    footerModel: document.getElementById("footer-model"),
    footerDb: document.getElementById("footer-db"),
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

  // Alert card SVG icons per threat type (matching mockup)
  const CARD_ICON_GROOMING = '<svg viewBox="0 0 24 24" fill="none" stroke="#E24B4A" stroke-width="2"><path d="M12 2L1 21h22L12 2zm0 7v5m0 3v1"/></svg>';
  const CARD_ICON_BULLYING = '<svg viewBox="0 0 24 24" fill="none" stroke="#BA7517" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M8 15s1.5-2 4-2 4 2 4 2M9 9h.01M15 9h.01"/></svg>';
  const CARD_ICON_CONTENT = '<svg viewBox="0 0 24 24" fill="none" stroke="#D85A30" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M12 8v4m0 4h.01"/></svg>';
  const CARD_ICON_DEFAULT = '<svg viewBox="0 0 24 24" fill="none" stroke="#888" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4m0 4h.01"/></svg>';

  // ----------------------------------------------------------------- view state machine

  const uiState = {
    selectedAnalysis: null,
    seenAlerts: new Set(),
  };

  async function selectAlert(id) {
    try {
      const r = await fetch(`/api/analysis/${id}`);
      if (!r.ok) return;
      const a = await r.json();
      uiState.seenAlerts.add(String(id));
      uiState.selectedAnalysis = a;
      render(window.__lastState || {});
    } catch(_) {}
  }

  function showOverview() {
    uiState.selectedAnalysis = null;
    els.detailPanel.style.display = "none";
    els.overviewPanel.style.display = "";
    renderRightPanel(window.__lastState || {});
  }

  // ----------------------------------------------------------------- shield hero (filled SVG, matching mockup)

  const SHIELD_SAFE =
    '<svg viewBox="0 0 80 90">' +
    '<path fill="#1D9E75" d="M40 5 L72 20 L72 50 Q72 75 40 87 Q8 75 8 50 L8 20 Z"/>' +
    '<path fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" d="M25 45 L35 55 L55 35"/>' +
    '</svg>';

  const SHIELD_ALERT =
    '<svg viewBox="0 0 80 90">' +
    '<path fill="#E24B4A" d="M40 5 L72 20 L72 50 Q72 75 40 87 Q8 75 8 50 L8 20 Z"/>' +
    '<path fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" d="M40 30 L40 52 M40 60 L40 62"/>' +
    '</svg>';

  const SHIELD_CAUTION =
    '<svg viewBox="0 0 80 90">' +
    '<path fill="#BA7517" d="M40 5 L72 20 L72 50 Q72 75 40 87 Q8 75 8 50 L8 20 Z"/>' +
    '<circle cx="40" cy="42" r="8" fill="none" stroke="#fff" stroke-width="3"/>' +
    '<circle cx="40" cy="42" r="3" fill="#fff"/>' +
    '</svg>';

  function renderShield(state) {
    const latest = state.latest;
    const h = state.session_health || {};
    const streak = state.safe_streak || 0;
    const isAlert = latest && (latest.threat_level === "alert" || latest.threat_level === "critical");
    const isCaution = latest && (latest.threat_level === "caution" || latest.threat_level === "warning");
    const pCount = h.platform_count || 0;

    let mode, icon, title, sub;
    if (isAlert) {
      mode = "alert"; icon = SHIELD_ALERT;
      title = "Threat detected";
      sub = "Click alert to inspect";
    } else if (isCaution) {
      mode = "caution"; icon = SHIELD_CAUTION;
      title = "Watch closely";
      sub = `Monitoring ${pCount} platform${pCount===1?"":"s"}`;
    } else {
      mode = "safe"; icon = SHIELD_SAFE;
      title = "All clear";
      sub = pCount > 0 ? `Monitoring ${pCount} platform${pCount===1?"":"s"}` : (streak >= 3 ? `${streak} safe in a row` : `${h.scans||0} scans`);
    }
    els.shieldHero.className = `gl-shield-hero gl-shield-${mode}`;
    els.shieldIcon.innerHTML = icon;
    setText(els.shieldTitle, title);
    setText(els.shieldSub, sub);
    const dur = h.session_duration || "\u2014";
    setText(els.statsLine, `${dur} active \u00b7 ${pCount} platform${pCount===1?"":"s"}`);
  }

  // ----------------------------------------------------------------- header

  function renderHeader(state) {
    const mon = state.monitoring;
    const latest = state.latest;
    const isAlert = latest && (latest.threat_level === "alert" || latest.threat_level === "critical");
    let dotCls, label, extra = "";
    if (!mon) { dotCls = "gl-dot gl-dot-dim"; label = "Stopped"; }
    else if (isAlert) { dotCls = "gl-dot gl-dot-alert"; label = "Threat detected"; extra = "gl-header-status-alert"; }
    else { dotCls = "gl-dot gl-dot-safe"; label = "Active"; }
    els.headerStatus.className = `gl-header-status ${extra}`.trim();
    els.headerStatus.innerHTML = `<span class="${dotCls}"></span><span class="status-text">${esc(label)}</span>`;
    setText(els.headerDuration, state.session_duration || "0m 00s");
    setText(els.headerModel, state.model_name || "");
  }

  function renderStreak(state) {
    const s = state.safe_streak || 0;
    if (s >= 3) { els.headerStreak.classList.remove("gl-streak-hidden"); setText(els.headerStreakText, `${s} safe`); }
    else { els.headerStreak.classList.add("gl-streak-hidden"); }
  }

  // ----------------------------------------------------------------- capture

  const CAP_CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>';
  const CAP_WARN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L1 21h22L12 2zm0 7v5m0 3v1"/></svg>';
  const CAP_EYE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z"/><circle cx="12" cy="12" r="2.5" fill="currentColor"/></svg>';

  function renderCapture(state) {
    const a = state.latest;
    if (!a) {
      els.captureCard.className = "gl-capture gl-capture-safe";
      els.captureScreen.innerHTML = '<div class="gl-capture-placeholder"><div class="gl-skeleton gl-skeleton-block" style="width:100%;height:100%;position:absolute;inset:0"></div></div>';
      els.captureBarIcon.innerHTML = CAP_CHECK;
      setText(els.captureBarTitle, "Initializing");
      setText(els.captureBarSub, "");
      setText(els.captureBarTime, "--:--:--");
      els.captureBarBadge.style.display = "none";
      return;
    }
    const level = a.threat_level || "safe";
    const isAlert = level === "alert" || level === "critical";
    const isCaution = level === "caution" || level === "warning";
    const mode = isAlert ? "alert" : isCaution ? "caution" : "safe";
    els.captureCard.className = `gl-capture gl-capture-${mode}`;

    const hasChat = (a.chat_messages||[]).length > 0;
    if ((isAlert||isCaution) && hasChat) {
      els.captureScreen.innerHTML = renderChat(a);
    } else if (a.screenshot_url) {
      els.captureScreen.innerHTML = `<img class="gl-capture-img" src="${a.screenshot_url}?t=${encodeURIComponent(a.timestamp||Date.now())}" alt="">`;
    } else {
      els.captureScreen.innerHTML = `<div class="gl-capture-placeholder">${esc(a.platform||"")}</div>`;
    }

    if (isAlert) {
      els.captureBarIcon.innerHTML = CAP_WARN;
      const lbl = (a.category_label||"Threat").trim();
      const stg = a.stage_segments && a.stage_segments.current_index >= 0 ? ` - STAGE ${a.stage_segments.current_index+1}/5` : "";
      setText(els.captureBarTitle, `${lbl} detected - ${a.confidence}%${stg}`);
    } else if (isCaution) {
      els.captureBarIcon.innerHTML = CAP_EYE;
      setText(els.captureBarTitle, `${(a.category_label||"Caution").trim()} - watch closely`);
    } else {
      els.captureBarIcon.innerHTML = CAP_CHECK;
      setText(els.captureBarTitle, `All clear - No threats - ${a.platform||"Unknown"}`);
    }
    setText(els.captureBarSub, "");
    setText(els.captureBarTime, a.time_label || "--:--:--");
    els.captureBarBadge.style.display = "none";
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
    const hist = state.scan_history || [];
    const slots = 20;
    const padded = hist.slice(-slots);
    while (padded.length < slots) padded.unshift({tone:"empty"});
    els.ribbon.innerHTML = padded.map(e => `<div class="gl-ribbon-seg gl-ribbon-seg-${e.tone||"empty"}"></div>`).join("");
  }

  function renderTimeline(state) {
    const entries = state.timeline || [];
    if (!entries.length) {
      els.timeline.innerHTML = '<div class="gl-empty">Waiting for the first capture...</div>';
      return;
    }
    els.timeline.innerHTML = entries.map((e, i) => {
      const level = e.threat_level;
      const k = e.platform_key || pKey(e.platform);
      const badgeCls = level === "alert" || level === "critical" ? "gl-timeline-status-alert" :
                       level === "caution" || level === "warning" ? "gl-timeline-status-caution" :
                       "gl-timeline-status-safe";
      const time = e.time_label || "";
      const iconInner = k !== "unknown"
        ? `<img src="/static/icons/${k}.svg" alt="">`
        : `<span class="gl-timeline-icon-letter">${(e.platform||"?").charAt(0).toUpperCase()}</span>`;
      return `<div class="gl-timeline-entry" data-tl-idx="${i}" title="${esc(e.reasoning||"")}">
        <span class="gl-timeline-icon" data-platform="${k}">${iconInner}</span>
        <span class="gl-timeline-platform gl-timeline-platform-${k}">${esc(e.platform||"Unknown")}</span>
        <span class="gl-timeline-time">${esc(time)}</span>
        <span class="gl-timeline-text">${esc(trunc(e.reasoning,55))}</span>
        <span class="gl-timeline-status ${badgeCls}">${esc(level)}</span>
      </div>`;
    }).join("");
    // All timeline rows are clickable — alerts open detail, safe shows inline analysis
    window.__timelineData = entries;
    els.timeline.querySelectorAll(".gl-timeline-entry").forEach(row => {
      row.addEventListener("click", () => {
        const idx = parseInt(row.getAttribute("data-tl-idx"), 10);
        const entry = entries[idx];
        if (!entry) return;
        // Try to match alert history for full detail
        const ts = entry.time_label;
        const hist = (window.__lastState && window.__lastState.alert_history) || [];
        const match = hist.find(a => a.time_label === ts);
        if (match && match.analysis_id) {
          selectAlert(match.analysis_id);
        } else {
          // Safe/caution entry — show inline detail from timeline data
          uiState.selectedAnalysis = entry;
          els.overviewPanel.style.display = "none";
          els.detailPanel.style.display = "";
          renderRightAnalysis(window.__lastState || {});
        }
      });
    });
  }

  // ----------------------------------------------------------------- right: SAFE overview

  function renderRightPanel(state) {
    renderAlertHistory(state.alert_history || [], state.current_session_id);
  }

  function renderAlertHistory(history, sessionId) {
    if (!history.length) {
      els.historyLabel.innerHTML = `Alerts <span class="gl-history-count">0</span>`;
      els.alertHistory.innerHTML =
        `<div class="gl-history-empty">
          <div class="gl-history-empty-shield"><svg viewBox="0 0 80 90"><path fill="#1D9E75" d="M40 5 L72 20 L72 50 Q72 75 40 87 Q8 75 8 50 L8 20 Z"/><path fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" d="M25 45 L35 55 L55 35"/></svg></div>
          <div class="gl-history-empty-title">All clear</div>
          <div class="gl-history-empty-sub">No threats detected yet.\nGuardianLens is actively monitoring.</div>
        </div>`;
      return;
    }
    const newAlerts = history.filter(a => !uiState.seenAlerts.has(String(a.analysis_id)));
    const seenAlerts = history.filter(a => uiState.seenAlerts.has(String(a.analysis_id)));
    const newCount = newAlerts.length;
    const counterHtml = newCount > 0 ? `<span class="gl-history-counter">${newCount}</span>` : "";
    els.historyLabel.innerHTML = `Alerts <span class="gl-history-count">${history.length}</span>${counterHtml}`;

    let html = "";
    html += newAlerts.map(a => renderAlertCard(a, false)).join("");
    if (newAlerts.length > 0 && seenAlerts.length > 0) {
      html += '<div class="gl-history-divider">Reviewed</div>';
    }
    html += seenAlerts.map(a => renderAlertCard(a, true)).join("");
    els.alertHistory.innerHTML = html;
  }

  function renderAlertCard(a, seen) {
    const type = a.threat_type || "";
    const threatKey = (type === "grooming" || type === "bullying" || type === "inappropriate_content") ? type : "other";
    let icon = CARD_ICON_DEFAULT;
    if (type === "grooming") icon = CARD_ICON_GROOMING;
    else if (type === "bullying") icon = CARD_ICON_BULLYING;
    else if (type === "inappropriate_content") icon = CARD_ICON_CONTENT;

    const stateClass = seen ? "gl-alert-card-seen" : "gl-alert-card-new";

    const badgeHtml = seen
      ? ""
      : `<span class="gl-alert-card-badge">NEW</span>`;

    const pills = (a.indicators||[]).slice(0,3).map(p =>
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
      stageHtml = `<div class="gl-alert-card-stage-mini">${segs}<span class="gl-alert-card-stage-label">${stageIdx}/5</span></div>`;
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
        <span class="gl-alert-card-user">${esc(a.user)}</span>
        <span class="gl-alert-card-sep">\u2022</span>
        <span class="gl-alert-card-summary">${esc(a.summary)}</span>
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
    renderTelegram(a);
  }

  function renderAnalysisCard(a) {
    const cat = a.category || "";
    const color = cat === "grooming" ? "#E24B4A" : cat === "bullying" ? "#BA7517" : cat === "inappropriate_content" ? "#D85A30" : "#E24B4A";
    const title = a.category_label ? `${a.category_label} detected` : "Threat detected";
    const conv = a.conversation || {};
    const meta = `${conv.username||"\u2014"} \u203a child \u00b7 ${a.platform||"Unknown"}`;
    const pills = (a.indicator_pills||a.indicators||[]).slice(0,6).map(p => {
      const l = typeof p==="string"?p:p.label;
      return `<span class="gl-analysis-card-pill" style="background:${color}22;color:${color}">${esc(trunc(l,32))}</span>`;
    }).join("");
    let stagebar = "";
    if (a.stage_segments && Array.isArray(a.stage_segments.segments)) {
      stagebar = `<div class="gl-analysis-card-stagebar">${a.stage_segments.segments.map(s => {
        const c = s.state==="active"?"gl-analysis-stage-seg-active":s.state==="current"?"gl-analysis-stage-seg-current":"";
        return `<div class="gl-analysis-stage-seg ${c}"></div>`;
      }).join("")}</div>`;
    }
    els.analysisCard.innerHTML = `
      <div class="gl-analysis-card-header">
        <div class="gl-analysis-card-titles">
          <div class="gl-analysis-card-title" style="color:${color}">${esc(title)}</div>
          <div class="gl-analysis-card-meta">${esc(meta)}</div>
        </div>
        <div class="gl-analysis-card-confidence">
          <div class="gl-analysis-card-conf-value" style="color:${color}">${a.confidence}%</div>
          <div class="gl-analysis-card-conf-label">CONFIDENCE</div>
        </div>
      </div>
      <div class="gl-analysis-card-pills">${pills}</div>
      ${stagebar}`;
  }

  function renderReasoning(a) {
    const steps = (a&&a.reasoning_chain)||[];
    if (!steps.length) { els.reasoningChain.innerHTML = '<div class="gl-empty">No reasoning.</div>'; return; }
    els.reasoningChain.innerHTML = steps.map(s => {
      if (s.type==="verdict") return `<span class="gl-reasoning-step-verdict">${esc(s.text)}</span>`;
      if (s.type==="flag") return `<span class="gl-reasoning-step-flag">&nbsp;&nbsp;&gt; ${esc(s.text)}</span>`;
      const lbl = s.label ? `<span class="gl-reasoning-step-label">${esc(s.label)}:</span> ` : "";
      return `${lbl}<span class="gl-reasoning-step-text">${esc(s.text)}</span>`;
    }).join("<br>");
  }

  function renderWhy(a) {
    const t = a&&a.why_this_matters;
    if (!t) { els.whyThisMatters.innerHTML = '<div class="gl-empty">\u2014</div>'; return; }
    els.whyThisMatters.innerHTML = `<div class="gl-why-text">${esc(t)}</div>`;
  }

  function renderFlagged(a) {
    const bd = (a&&a.threat_breakdown)||[];
    const wq = bd.filter(b=>b.quote);
    if (!wq.length) { els.flaggedLabel.style.display="none"; els.flaggedMessages.style.display="none"; return; }
    els.flaggedLabel.style.display=""; els.flaggedMessages.style.display="";
    const cat = a.category||"";
    const color = cat==="grooming"?"#E24B4A":cat==="bullying"?"#BA7517":"#D85A30";
    els.flaggedMessages.innerHTML = wq.map(item =>
      `<div class="gl-flagged-msg"><div class="gl-flagged-msg-body"><span class="gl-flagged-msg-quote" style="color:${color}">"${esc(trunc(item.quote,80))}"</span><span class="gl-flagged-msg-explanation">${esc(item.explanation||item.title||"")}</span></div></div>`
    ).join("");
  }

  function renderAction(a) {
    const action = a&&a.recommended_action;
    if (!action) { els.recommendedAction.innerHTML='<div class="gl-empty">\u2014</div>'; els.recommendedAction.className="gl-action"; return; }
    const cat = a.category||"";
    const color = cat==="grooming"?"#E24B4A":cat==="bullying"?"#BA7517":cat==="inappropriate_content"?"#D85A30":"#7F77DD";
    const bg = cat==="grooming"?"#2a1a1a":cat==="bullying"?"#1f1a0f":cat==="inappropriate_content"?"#2a1a0f":"#1e1e32";
    const borderClass = cat==="grooming"?"gl-action-grooming":cat==="bullying"?"gl-action-bullying":cat==="inappropriate_content"?"gl-action-inappropriate":"gl-action-other";
    els.recommendedAction.className = `gl-action ${borderClass}`;
    const label = `<div class="gl-action-label" style="color:${color}">Recommended action for parent<button class="gl-action-dismiss" id="action-dismiss" type="button" title="Dismiss">\u00d7</button></div>`;
    const steps = (action.steps||[]).map((s,i) =>
      `<div class="gl-action-step"><span class="gl-action-num" style="background:${bg};color:${color}">${i+1}</span><span class="gl-action-text">${esc(s)}</span></div>`
    ).join("");
    const priv = action.privacy_note ? `<div class="gl-action-privacy">${esc(action.privacy_note)}</div>` : "";
    els.recommendedAction.innerHTML = label + steps + priv;
    const dismissBtn = document.getElementById("action-dismiss");
    if (dismissBtn) dismissBtn.addEventListener("click", (e) => { e.stopPropagation(); showOverview(); });
  }

  function renderTelegram(a) {
    const alert = a&&a.parent_alert;
    if (!alert) { els.telegramBlock.innerHTML=""; return; }
    const at = alert.delivered_at ? fmtDelivered(alert.delivered_at) : fmtTime();
    els.telegramBlock.innerHTML = `
      <div class="gl-telegram-card">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#1D9E75" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
        <span class="gl-telegram-label">Parent alert generated \u00b7 ${esc(at)}</span>
        <span class="gl-telegram-sent-badge">Ready</span>
      </div>`;
  }

  function fmtDelivered(iso) {
    if (!iso) return fmtTime();
    try { const d = new Date(iso); return isNaN(d.getTime()) ? fmtTime() : d.toTimeString().slice(0,8); } catch(_) { return fmtTime(); }
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

    renderHeader(state);
    renderStreak(state);
    renderShield(state);
    renderCapture(state);
    renderRibbon(state);
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
    setText(els.footerDb, state.db_path);
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
    const node = document.getElementById("initial-state");
    if (node) try { render(JSON.parse(node.textContent)); } catch(_) {}
    connectStream();
  });
})();
