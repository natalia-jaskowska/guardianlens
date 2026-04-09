/**
 * GuardianLens dashboard front-end.
 *
 * Connects to /api/stream over Server-Sent Events. Each event payload
 * is the full state snapshot built by app.state.AppState.build_state().
 * Render functions translate that snapshot into DOM updates.
 *
 * Vanilla JS, no build step. ~250 lines including comments.
 */

(() => {
  "use strict";

  // ----------------------------------------------------------------- DOM refs

  const els = {
    shell: document.getElementById("shell"),
    headerStatus: document.getElementById("header-status"),
    headerDuration: document.getElementById("header-duration"),
    headerModel: document.getElementById("header-model"),
    metricScreenshots: document.getElementById("metric-screenshots"),
    metricSafe: document.getElementById("metric-safe"),
    metricCaution: document.getElementById("metric-caution"),
    metricAlerts: document.getElementById("metric-alerts"),
    metricScreenshotsSub: document.getElementById("metric-screenshots-sub"),
    metricSafeSub: document.getElementById("metric-safe-sub"),
    metricCautionSub: document.getElementById("metric-caution-sub"),
    metricAlertsSub: document.getElementById("metric-alerts-sub"),
    metricSparkline: document.getElementById("metric-sparkline"),
    fakeBrowser: document.getElementById("fake-browser"),
    browserUrl: document.getElementById("browser-url"),
    browserContent: document.getElementById("browser-content"),
    breakdownCard: document.getElementById("breakdown-card"),
    breakdownTitle: document.getElementById("breakdown-title"),
    breakdownSubtitle: document.getElementById("breakdown-subtitle"),
    breakdownConfidence: document.getElementById("breakdown-confidence"),
    breakdownPills: document.getElementById("breakdown-pills"),
    breakdownStageWrap: document.getElementById("breakdown-stage-wrap"),
    breakdownStagebar: document.getElementById("breakdown-stagebar"),
    breakdownStagelabels: document.getElementById("breakdown-stagelabels"),
    breakdownStatboxes: document.getElementById("breakdown-statboxes"),
    scanStrip: document.getElementById("breakdown-scan-strip"),
    scanStripBars: document.getElementById("scan-strip-bars"),
    scanStripCounts: document.getElementById("scan-strip-counts"),
    timeline: document.getElementById("timeline"),
    sessionHealth: document.getElementById("session-health"),
    healthTitle: document.getElementById("health-title"),
    healthSummary: document.getElementById("health-summary"),
    healthPlatforms: document.getElementById("health-platforms"),
    healthModelText: document.getElementById("health-model-text"),
    alertStack: document.getElementById("alert-stack"),
    reasoningChain: document.getElementById("reasoning-chain"),
    whyThisMatters: document.getElementById("why-this-matters"),
    recommendedAction: document.getElementById("recommended-action"),
    telegramBlock: document.getElementById("telegram-block"),
    headerStreak: document.getElementById("header-streak"),
    headerStreakText: document.getElementById("header-streak-text"),
    privacySubtitle: document.getElementById("privacy-subtitle"),
    lastRefresh: document.getElementById("last-refresh"),
    footerModel: document.getElementById("footer-model"),
    footerDb: document.getElementById("footer-db"),
  };

  // ----------------------------------------------------------------- platform badges

  // Resolve a platform name (possibly with section like "Instagram DM")
  // to an SVG icon file in /static/icons/. Adding a new platform = drop
  // a new SVG into the folder + add one line here.
  function platformBadgeFor(platformText) {
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
    const key = platformBadgeFor(platformText);
    const title = escapeHtml(platformText || "Unknown");
    if (!key) {
      return `<span class="gl-platform-badge gl-platform-badge-unknown" title="${title}">?</span>`;
    }
    return `<span class="gl-platform-badge gl-platform-badge-${key}" title="${title}"><img src="/static/icons/${key}.svg" alt=""></span>`;
  }

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

  const formatTime = (date = new Date()) =>
    date.toTimeString().slice(0, 8);

  // ----------------------------------------------------------------- render: header

  function renderHeader(state) {
    const monitoring = state.monitoring;
    const dotClass = monitoring ? "gl-dot gl-dot-safe" : "gl-dot gl-dot-dim";
    const label = monitoring ? "Monitoring active" : "Monitoring stopped";
    els.headerStatus.innerHTML = `<span class="${dotClass}"></span><span>${escapeHtml(label)}</span>`;
    setText(els.headerDuration, state.session_duration || "0m 00s");
    setText(els.headerModel, state.model_name || "");
  }

  // ----------------------------------------------------------------- render: metrics

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
    // Always render exactly 12 bars so the layout is stable.
    const slots = 12;
    const padded = history.slice(-slots);
    while (padded.length < slots) padded.unshift({ tone: "empty" });
    const html = padded
      .map((entry, i) => {
        const tone = entry.tone || "empty";
        const cls = tone === "empty" ? "" : `gl-spark-bar-${tone}`;
        // Newer bars are taller — gentle gradient from 6px to 18px.
        const height = 6 + Math.round((i / (slots - 1)) * 12);
        return `<span class="gl-spark-bar ${cls}" style="height:${height}px"></span>`;
      })
      .join("");
    els.metricSparkline.innerHTML = html;
  }

  // ----------------------------------------------------------------- render: screenshot

  // ----------------------------------------------------------------- fake browser

  const PLATFORM_AVATAR_INITIAL = (username) =>
    (username || "?").replace(/^@/, "").charAt(0).toUpperCase();

  function renderFakeBrowser(state) {
    const a = state.latest;
    if (!a) {
      els.fakeBrowser.className = "gl-fake-browser";
      els.browserUrl.textContent = "—";
      els.browserContent.innerHTML = '<div class="gl-browser-empty">Waiting for first capture...</div>';
      return;
    }
    const convo = a.conversation || {};
    const platformKey = convo.platform_key || "unknown";
    els.fakeBrowser.className = `gl-fake-browser gl-fake-browser-${platformKey}`;
    els.browserUrl.textContent = convo.url || a.screenshot_url || "—";

    const messages = a.chat_messages || [];

    // Demo mode: synthetic chat with structured messages → render bubbles.
    if (messages.length) {
      const username = convo.username || "user";
      const status = convo.active_status || "Active now";
      const headerHtml = `
        <div class="gl-convo-header">
          <div class="gl-convo-avatar">${escapeHtml(PLATFORM_AVATAR_INITIAL(username))}</div>
          <div class="gl-convo-meta">
            <div class="gl-convo-username">${escapeHtml(username)}</div>
            <div class="gl-convo-status">${escapeHtml(status)}</div>
          </div>
        </div>`;
      const bubbleRowsHtml = messages
        .map((m) => renderBubbleRow(m, platformKey))
        .join("");
      els.browserContent.innerHTML =
        headerHtml + `<div class="gl-bubbles gl-fade-in">${bubbleRowsHtml}</div>`;
      return;
    }

    // Watch-folder / real-screenshot mode: no structured messages, just
    // display the actual captured image so the parent sees what the
    // analyzer saw.
    if (a.screenshot_url) {
      const cacheBuster = a.timestamp || Date.now();
      const src = `${a.screenshot_url}?t=${encodeURIComponent(cacheBuster)}`;
      els.browserContent.innerHTML = `
        <div class="gl-browser-image gl-fade-in">
          <img src="${src}" alt="Captured screen">
        </div>`;
      return;
    }

    // Fallback: nothing to display.
    els.browserContent.innerHTML =
      '<div class="gl-browser-empty">No content for this capture.</div>';
  }

  function renderBubbleRow(message, platformKey) {
    const senderKey = (message.sender || "them").toLowerCase();
    const isMe = senderKey === "me" || senderKey === "self" || senderKey === "child";
    const rowSide = isMe ? "me" : "them";
    const bubbleSide = isMe ? "me" : "them";
    const flagged = message.flag ? " gl-bubble-flagged" : "";
    // Floating flag label sits absolutely positioned to the right of
    // the bubble (only for "them" rows since flagged messages always
    // come from the predator in our scenarios).
    const flagLabel = message.flag && !isMe
      ? `<span class="gl-bubble-flag-floating">${escapeHtml(message.flag)}</span>`
      : "";
    const senderAttr = `data-sender="${escapeHtml(message.sender || "")}"`;
    return `
      <div class="gl-bubble-row gl-bubble-row-${rowSide}" ${senderAttr}>
        <div class="gl-bubble gl-bubble-${bubbleSide}${flagged}">${escapeHtml(message.text)}</div>
        ${flagLabel}
      </div>`;
  }

  // ----------------------------------------------------------------- threat breakdown (compact)

  function renderThreatBreakdown(state) {
    const a = state.latest;
    if (!a) {
      els.breakdownCard.className = "gl-breakdown-card";
      els.breakdownTitle.textContent = "Threat breakdown";
      els.breakdownSubtitle.textContent = "—";
      els.breakdownConfidence.textContent = "—";
      els.breakdownPills.innerHTML = "";
      els.breakdownStagebar.innerHTML = "";
      els.breakdownStagelabels.innerHTML = "";
      els.breakdownStatboxes.innerHTML = "";
      return;
    }
    const level = a.threat_level;
    let cardClass = "gl-breakdown-card";
    if (level === "safe") cardClass += " gl-breakdown-card-safe";
    else if (level === "caution" || level === "warning") cardClass += " gl-breakdown-card-caution";
    els.breakdownCard.className = cardClass;

    els.breakdownTitle.textContent =
      level === "safe"
        ? "ALL CLEAR"
        : level === "caution" || level === "warning"
        ? `${a.category_label} — CAUTION`
        : `${a.category_label} DETECTED`;

    // Subtitle: "sender → child" when a conversation was analyzed, or
    // a calm "no chat detected" line when the scan was just a gameplay
    // screenshot.
    if (level === "safe") {
      const hasChatMessages = (a.chat_messages || []).length > 0;
      if (hasChatMessages) {
        els.breakdownSubtitle.textContent = "no risk indicators found";
      } else {
        els.breakdownSubtitle.textContent = `${a.platform || "content"} · no chat detected`;
      }
    } else {
      const convo = a.conversation || {};
      const subtitleParts = [convo.username || "—"];
      if ((a.chat_messages || []).some((m) => ["me", "self", "child"].includes((m.sender || "").toLowerCase()))) {
        subtitleParts.push("child");
      }
      els.breakdownSubtitle.textContent = subtitleParts.join(" → ");
    }

    els.breakdownConfidence.textContent = `${a.confidence}%`;

    // Indicator pills
    const pills = a.indicator_pills || [];
    els.breakdownPills.innerHTML = pills
      .map((p) => {
        const cls = `gl-breakdown-pill${p.tone === "caution" ? " gl-breakdown-pill-caution" : p.tone === "safe" ? " gl-breakdown-pill-safe" : ""}`;
        return `<span class="${cls}">${escapeHtml(p.label)}</span>`;
      })
      .join("");

    // Stage bar
    const stage = a.stage_segments || { segments: [], current_index: -1 };
    els.breakdownStagebar.innerHTML = stage.segments
      .map((seg) => {
        const segCls = seg.state === "active"
          ? "gl-breakdown-stage gl-breakdown-stage-active"
          : seg.state === "current"
          ? "gl-breakdown-stage gl-breakdown-stage-current"
          : "gl-breakdown-stage";
        return `<div class="${segCls}"></div>`;
      })
      .join("");
    els.breakdownStagelabels.innerHTML = stage.segments
      .map((seg) => {
        const cls = seg.state === "current"
          ? "gl-breakdown-stagelabel gl-breakdown-stagelabel-current"
          : seg.state === "active"
          ? "gl-breakdown-stagelabel gl-breakdown-stagelabel-active"
          : "gl-breakdown-stagelabel";
        return `<span class="${cls}">${escapeHtml(seg.label.toLowerCase())}</span>`;
      })
      .join("");

    // Stat boxes — prefer the analysis-bound list so the breakdown
    // stays coherent when the dashboard is locked to the latest alert.
    const boxes = (a && a.stat_boxes_inline) || state.stat_boxes || [];
    els.breakdownStatboxes.innerHTML = boxes
      .map((box) => {
        const isCaution = String(box.label).toLowerCase().startsWith("escal");
        const cls = isCaution
          ? "gl-breakdown-statbox gl-breakdown-statbox-caution"
          : "gl-breakdown-statbox";
        return `
          <div class="${cls}">
            <div class="gl-breakdown-statbox-value">${escapeHtml(String(box.value))}</div>
            <div class="gl-breakdown-statbox-label">${escapeHtml(box.label)}</div>
          </div>`;
      })
      .join("");
  }

  // ----------------------------------------------------------------- right panel (uses latest_alert)

  function renderReasoningChain(alertState) {
    if (!alertState) {
      els.reasoningChain.innerHTML = '<div class="gl-empty">Waiting for the first alert...</div>';
      return;
    }
    const steps = alertState.reasoning_chain || [];
    if (!steps.length) {
      els.reasoningChain.innerHTML = '<div class="gl-empty">No reasoning chain available.</div>';
      return;
    }
    // Build a single HTML string with explicit <br> between rows so each
    // STEP / flag / verdict sits on its own line regardless of CSS quirks.
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

  function renderWhyThisMatters(alertState) {
    if (!alertState || !alertState.why_this_matters) {
      els.whyThisMatters.innerHTML = '<div class="gl-empty">No flagged conversations yet.</div>';
      return;
    }
    els.whyThisMatters.innerHTML = `<div class="gl-why-text">${escapeHtml(alertState.why_this_matters)}</div>`;
  }

  function renderRecommendedAction(alertState) {
    const action = alertState && alertState.recommended_action;
    if (!action) {
      els.recommendedAction.innerHTML = '<div class="gl-empty">No action required right now.</div>';
      return;
    }
    const stepsHtml = (action.steps || [])
      .map(
        (step, idx) => `
        <div class="gl-action-step">
          <div class="gl-action-num">${idx + 1}</div>
          <div class="gl-action-text">${escapeHtml(step)}</div>
        </div>`,
      )
      .join("");
    const privacyHtml = action.privacy_note
      ? `<div class="gl-action-privacy">${escapeHtml(action.privacy_note)}</div>`
      : "";
    els.recommendedAction.innerHTML = stepsHtml + privacyHtml;
  }

  function renderTelegram(alertState) {
    const alert = alertState && alertState.parent_alert;
    if (!alert) {
      els.telegramBlock.innerHTML = "";
      return;
    }
    const deliveredAt = formatDeliveredAt(alert.delivered_at);
    els.telegramBlock.innerHTML = `
      <div class="gl-telegram-card gl-fade-in">
        <div class="gl-telegram-header">
          <img class="gl-telegram-icon" src="/static/icons/telegram.svg" alt="">
          <span class="gl-telegram-label">Telegram alert delivered</span>
        </div>
        <div class="gl-telegram-message">"${escapeHtml(alert.summary)}"</div>
        <div class="gl-telegram-meta">Delivered ${escapeHtml(deliveredAt)} &middot; read receipt pending</div>
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

  // ----------------------------------------------------------------- render: timeline

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
        const text = `${escapeHtml(e.platform)} &middot; ${escapeHtml(truncate(e.reasoning, 70))}`;
        const statusCls = `gl-timeline-status gl-timeline-status-${level}`;
        return `
          <div class="gl-timeline-entry gl-timeline-entry-${level}">
            <span class="${dotCls}"></span>
            ${badge}
            <span class="gl-timeline-time">${escapeHtml(e.time_label)}</span>
            <span class="gl-timeline-text">${text}</span>
            <span class="${statusCls}">${escapeHtml(level)}</span>
          </div>`;
      })
      .join("");
    els.timeline.innerHTML = html;
  }

  // ----------------------------------------------------------------- session health + streak + scan strip

  function renderSessionHealth(state) {
    const h = state.session_health || {};
    if (!els.sessionHealth) return;

    // Headline + color tint (green when clean, yellow when caution/alert
    // happened earlier in the session).
    const clean = h.clean !== false;
    els.sessionHealth.style.borderColor = clean
      ? "rgba(34, 197, 94, 0.22)"
      : "rgba(234, 179, 8, 0.25)";
    setText(els.healthTitle, h.headline || "ALL CLEAR");

    // Summary line: "78 screenshots · 18m 23s · 5 platforms"
    const summaryParts = [];
    if (h.scans !== undefined) summaryParts.push(`${h.scans} screenshots analyzed`);
    if (h.session_duration) summaryParts.push(h.session_duration);
    if (h.platform_count) summaryParts.push(`${h.platform_count} platforms`);
    setText(els.healthSummary, summaryParts.join(" · "));

    // Totals sub-line: "66 safe · 7 caution · 5 alerts"
    const totalsLine = `${h.safe || 0} safe · ${h.caution || 0} caution · ${h.alerts || 0} alerts`;

    // Last alert sub-line: "Last alert 4m 12s ago — Instagram grooming"
    let lastAlertLine = "";
    if (h.last_alert) {
      lastAlertLine = `Last alert ${escapeHtml(h.last_alert.ago)} — ${escapeHtml(h.last_alert.description)}`;
    }

    // Platform distribution
    const platforms = h.platforms || [];
    if (!platforms.length) {
      els.healthPlatforms.innerHTML =
        '<div class="gl-health-platform-row"><span></span><span>no data yet</span><span></span></div>';
    } else {
      els.healthPlatforms.innerHTML = platforms
        .map((p) => {
          const badge = renderPlatformBadge(p.name);
          return `
            <div class="gl-health-platform-row">
              ${badge}
              <span class="gl-health-platform-name">${escapeHtml(p.name)}</span>
              <span class="gl-health-platform-count">${p.count}</span>
            </div>`;
        })
        .join("");
    }

    // Model health line
    const modelBits = [h.model_name || "—"];
    if (h.avg_inference_label) modelBits.push(h.avg_inference_label);
    modelBits.push(h.monitoring ? "100% up" : "stopped");
    setText(els.healthModelText, modelBits.join(" · "));

    // Stash the extra lines into the dedicated spans (see template updates)
    const totalsEl = document.getElementById("health-totals");
    const lastAlertEl = document.getElementById("health-last-alert");
    if (totalsEl) totalsEl.textContent = totalsLine;
    if (lastAlertEl) {
      if (lastAlertLine) {
        lastAlertEl.innerHTML = lastAlertLine;
        lastAlertEl.style.display = "";
      } else {
        lastAlertEl.style.display = "none";
      }
    }
  }

  function renderRightPanelMode(state) {
    // Pick which right-panel content to show based on the CURRENT
    // scan's threat level. Previous version checked latest_alert
    // existence, which made stale grooming content stick around for
    // the rest of the session even after many safe scans. Now the
    // mode tracks what the camera is seeing RIGHT NOW.
    //
    // - Current scan is alert/critical → reasoning stack for that scan
    // - Otherwise → Session Health overview
    const latest = (state && state.latest) || null;
    const level = latest && latest.threat_level;
    const showAlert = level === "alert" || level === "critical";
    if (showAlert) {
      els.sessionHealth.style.display = "none";
      els.alertStack.style.display = "";
    } else {
      els.sessionHealth.style.display = "";
      els.alertStack.style.display = "none";
    }
  }

  function renderScanStrip(state) {
    // Shown inside the breakdown card when the latest scan is safe —
    // replaces the empty stage bar + stat boxes with a row of 20
    // colored bars (one per recent scan) + total counts.
    const history = state.scan_history || [];
    const slots = 20;
    const padded = history.slice(-slots);
    while (padded.length < slots) padded.unshift({ tone: "empty" });
    const bars = padded
      .map((entry) => {
        const tone = entry.tone || "empty";
        const cls = tone === "empty" ? "" : `gl-scan-strip-bar-${tone}`;
        return `<div class="gl-scan-strip-bar ${cls}"></div>`;
      })
      .join("");
    els.scanStripBars.innerHTML = bars;

    // Aggregate counts
    const counts = { safe: 0, caution: 0, alert: 0 };
    for (const entry of history) {
      if (entry.tone && counts[entry.tone] !== undefined) counts[entry.tone] += 1;
    }
    els.scanStripCounts.innerHTML = `
      <span class="safe">${counts.safe} safe</span>
      <span class="caution">${counts.caution} caution</span>
      <span class="alert">${counts.alert} alerts</span>
    `;
  }

  function renderBreakdownMode(state) {
    // Inside the breakdown card: if latest is safe and there's no
    // grooming stage context, hide the stage bar + stat boxes and
    // show the scan trend strip instead.
    const latest = state.latest;
    const showStage =
      latest &&
      latest.threat_level !== "safe" &&
      latest.stage_segments &&
      (latest.stage_segments.current_index ?? -1) >= 0;
    if (showStage) {
      els.breakdownStageWrap.style.display = "";
      els.scanStrip.style.display = "none";
    } else {
      els.breakdownStageWrap.style.display = "none";
      els.scanStrip.style.display = "";
    }
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

  // ----------------------------------------------------------------- alert notifications

  // Browser Notifications + soft "ding" sound on each new alert.
  //
  // - Web Audio API generates the ding in JS (no audio file).
  // - Audio context is unlocked on the first user interaction (browsers
  //   block autoplay until then).
  // - Browser notifications require a secure context (HTTPS or
  //   localhost). Over a LAN IP they silently no-op; the audio still
  //   plays. To get notifications working from a remote machine, SSH-
  //   tunnel to localhost: `ssh -L 7860:localhost:7860 host` then open
  //   http://localhost:7860/.
  // - "New alert" is detected by comparing state.latest_alert.timestamp
  //   to the previous one. The first state observed after page load is
  //   treated as the baseline (no notification on the bootstrapped
  //   alert from a previous session).
  const notify = (() => {
    let audioCtx = null;
    let audioUnlocked = false;
    let lastAlertTs = null;
    let initialized = false;
    let permissionRequested = false;

    const ensureContext = () => {
      if (audioCtx) return audioCtx;
      const Ctor = window.AudioContext || window.webkitAudioContext;
      if (!Ctor) {
        console.warn("[notify] no AudioContext available in this browser");
        return null;
      }
      try {
        audioCtx = new Ctor();
        console.log("[notify] AudioContext created, state:", audioCtx.state);
        return audioCtx;
      } catch (err) {
        console.warn("[notify] AudioContext creation failed", err);
        return null;
      }
    };

    const unlockAudio = async () => {
      if (audioUnlocked) return true;
      const ctx = ensureContext();
      if (!ctx) return false;
      if (ctx.state === "suspended") {
        try {
          await ctx.resume();
          console.log("[notify] AudioContext resumed, state:", ctx.state);
        } catch (err) {
          console.warn("[notify] resume failed", err);
        }
      }
      audioUnlocked = ctx.state === "running";
      if (audioUnlocked) {
        document.body.classList.add("gl-audio-on");
      }
      return audioUnlocked;
    };

    document.addEventListener("click", unlockAudio, { once: false });
    document.addEventListener("keydown", unlockAudio, { once: false });

    // Two-tone ding: 880 Hz then 1320 Hz, ~400ms total, soft envelope.
    const playDing = () => {
      if (!audioCtx) {
        console.warn("[notify] playDing called but no AudioContext");
        return;
      }
      if (audioCtx.state !== "running") {
        console.warn("[notify] playDing called but context state is", audioCtx.state);
        return;
      }
      const t0 = audioCtx.currentTime;
      const tones = [
        { freq: 880, start: 0.0, dur: 0.35 },
        { freq: 1320, start: 0.1, dur: 0.4 },
      ];
      for (const tone of tones) {
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
      }
      console.log("[notify] ding played");
    };

    // Public test entry: unlocks audio + plays ding immediately. Hooked
    // to the hint banner click and exposed on window.notify.test() so
    // you can verify audio works without waiting for an alert.
    const test = async () => {
      console.log("[notify] test() called");
      const ok = await unlockAudio();
      if (!ok) {
        console.warn("[notify] could not unlock audio context");
        return false;
      }
      playDing();
      return true;
    };

    const requestPermission = () => {
      if (permissionRequested) return;
      permissionRequested = true;
      if (typeof Notification === "undefined") return;
      if (Notification.permission === "default") {
        try {
          Notification.requestPermission();
        } catch (_) {
          /* old browsers don't return a promise */
        }
      }
    };

    const showBrowserNotification = (alertState) => {
      if (typeof Notification === "undefined") return;
      if (Notification.permission !== "granted") return;
      const pa = (alertState && alertState.parent_alert) || {};
      const title = pa.title
        ? `GuardianLens — ${pa.title}`
        : "GuardianLens — safety alert";
      const body =
        pa.summary ||
        `${alertState.category_label || "Threat"} detected on ${alertState.platform || "an app"}`;
      try {
        const n = new Notification(title, {
          body,
          tag: "guardlens-alert",
          requireInteraction: false,
          silent: false,
        });
        n.onclick = () => {
          window.focus();
          n.close();
        };
        setTimeout(() => {
          try {
            n.close();
          } catch (_) {}
        }, 8000);
      } catch (err) {
        console.warn("notification failed", err);
      }
    };

    const handle = (state) => {
      requestPermission();
      const alertState = state && state.latest_alert;
      const ts = alertState && alertState.timestamp;
      if (!initialized) {
        initialized = true;
        lastAlertTs = ts || null;
        return;
      }
      if (!ts) return;
      if (ts === lastAlertTs) return;
      lastAlertTs = ts;
      playDing();
      showBrowserNotification(alertState);
    };

    return { handle, test, playDing, unlockAudio };
  })();

  // Expose for console debugging: window.notify.test() to test the ding.
  window.notify = notify;

  // ----------------------------------------------------------------- top-level render

  function render(state) {
    if (!state) return;
    document.body.classList.toggle("loaded", true);
    notify.handle(state);
    if (state.is_alert) {
      els.shell.classList.add("gl-alert-active");
    } else {
      els.shell.classList.remove("gl-alert-active");
    }
    renderHeader(state);
    renderStreak(state);
    renderMetrics(state);
    // Capture view always shows the LATEST scan so the dashboard feels
    // alive — each new screenshot appears in the fake browser as it
    // arrives.
    renderFakeBrowser(state);
    renderThreatBreakdown(state);
    renderBreakdownMode(state);
    renderScanStrip(state);
    renderTimeline(state);
    // Right panel: dual mode. Session Health card when everything is
    // safe, reasoning-chain stack when the CURRENT scan is an alert.
    // The reasoning/why/action renderers always take the latest scan
    // so they match whatever the mode switcher decided to show — no
    // stale alert content from earlier in the session.
    renderRightPanelMode(state);
    renderSessionHealth(state);
    const rightPanelAnalysis = state.latest || null;
    renderReasoningChain(rightPanelAnalysis);
    renderWhyThisMatters(rightPanelAnalysis);
    renderRecommendedAction(rightPanelAnalysis);
    renderTelegram(rightPanelAnalysis);
    setText(els.lastRefresh, formatTime());
    setText(els.footerModel, state.model_name);
    setText(els.footerDb, state.db_path);
    if (els.privacySubtitle) {
      els.privacySubtitle.textContent =
        `Gemma 4 via Ollama · data sent to cloud: 0 bytes`;
    }
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
      // EventSource auto-reconnects with the default 3 s backoff.
      console.warn("SSE connection dropped, retrying...");
    };
    return source;
  }

  document.addEventListener("DOMContentLoaded", () => {
    const initial = loadInitialState();
    if (initial) render(initial);
    connectStream();
    // Audio unlock happens on the first click anywhere in the document
    // (see notify module). For console fallback: window.notify.test().
  });
})();
