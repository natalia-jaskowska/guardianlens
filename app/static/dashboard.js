/**
 * GuardianLens dashboard front-end.
 *
 * Connects to /api/stream over Server-Sent Events. Each event payload
 * is the full state snapshot built by app.state.AppState.build_state().
 *
 * The right panel has two states managed by `uiState`:
 *
 *   1. SAFE overview     — All clear card + alert history list
 *   2. FULL ANALYSIS     — Reasoning chain + flagged messages + recommended action
 *
 * Auto-transitions:
 *   - new alert lands       → ANALYSIS (auto)  unless user manually navigated
 *   - next safe scan        → SAFE      (auto)  unless user manually navigated
 *
 * Manual navigation:
 *   - click an alert card   → ANALYSIS (manual, fetches full data via /api/analysis/{id})
 *   - click "← Back"        → SAFE     (clears manual flag)
 *
 * Vanilla JS, no build step, no framework. ~400 lines.
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

    metricScreenshots: document.getElementById("metric-screenshots"),
    metricSafe: document.getElementById("metric-safe"),
    metricCaution: document.getElementById("metric-caution"),
    metricAlerts: document.getElementById("metric-alerts"),
    metricScreenshotsSub: document.getElementById("metric-screenshots-sub"),
    metricSafeSub: document.getElementById("metric-safe-sub"),
    metricCautionSub: document.getElementById("metric-caution-sub"),
    metricAlertsSub: document.getElementById("metric-alerts-sub"),
    metricSparkline: document.getElementById("metric-sparkline"),

    captureCard: document.getElementById("capture-card"),
    captureThumb: document.getElementById("capture-thumb"),
    captureStatusText: document.getElementById("capture-status-text"),
    captureLine: document.getElementById("capture-line"),
    captureMetaLine: document.getElementById("capture-meta-line"),

    heartbeat: document.getElementById("heartbeat"),
    timeline: document.getElementById("timeline"),
    lastRefresh: document.getElementById("last-refresh"),

    // Right panel - safe overview
    rightSafe: document.getElementById("right-safe"),
    allclearTitle: document.getElementById("allclear-title"),
    allclearSub: document.getElementById("allclear-sub"),
    miniStatMonitored: document.getElementById("mini-stat-monitored"),
    miniStatPlatforms: document.getElementById("mini-stat-platforms"),
    historyLabel: document.getElementById("history-label"),
    alertHistory: document.getElementById("alert-history"),
    historicalAction: document.getElementById("historical-action"),
    historicalActionBody: document.getElementById("historical-action-body"),
    telegramSummary: document.getElementById("telegram-summary"),
    telegramSummaryText: document.getElementById("telegram-summary-text"),

    // Right panel - full analysis
    rightAnalysis: document.getElementById("right-analysis"),
    analysisBack: document.getElementById("analysis-back"),
    analysisLiveBanner: document.getElementById("analysis-live-banner"),
    analysisTimestampLabel: document.getElementById("analysis-timestamp-label"),
    analysisCard: document.getElementById("analysis-card"),
    reasoningChain: document.getElementById("reasoning-chain"),
    whyThisMatters: document.getElementById("why-this-matters"),
    flaggedLabel: document.getElementById("flagged-label"),
    flaggedMessages: document.getElementById("flagged-messages"),
    recommendedAction: document.getElementById("recommended-action"),
    telegramBlock: document.getElementById("telegram-block"),

    footerModel: document.getElementById("footer-model"),
    footerDb: document.getElementById("footer-db"),
  };

  // ----------------------------------------------------------------- helpers

  const escapeHtml = (str) => {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  };

  const truncate = (str, limit) => {
    if (!str) return "";
    str = str.replace(/\s+/g, " ").trim();
    return str.length > limit ? str.slice(0, limit - 1).trimEnd() + "..." : str;
  };

  const setText = (el, text) => {
    if (el && el.textContent !== text) el.textContent = text;
  };

  const formatTime = (date = new Date()) => date.toTimeString().slice(0, 8);

  // ----------------------------------------------------------------- platform badges

  function platformKey(platformText) {
    if (!platformText) return null;
    const lower = platformText.toLowerCase();
    if (lower.includes("instagram")) return "instagram";
    if (lower.includes("tiktok")) return "tiktok";
    if (lower.includes("discord")) return "discord";
    if (lower.includes("minecraft")) return "minecraft";
    if (lower.includes("roblox")) return "roblox";
    if (lower.includes("snap")) return "snapchat";
    if (lower.includes("telegram")) return "telegram";
    return null;
  }

  function renderPlatformBadge(platformText) {
    const key = platformKey(platformText);
    const title = escapeHtml(platformText || "Unknown");
    if (!key) {
      return `<span class="gl-platform-badge gl-platform-badge-unknown" title="${title}">?</span>`;
    }
    return `<span class="gl-platform-badge gl-platform-badge-${key}" title="${title}"><img src="/static/icons/${key}.svg" alt=""></span>`;
  }

  // ----------------------------------------------------------------- view state machine

  const uiState = {
    view: "safe", // "safe" or "analysis"
    selectedAnalysis: null,
    manualNavigation: false,
    lastAutoAlertId: null,
    autoTriggered: false,
  };

  function decideView(state) {
    const latest = state.latest;
    const isLatestAlert =
      latest && (latest.threat_level === "alert" || latest.threat_level === "critical");
    const latestId = isLatestAlert ? latest.timestamp : null;

    // Manual navigation persists — user is inspecting something specific.
    if (uiState.manualNavigation) {
      return;
    }

    if (isLatestAlert && latestId !== uiState.lastAutoAlertId) {
      // New alert — auto-switch to analysis view
      uiState.view = "analysis";
      uiState.selectedAnalysis = latest;
      uiState.lastAutoAlertId = latestId;
      uiState.autoTriggered = true;
    } else if (!isLatestAlert && uiState.view === "analysis" && uiState.autoTriggered) {
      // Latest scan is safe and the previous analysis view was auto-
      // triggered — slide back to overview.
      uiState.view = "safe";
      uiState.selectedAnalysis = null;
      uiState.autoTriggered = false;
    }
  }

  async function selectAlert(analysisId) {
    // User clicked an alert history card. Fetch the full analysis from
    // the server and switch to the analysis view.
    try {
      const response = await fetch(`/api/analysis/${analysisId}`);
      if (!response.ok) {
        console.warn("[guardlens] failed to fetch analysis", analysisId);
        return;
      }
      const analysis = await response.json();
      uiState.manualNavigation = true;
      uiState.autoTriggered = false;
      uiState.view = "analysis";
      uiState.selectedAnalysis = analysis;
      // Render immediately, the next SSE tick will refresh the rest.
      render(window.__lastState || {});
    } catch (err) {
      console.warn("[guardlens] selectAlert error", err);
    }
  }

  function returnToOverview() {
    uiState.manualNavigation = false;
    uiState.autoTriggered = false;
    uiState.view = "safe";
    uiState.selectedAnalysis = null;
    render(window.__lastState || {});
  }

  // ----------------------------------------------------------------- header + metrics + capture

  function renderHeader(state) {
    const monitoring = state.monitoring;
    const dotClass = monitoring ? "gl-dot gl-dot-safe" : "gl-dot gl-dot-dim";
    const label = monitoring ? "Active" : "Stopped";
    els.headerStatus.innerHTML = `<span class="${dotClass}"></span><span>${escapeHtml(label)}</span>`;
    setText(els.headerDuration, state.session_duration || "0m 00s");
    setText(els.headerModel, state.model_name || "");
  }

  function renderStreak(state) {
    const streak = state.safe_streak || 0;
    if (streak >= 3) {
      els.headerStreak.classList.remove("gl-streak-hidden");
      setText(els.headerStreakText, `${streak} safe in a row`);
    } else {
      els.headerStreak.classList.add("gl-streak-hidden");
    }
  }

  function renderMetrics(state) {
    const m = state.metrics || { screenshots: 0, safe: 0, caution: 0, alerts: 0 };
    setText(els.metricScreenshots, m.screenshots);
    setText(els.metricSafe, m.safe);
    setText(els.metricCaution, m.caution);
    setText(els.metricAlerts, m.alerts);

    const sub = state.metric_sublabels || {};
    setText(els.metricScreenshotsSub, sub.screenshots || "");
    setText(els.metricSafeSub, sub.safe || "");
    setText(els.metricCautionSub, sub.caution || "");
    setText(els.metricAlertsSub, sub.alerts || "");

    renderSparkline(state.scan_history || []);
  }

  function renderSparkline(history) {
    const slots = 12;
    const padded = history.slice(-slots);
    while (padded.length < slots) padded.unshift({ tone: "empty" });
    const html = padded
      .map((entry, i) => {
        const tone = entry.tone || "empty";
        const cls = tone === "empty" ? "" : `gl-spark-bar-${tone}`;
        const height = 6 + Math.round((i / (slots - 1)) * 12);
        return `<span class="gl-spark-bar ${cls}" style="height:${height}px"></span>`;
      })
      .join("");
    els.metricSparkline.innerHTML = html;
  }

  function renderCapture(state) {
    const a = state.latest;
    if (!a) {
      els.captureCard.className = "gl-capture-simple";
      els.captureThumb.innerHTML = '<div class="gl-capture-thumb-placeholder">Waiting...</div>';
      setText(els.captureStatusText, "Initializing");
      setText(els.captureLine, "Connecting to monitor stream...");
      setText(els.captureMetaLine, "—");
      return;
    }

    const level = a.threat_level || "safe";
    const isAlert = level === "alert" || level === "critical";
    const isCaution = level === "caution" || level === "warning";

    let cardClass = "gl-capture-simple";
    if (isAlert) cardClass += " gl-capture-alert";
    else if (isCaution) cardClass += " gl-capture-caution";
    els.captureCard.className = cardClass;

    // Thumbnail
    if (a.screenshot_url) {
      const src = `${a.screenshot_url}?t=${encodeURIComponent(a.timestamp || Date.now())}`;
      els.captureThumb.innerHTML = `<img src="${src}" alt="">`;
    } else {
      els.captureThumb.innerHTML = `<div class="gl-capture-thumb-placeholder">${escapeHtml(a.platform || "—")}</div>`;
    }

    // Status text
    const statusText = isAlert
      ? `${a.category_label || "Threat"} detected`
      : isCaution
      ? `${a.category_label || "Caution"} — caution`
      : "All clear";
    setText(els.captureStatusText, statusText);

    // Reasoning one-liner
    const oneLiner = isAlert || isCaution
      ? truncate(a.reasoning || "", 80)
      : "Normal activity. No chat or social interaction detected.";
    setText(els.captureLine, oneLiner);

    // Meta line
    const meta = `${a.time_label || "—"} · ${a.platform || "Unknown"}`;
    setText(els.captureMetaLine, meta);
  }

  // ----------------------------------------------------------------- heartbeat + timeline

  function renderHeartbeat(state) {
    const history = state.scan_history || [];
    const slots = 30;
    const padded = history.slice(-slots);
    while (padded.length < slots) padded.unshift({ tone: "empty" });
    els.heartbeat.innerHTML = padded
      .map((entry) => {
        const tone = entry.tone || "empty";
        const cls = tone === "empty" ? "" : `gl-heartbeat-bar-${tone}`;
        const height =
          tone === "alert"
            ? 90
            : tone === "caution"
            ? 40
            : tone === "safe"
            ? 14
            : 8;
        return `<div class="gl-heartbeat-bar ${cls}" style="height:${height}%"></div>`;
      })
      .join("");
  }

  function renderTimeline(state) {
    const entries = state.timeline || [];
    if (!entries.length) {
      els.timeline.innerHTML = '<div class="gl-empty">Waiting for the first capture...</div>';
      return;
    }
    const html = entries
      .map((e) => {
        const level = e.threat_level;
        const dotCls = `gl-dot gl-dot-${level}`;
        const badge = renderPlatformBadge(e.platform);
        const text = `${escapeHtml(e.platform)} — ${escapeHtml(truncate(e.reasoning, 60))}`;
        const statusCls = `gl-timeline-status gl-timeline-status-${level}`;
        const timeAgo = e.time_label || "now";
        return `
          <div class="gl-timeline-entry gl-timeline-entry-${level}">
            <span class="${dotCls}"></span>
            ${badge}
            <span class="gl-timeline-time">${escapeHtml(timeAgo)}</span>
            <span class="gl-timeline-text">${text}</span>
            <span class="${statusCls}">${escapeHtml(level)}</span>
          </div>`;
      })
      .join("");
    els.timeline.innerHTML = html;
  }

  // ----------------------------------------------------------------- right panel: SAFE overview

  function renderRightSafe(state) {
    const h = state.session_health || {};
    const streak = state.safe_streak || 0;

    setText(els.allclearTitle, h.clean ? "All clear" : "Watch closely");
    setText(els.allclearSub, streak >= 3 ? `${streak} safe in a row` : `${h.scans || 0} scans this session`);

    setText(els.miniStatMonitored, h.session_duration || "—");
    setText(els.miniStatPlatforms, h.platform_count || "—");

    renderAlertHistory(state.alert_history || []);

    // Historical action from latest alert (dimmed)
    const lastAlert = state.latest_alert;
    if (lastAlert && lastAlert.recommended_action && lastAlert.recommended_action.steps) {
      const steps = lastAlert.recommended_action.steps;
      els.historicalActionBody.innerHTML = steps
        .map((s, i) => `${i + 1}. ${escapeHtml(s)}`)
        .join("<br>");
      els.historicalAction.style.display = "";
    } else {
      els.historicalAction.style.display = "none";
    }

    // Telegram summary one-liner
    const totals = state.metrics || {};
    if (totals.alerts > 0) {
      setText(
        els.telegramSummaryText,
        `Telegram: ${totals.alerts} alert${totals.alerts === 1 ? "" : "s"} sent`,
      );
      els.telegramSummary.style.display = "";
    } else {
      els.telegramSummary.style.display = "none";
    }
  }

  function renderAlertHistory(history) {
    setText(els.historyLabel, `Alert history (${history.length})`);
    if (!history.length) {
      els.alertHistory.innerHTML =
        '<div class="gl-history-empty">No alerts yet — your child is safe.</div>';
      return;
    }
    els.alertHistory.innerHTML = history
      .map((alert, idx) => renderAlertCard(alert, idx))
      .join("");
    // Wire up click handlers
    els.alertHistory.querySelectorAll("[data-analysis-id]").forEach((card) => {
      card.addEventListener("click", () => {
        const id = card.getAttribute("data-analysis-id");
        if (id) selectAlert(id);
      });
    });
  }

  function renderAlertCard(alert, idx) {
    const severityClass = alert.severity === "caution" ? "gl-alert-card-caution" : "";
    const fadeClass = idx >= 3 ? "gl-alert-card-faded" : "";
    const badge = renderPlatformBadge(alert.platform);
    const pills = (alert.indicators || [])
      .slice(0, 3)
      .map((p) => `<span class="gl-alert-card-pill">${escapeHtml(p)}</span>`)
      .join("");
    return `
      <div class="gl-alert-card ${severityClass} ${fadeClass}" data-analysis-id="${alert.analysis_id}">
        <div class="gl-alert-card-row1">
          <div class="gl-alert-card-titlebar">
            ${badge.replace("gl-platform-badge", "gl-platform-badge gl-alert-card-platform")}
            <span class="gl-alert-card-title">${escapeHtml(alert.threat_label)} — ${alert.confidence}%</span>
          </div>
          <span class="gl-alert-card-time">${escapeHtml(alert.time_ago)}</span>
        </div>
        <div class="gl-alert-card-summary">${escapeHtml(alert.user)} — ${escapeHtml(alert.summary)}</div>
        <div class="gl-alert-card-row3">
          <div class="gl-alert-card-pills">${pills}</div>
          <span class="gl-alert-card-arrow">→</span>
        </div>
      </div>`;
  }

  // ----------------------------------------------------------------- right panel: FULL ANALYSIS

  function renderRightAnalysis(state) {
    const a = uiState.selectedAnalysis;
    if (!a) {
      // Nothing selected — fall back to whatever's latest
      els.analysisCard.innerHTML =
        '<div class="gl-empty">No analysis to display.</div>';
      return;
    }

    // Show "back" button only when manually navigated
    els.analysisBack.style.display = uiState.manualNavigation ? "" : "none";
    // Show LIVE ALERT banner only when auto-triggered
    els.analysisLiveBanner.style.display = uiState.autoTriggered ? "" : "none";

    setText(els.analysisTimestampLabel, `Alert detail · ${a.time_label || "—"}`);

    // Render the alert summary card
    renderAnalysisCard(a);
    renderReasoningChain(a);
    renderWhyThisMatters(a);
    renderFlaggedMessages(a);
    renderRecommendedAction(a);
    renderTelegramCard(a);
  }

  function renderAnalysisCard(a) {
    const cls = a.threat_level || "safe";
    const isCaution = cls === "caution" || cls === "warning";
    const cardClass = isCaution ? "gl-analysis-card gl-analysis-card-caution" : "gl-analysis-card";
    const title = (a.category_label || "THREAT") + (cls === "alert" || cls === "critical" ? " DETECTED" : "");
    const conv = a.conversation || {};
    const meta = `${conv.username || "—"} → child · ${a.platform || "Unknown"}`;

    const pills = (a.indicator_pills || a.indicators || [])
      .slice(0, 6)
      .map((p) => {
        const label = typeof p === "string" ? p : p.label;
        return `<span class="gl-analysis-card-pill">${escapeHtml(truncate(label, 32))}</span>`;
      })
      .join("");

    // Stage bar
    let stagebarHtml = "";
    if (a.stage_segments && Array.isArray(a.stage_segments.segments)) {
      stagebarHtml = `<div class="gl-analysis-card-stagebar">${a.stage_segments.segments
        .map((seg) => {
          const c =
            seg.state === "active"
              ? "gl-analysis-stage-seg gl-analysis-stage-seg-active"
              : seg.state === "current"
              ? "gl-analysis-stage-seg gl-analysis-stage-seg-current"
              : "gl-analysis-stage-seg";
          return `<div class="${c}"></div>`;
        })
        .join("")}</div>`;
    }

    els.analysisCard.className = cardClass;
    els.analysisCard.innerHTML = `
      <div class="gl-analysis-card-header">
        <div class="gl-analysis-card-titles">
          <div class="gl-analysis-card-title">${escapeHtml(title)}</div>
          <div class="gl-analysis-card-meta">${escapeHtml(meta)}</div>
        </div>
        <div class="gl-analysis-card-confidence">
          <span class="gl-analysis-card-conf-value">${a.confidence}%</span>
          <span class="gl-analysis-card-conf-label">Confidence</span>
        </div>
      </div>
      <div class="gl-analysis-card-pills">${pills}</div>
      ${stagebarHtml}
    `;
  }

  function renderReasoningChain(a) {
    const steps = (a && a.reasoning_chain) || [];
    if (!steps.length) {
      els.reasoningChain.innerHTML = '<div class="gl-empty">No reasoning chain.</div>';
      return;
    }
    const parts = steps.map((step) => {
      if (step.type === "verdict") {
        return `<span class="gl-reasoning-step-verdict">${escapeHtml(step.text)}</span>`;
      }
      if (step.type === "flag") {
        return `<span class="gl-reasoning-step-flag">&nbsp;&nbsp;${escapeHtml(step.text)}</span>`;
      }
      const labelHtml = step.label
        ? `<span class="gl-reasoning-step-label">${escapeHtml(step.label)}:</span> `
        : "";
      return `${labelHtml}<span class="gl-reasoning-step-text">${escapeHtml(step.text)}</span>`;
    });
    els.reasoningChain.innerHTML = parts.join("<br>");
  }

  function renderWhyThisMatters(a) {
    const text = a && a.why_this_matters;
    if (!text) {
      els.whyThisMatters.innerHTML = '<div class="gl-empty">—</div>';
      return;
    }
    els.whyThisMatters.innerHTML = `<div class="gl-why-text">${escapeHtml(text)}</div>`;
  }

  function renderFlaggedMessages(a) {
    const breakdown = (a && a.threat_breakdown) || [];
    const withQuotes = breakdown.filter((b) => b.quote);
    if (!withQuotes.length) {
      els.flaggedLabel.style.display = "none";
      els.flaggedMessages.style.display = "none";
      return;
    }
    els.flaggedLabel.style.display = "";
    els.flaggedMessages.style.display = "";
    els.flaggedMessages.innerHTML = withQuotes
      .map(
        (item, idx) => `
        <div class="gl-flagged-msg">
          <div class="gl-flagged-msg-num">${idx + 1}</div>
          <div class="gl-flagged-msg-body">
            <span class="gl-flagged-msg-quote">"${escapeHtml(truncate(item.quote, 80))}"</span>
            <span class="gl-flagged-msg-explanation">${escapeHtml(item.explanation || item.title || "")}</span>
          </div>
        </div>`,
      )
      .join("");
  }

  function renderRecommendedAction(a) {
    const action = a && a.recommended_action;
    if (!action) {
      els.recommendedAction.innerHTML = '<div class="gl-empty">—</div>';
      return;
    }
    const steps = (action.steps || [])
      .map(
        (step, idx) => `
        <div class="gl-action-step">
          <div class="gl-action-num">${idx + 1}</div>
          <div class="gl-action-text">${escapeHtml(step)}</div>
        </div>`,
      )
      .join("");
    const privacy = action.privacy_note
      ? `<div class="gl-action-privacy">${escapeHtml(action.privacy_note)}</div>`
      : "";
    els.recommendedAction.innerHTML = steps + privacy;
  }

  function renderTelegramCard(a) {
    const alert = a && a.parent_alert;
    if (!alert) {
      els.telegramBlock.innerHTML = "";
      return;
    }
    const deliveredAt = formatDeliveredAt(alert.delivered_at);
    els.telegramBlock.innerHTML = `
      <div class="gl-telegram-card">
        <div class="gl-telegram-header">
          <img class="gl-telegram-icon" width="9" height="9" src="/static/icons/telegram.svg" alt="">
          <span class="gl-telegram-label">Telegram alert delivered</span>
        </div>
        <div class="gl-telegram-message">"${escapeHtml(alert.summary)}"</div>
        <div class="gl-telegram-meta">Delivered ${escapeHtml(deliveredAt)} · read receipt pending</div>
      </div>`;
  }

  function formatDeliveredAt(iso) {
    if (!iso) return formatTime();
    try {
      const d = new Date(iso);
      if (isNaN(d.getTime())) return formatTime();
      return d.toTimeString().slice(0, 8);
    } catch (_) {
      return formatTime();
    }
  }

  // ----------------------------------------------------------------- alert notifications

  const notify = (() => {
    let audioCtx = null;
    let audioUnlocked = false;
    let lastAlertTs = null;
    let initialized = false;
    let permissionRequested = false;

    const ensureContext = () => {
      if (audioCtx) return audioCtx;
      const Ctor = window.AudioContext || window.webkitAudioContext;
      if (!Ctor) return null;
      try {
        audioCtx = new Ctor();
        return audioCtx;
      } catch (_) {
        return null;
      }
    };
    const unlockAudio = async () => {
      if (audioUnlocked) return true;
      const ctx = ensureContext();
      if (!ctx) return false;
      if (ctx.state === "suspended") {
        try { await ctx.resume(); } catch (_) {}
      }
      audioUnlocked = ctx.state === "running";
      return audioUnlocked;
    };
    document.addEventListener("click", unlockAudio, { once: false });
    document.addEventListener("keydown", unlockAudio, { once: false });

    const playDing = () => {
      if (!audioCtx || audioCtx.state !== "running") return;
      const t0 = audioCtx.currentTime;
      [
        { freq: 880, start: 0.0, dur: 0.35 },
        { freq: 1320, start: 0.1, dur: 0.4 },
      ].forEach((tone) => {
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type = "sine";
        osc.frequency.value = tone.freq;
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        const start = t0 + tone.start;
        gain.gain.setValueAtTime(0, start);
        gain.gain.linearRampToValueAtTime(0.25, start + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.001, start + tone.dur);
        osc.start(start);
        osc.stop(start + tone.dur + 0.05);
      });
    };

    const showBrowserNotification = (alertState) => {
      if (typeof Notification === "undefined") return;
      if (Notification.permission !== "granted") return;
      const pa = (alertState && alertState.parent_alert) || {};
      const title = pa.title ? `GuardianLens — ${pa.title}` : "GuardianLens — safety alert";
      const body =
        pa.summary ||
        `${alertState.category_label || "Threat"} detected on ${alertState.platform || "an app"}`;
      try {
        const n = new Notification(title, { body, tag: "guardlens-alert", silent: false });
        n.onclick = () => { window.focus(); n.close(); };
        setTimeout(() => { try { n.close(); } catch (_) {} }, 8000);
      } catch (_) {}
    };

    const requestPermission = () => {
      if (permissionRequested) return;
      permissionRequested = true;
      if (typeof Notification === "undefined") return;
      if (Notification.permission === "default") {
        try { Notification.requestPermission(); } catch (_) {}
      }
    };

    const handle = (state) => {
      requestPermission();
      const a = state && state.latest;
      const isAlert = a && (a.threat_level === "alert" || a.threat_level === "critical");
      const ts = isAlert ? a.timestamp : null;
      if (!initialized) {
        initialized = true;
        lastAlertTs = ts || null;
        return;
      }
      if (!ts) return;
      if (ts === lastAlertTs) return;
      lastAlertTs = ts;
      playDing();
      showBrowserNotification(a);
    };

    return { handle, test: async () => { await unlockAudio(); playDing(); } };
  })();
  window.notify = notify;

  // ----------------------------------------------------------------- top-level render

  function render(state) {
    if (!state) return;
    window.__lastState = state;
    document.body.classList.toggle("loaded", true);
    notify.handle(state);

    // Wow alert atmosphere — only when CURRENT scan is alert
    const latest = state.latest;
    const isAlertNow =
      latest && (latest.threat_level === "alert" || latest.threat_level === "critical");
    if (isAlertNow) {
      els.shell.classList.add("gl-alert-active");
    } else {
      els.shell.classList.remove("gl-alert-active");
    }

    renderHeader(state);
    renderStreak(state);
    renderMetrics(state);
    renderCapture(state);
    renderHeartbeat(state);
    renderTimeline(state);

    decideView(state);
    if (uiState.view === "safe") {
      els.rightSafe.style.display = "";
      els.rightAnalysis.style.display = "none";
      renderRightSafe(state);
    } else {
      els.rightSafe.style.display = "none";
      els.rightAnalysis.style.display = "";
      renderRightAnalysis(state);
    }

    setText(els.lastRefresh, formatTime());
    setText(els.footerModel, state.model_name);
    setText(els.footerDb, state.db_path);
  }

  // ----------------------------------------------------------------- bootstrap

  function loadInitialState() {
    const node = document.getElementById("initial-state");
    if (!node) return null;
    try {
      return JSON.parse(node.textContent);
    } catch (err) {
      console.warn("Failed to parse initial state", err);
      return null;
    }
  }

  function connectStream() {
    const source = new EventSource("/api/stream");
    source.onmessage = (event) => {
      try {
        const state = JSON.parse(event.data);
        render(state);
      } catch (err) {
        console.error("Bad SSE payload", err, event.data);
      }
    };
    source.onerror = () => {
      console.warn("SSE connection dropped, retrying...");
    };
    return source;
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (els.analysisBack) {
      els.analysisBack.addEventListener("click", returnToOverview);
    }
    const initial = loadInitialState();
    if (initial) render(initial);
    connectStream();
  });
})();
