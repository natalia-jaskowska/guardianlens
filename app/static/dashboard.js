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
    breakdownStagebar: document.getElementById("breakdown-stagebar"),
    breakdownStagelabels: document.getElementById("breakdown-stagelabels"),
    breakdownStatboxes: document.getElementById("breakdown-statboxes"),
    timeline: document.getElementById("timeline"),
    reasoningChain: document.getElementById("reasoning-chain"),
    whyThisMatters: document.getElementById("why-this-matters"),
    recommendedAction: document.getElementById("recommended-action"),
    telegramBlock: document.getElementById("telegram-block"),
    privacySubtitle: document.getElementById("privacy-subtitle"),
    lastRefresh: document.getElementById("last-refresh"),
    footerModel: document.getElementById("footer-model"),
    footerDb: document.getElementById("footer-db"),
  };

  // ----------------------------------------------------------------- platform badges

  // Maps a platform name (possibly with section like "Instagram DM") to
  // a {key, label} pair the renderer uses to pick a badge variant.
  function platformBadgeFor(platformText) {
    if (!platformText) return { key: "unknown", label: "?" };
    const lower = platformText.toLowerCase();
    if (lower.includes("instagram")) return { key: "instagram", label: "Ig" };
    if (lower.includes("tiktok")) return { key: "tiktok", label: "Tk" };
    if (lower.includes("discord")) return { key: "discord", label: "Dc" };
    if (lower.includes("minecraft")) return { key: "minecraft", label: "Mc" };
    if (lower.includes("snap")) return { key: "instagram", label: "Sn" };
    if (lower.includes("roblox")) return { key: "minecraft", label: "Rb" };
    return { key: "unknown", label: "?" };
  }

  function renderPlatformBadge(platformText) {
    const badge = platformBadgeFor(platformText);
    return `<span class="gl-platform-badge gl-platform-badge-${badge.key}" title="${escapeHtml(platformText || "Unknown")}">${badge.label}</span>`;
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
    els.browserUrl.textContent = convo.url || "—";

    const messages = a.chat_messages || [];
    if (!messages.length) {
      els.browserContent.innerHTML =
        '<div class="gl-browser-empty">No structured messages for this capture.</div>';
      return;
    }

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

    const titleText =
      level === "safe"
        ? `${escapeHtml(a.category_label || "NO THREATS")} OK`
        : level === "caution" || level === "warning"
        ? `${escapeHtml(a.category_label)} CAUTION`
        : `${escapeHtml(a.category_label)} DETECTED`;
    els.breakdownTitle.textContent = "";
    els.breakdownTitle.textContent = level === "safe" ? "NO THREATS" : `${a.category_label} DETECTED`;

    // Subtitle: "sender → child"
    const convo = a.conversation || {};
    const subtitleParts = [convo.username || "—"];
    if ((a.chat_messages || []).some((m) => ["me", "self", "child"].includes((m.sender || "").toLowerCase()))) {
      subtitleParts.push("child");
    }
    els.breakdownSubtitle.textContent = subtitleParts.join(" → ");

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
          <svg class="gl-telegram-icon" width="9" height="9" viewBox="0 0 16 16" fill="none">
            <path d="M14 2L7 9M14 2L10 14L7 9M14 2L2 6L7 9" stroke="#60a5fa" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
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
    renderMetrics(state);
    // Capture view + right panel both lock to the most recent ALERT so the
    // parent always sees the most concerning recent incident, not whatever
    // safe scan happened to come in last. Falls back to the latest scan
    // when no alert has been recorded yet.
    const alertState = state.latest_alert || state.latest;
    const captureProxy = alertState
      ? { ...state, latest: alertState }
      : state;
    renderFakeBrowser(captureProxy);
    renderThreatBreakdown(captureProxy);
    renderTimeline(state);
    renderReasoningChain(alertState);
    renderWhyThisMatters(alertState);
    renderRecommendedAction(alertState);
    renderTelegram(alertState);
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
