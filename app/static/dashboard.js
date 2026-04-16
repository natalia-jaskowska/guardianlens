/**
 * GuardianLens dashboard — conversation-centric redesign.
 * Subscribes to /api/stream (SSE) and renders left = activity list,
 * right = three states (session overview / conversation detail /
 * environment detail).
 */

const $ = (id) => document.getElementById(id);

/* ------------------------------- state ------------------------------ */
const SEEN_KEY = "guardlens.seen_alerts.v1";

function loadSeen() {
  try {
    const raw = localStorage.getItem(SEEN_KEY);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch { return new Set(); }
}
function saveSeen() {
  try {
    localStorage.setItem(SEEN_KEY, JSON.stringify([...ui.seenAlerts]));
  } catch {}
}

// One stable id per alertable state.  The threat level is part of the
// key on purpose: if a conversation escalates (warning → alert) the
// counter treats it as a fresh unread event — the parent should see
// the new severity even if they'd dismissed the old one.
function alertId(kind, data) {
  if (kind === "conversation") {
    return `c:${data.platform}:${data.participant}:${data.threat_level}`;
  }
  return `e:${data.platform}:${data.context}:${data.overall_safety}`;
}
function markSeen(key) {
  if (!key) return;
  if (!ui.seenAlerts.has(key)) {
    ui.seenAlerts.add(key);
    saveSeen();
  }
}

const ui = {
  snapshot: null,
  selection: null,
  lastAutoAlertKey: null,
  lastFrameKey: null,
  seenAlerts: loadSeen(),
};

/* ----------------------------- formatters --------------------------- */
const LEVEL_CLASS = {
  safe: "safe", caution: "warn", warning: "warn",
  alert: "alert", critical: "alert",
};
const levelClass = (lvl) => LEVEL_CLASS[lvl] || "safe";

function prettyDuration(seconds) {
  seconds = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m) return `${m}m ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

function initials(name) {
  if (!name) return "—";
  const clean = String(name).replace(/[^a-zA-Z0-9]/g, "");
  return (clean.slice(0, 2) || "—").toUpperCase();
}

function timeAgo(isoOrSeconds) {
  if (!isoOrSeconds) return "";
  const d = typeof isoOrSeconds === "string" ? new Date(isoOrSeconds) : new Date(isoOrSeconds * 1000);
  const s = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (s < 10) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  return `${Math.floor(m / 60)}h ago`;
}

function platformFamily(p) {
  const s = String(p || "").toLowerCase();
  if (s.includes("instagram")) return "instagram";
  if (s.includes("minecraft")) return "minecraft";
  if (s.includes("discord")) return "discord";
  if (s.includes("tiktok")) return "tiktok";
  if (s.includes("youtube")) return "youtube";
  if (s.includes("snapchat")) return "snapchat";
  if (s.includes("whatsapp")) return "whatsapp";
  if (s.includes("roblox")) return "roblox";
  return "unknown";
}
const platformLetters = {
  instagram: "Ig", minecraft: "Mc", discord: "Dc", tiktok: "Tk",
  youtube: "Yt", snapchat: "Sc", whatsapp: "Wa", roblox: "Rb", unknown: "?",
};
// Pretty names for the platform line. Keep the source string if unknown
// so we never turn a model output like "chat" into the literal word "chat".
const PLATFORM_LABELS = {
  instagram: "Instagram", minecraft: "Minecraft", discord: "Discord",
  tiktok: "TikTok", youtube: "YouTube", snapchat: "Snapchat",
  whatsapp: "WhatsApp", roblox: "Roblox",
};
function platformLabel(raw) {
  const fam = platformFamily(raw);
  return PLATFORM_LABELS[fam] || (raw ? String(raw).replace(/_/g, " ") : "Unknown");
}

// Inline SVG brand glyphs, sized 18x18 and rendered in white on the
// colored tile background. Simplified silhouettes — instantly
// recognisable, no trademark issues, no external requests.
const PLATFORM_SVG = {
  discord:
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M20 5.1a17 17 0 0 0-4.2-1.3l-.2.4a13 13 0 0 0-7.2 0l-.2-.4A17 17 0 0 0 4 5.1 18 18 0 0 0 .9 17a17 17 0 0 0 5.2 2.6l.4-.6a12 12 0 0 1-2-.9l.5-.4a12 12 0 0 0 10 0l.5.4-2 .9.4.6A17 17 0 0 0 23 17a18 18 0 0 0-3-11.9zM8.5 14.4c-1 0-1.9-1-1.9-2.1 0-1.2.9-2.2 2-2.2 1 0 1.9 1 1.9 2.2 0 1.1-.9 2.1-2 2.1zm7 0c-1 0-1.9-1-1.9-2.1 0-1.2.9-2.2 1.9-2.2s1.9 1 1.9 2.2c0 1.1-.8 2.1-1.9 2.1z"/></svg>',
  instagram:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor" stroke="none"/></svg>',
  minecraft:
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M4 7l8-4 8 4-8 4-8-4zm0 2v8l8 4v-8L4 9zm16 0l-8 4v8l8-4V9z"/></svg>',
  tiktok:
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M17 3v3.1a5 5 0 0 0 4 2v3a8 8 0 0 1-4-1.2V16a6 6 0 1 1-6-6v3a3 3 0 1 0 3 3V3h3z"/></svg>',
  youtube:
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M22 7.3a3 3 0 0 0-2.1-2.1C18 4.8 12 4.8 12 4.8s-6 0-7.9.4A3 3 0 0 0 2 7.3 31 31 0 0 0 1.6 12 31 31 0 0 0 2 16.7a3 3 0 0 0 2.1 2.1C6 19.2 12 19.2 12 19.2s6 0 7.9-.4a3 3 0 0 0 2.1-2.1 31 31 0 0 0 .4-4.7 31 31 0 0 0-.4-4.7zM10 15.3V8.7l5.2 3.3L10 15.3z"/></svg>',
  snapchat:
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2.5c3.3 0 5.5 2.3 5.5 5.6 0 1.3-.2 3-.2 3.3.4.3.8.4 1.3.4.4 0 .7-.1 1-.3l.2.2a.7.7 0 0 1-.3 1 8 8 0 0 1-2 .9c-.1.2-.2.7-.3 1a.4.4 0 0 1-.4.3l-1.5-.1a4 4 0 0 0-1.6.4c-.8.4-1.6 1.7-3.7 1.7s-2.9-1.3-3.7-1.7a4 4 0 0 0-1.6-.4l-1.5.1a.4.4 0 0 1-.4-.3l-.3-1a8 8 0 0 1-2-.9.7.7 0 0 1-.3-1l.2-.2c.3.2.6.3 1 .3.5 0 .9-.1 1.3-.4 0-.3-.2-2-.2-3.3 0-3.3 2.2-5.6 5.5-5.6z"/></svg>',
  whatsapp:
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2.8A9.2 9.2 0 0 0 4 16.6l-1.2 4.3 4.4-1.1a9.2 9.2 0 0 0 13.6-8 9.2 9.2 0 0 0-8.8-9zm5.3 13c-.2.6-1.3 1.2-1.8 1.2-.5 0-.5.4-3-.6a10 10 0 0 1-4.1-3.6c-.2-.3-1-1.3-1-2.5 0-1.1.6-1.7.8-1.9.2-.2.5-.3.7-.3h.5c.2 0 .4 0 .6.5l.8 2c.1.1.1.3 0 .5l-.3.5-.5.5.1.2a7 7 0 0 0 1.2 1.5 6 6 0 0 0 1.7 1c.2.1.3.1.5-.1l.6-.7.3-.2h.3l1.9.9.3.2c0 .2 0 .8-.2 1.4z"/></svg>',
  roblox:
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M4.4 2l15.2 4-4 15.2L.4 17.2 4.4 2zm5.6 8l-.9 3.5 3.5.9.9-3.5-3.5-.9z"/></svg>',
  unknown:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.3 2.4c-.5.2-.8.6-.8 1.2V14" stroke-linecap="round"/><circle cx="12" cy="17" r="0.9" fill="currentColor" stroke="none"/></svg>',
};
function platformLogo(fam) {
  return PLATFORM_SVG[fam] || PLATFORM_SVG.unknown;
}

// One-word parent-readable status badge per backend threat level.
// Returns [label, cssClass]. "Critical" collapses into ALERT visually
// because the parent action is identical.
const STATUS_LABEL = {
  safe:     ["Safe",     "safe"],
  caution:  ["Caution",  "caution"],
  warning:  ["Warning",  "warning"],
  alert:    ["Alert",    "alert"],
  critical: ["Alert",    "alert"],
};
function statusBadge(level) {
  const [lbl, cls] = STATUS_LABEL[level] || STATUS_LABEL.safe;
  return { label: lbl, cls };
}

/* ---------------------------- activity list ------------------------- */
function sortByDanger(items, levelKey) {
  const order = { alert: 0, critical: 0, warning: 1, caution: 2, safe: 3 };
  return [...items].sort((a, b) => {
    const la = order[a[levelKey]] ?? 9;
    const lb = order[b[levelKey]] ?? 9;
    return la - lb;
  });
}

function renderActivity(conversations) {
  const list = $("activityList");
  const sorted = [...conversations].sort((a, b) => {
    return new Date(b.last_seen || 0) - new Date(a.last_seen || 0);
  });

  list.innerHTML = "";
  if (sorted.length === 0) {
    list.innerHTML = `<div class="gl-empty">Monitoring — no activity yet</div>`;
    return;
  }

  for (const c of sorted) {
    list.appendChild(convCard(c));
  }
}

function convCard(c) {
  // Conversation card. Layout reads left-to-right like a parent-facing
  // message row:
  //   [platform logo]  username            [STATUS badge]
  //                    platform · N msgs · duration · conf%
  //                    one-line narrative snippet
  // The status badge is the thing the eye lands on first — that's the
  // single decision (do I need to open this?) a parent is making.
  const rawLvl = c.threat_level || "safe";
  const lvl = levelClass(rawLvl);
  const pct = Math.round(c.confidence || 0);
  const fam = platformFamily(c.platform);
  const badge = statusBadge(rawLvl);
  const card = document.createElement("div");
  const isSelected = ui.selection
    && ui.selection.kind === "conversation"
    && ui.selection.platform === c.platform
    && ui.selection.participant === c.participant;
  card.className = `gl-card conv ${lvl}${isSelected ? " selected" : ""}`;
  card.setAttribute("role", "button");
  card.setAttribute("tabindex", "0");
  if (isSelected) card.setAttribute("aria-current", "true");
  card.setAttribute(
    "aria-label",
    `${badge.label} — ${c.participant} on ${platformLabel(c.platform)}. Click to open analysis.`,
  );
  const openDetail = () => {
    markSeen(alertId("conversation", c));
    ui.selection = { kind: "conversation", platform: c.platform, participant: c.participant };
    // Include the current threat_level so a later escalation from
    // caution → alert produces a fresh key and re-pops the detail view.
    ui.lastAutoAlertKey = `${selectionKey(ui.selection)}:${c.threat_level}`;
    render();
  };
  card.addEventListener("click", openDetail);
  card.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDetail(); }
  });

  const promoted = c.source && c.source.startsWith("promoted_")
    ? `<span class="gl-chip-promoted" title="Promoted from a public space">promoted</span>` : "";

  // Platform + recency. "X ago" answers "is this still happening?".
  const ago = c.last_seen ? timeAgo(c.last_seen) : "";
  const metaParts = [platformLabel(c.platform)];
  if (ago) metaParts.push(ago);
  if (pct && lvl !== "safe") metaParts.push(`${pct}% confidence`);
  const meta = metaParts.join(" · ");

  const snippet = shortNarrative(c);

  const alertPulse = lvl === "alert"
    ? '<span class="gl-badge-dot" aria-hidden="true"></span>' : "";

  const names = (c.participants && c.participants.length > 0)
    ? c.participants
    : (c.participant ? [c.participant] : []);
  const shown = names.slice(0, 3).join(", ");
  const extra = names.length > 3 ? ` +${names.length - 3}` : "";
  const title = shown ? shown + extra : "Unknown";

  card.innerHTML = `
    <div class="gl-tile ${fam}" aria-hidden="true">${platformLogo(fam)}</div>
    <div class="gl-card-body">
      <div class="gl-card-head">
        <span class="gl-card-name" title="${escapeHtml(names.join(", "))}">${escapeHtml(title)}</span>
        ${promoted}
        <span class="gl-status-badge ${badge.cls}">${alertPulse}${badge.label}${c.category && c.category !== "none" ? ` · ${prettyIndicator(c.category)}` : ""}</span>
      </div>
      <div class="gl-card-meta">${escapeHtml(meta)}</div>
      ${snippet ? `<div class="gl-card-note ${lvl}">${escapeHtml(snippet)}</div>` : ""}
    </div>`;
  return card;
}

function shortNarrative(c) {
  if (c.short_summary) return c.short_summary;
  if (c.narrative) return c.narrative.split(".")[0].slice(0, 140);
  if (c.indicators && c.indicators.length > 0) {
    return `${c.category} — ${c.indicators.slice(0, 2).join(", ")}`;
  }
  return c.category || "observed";
}

/* ---------------------------- capture block ------------------------- */
function renderCapture(snapshot) {
  const latest = snapshot.latest;
  const frame = $("captureFrame");
  const statusEl = $("captureStatus");
  const card = $("captureCard");
  const icon = $("captureIcon");
  const text = $("captureText");
  const sub = $("captureSub");
  const ago = $("captureAgo");

  if (!latest) {
    frame.innerHTML = `<div class="gl-capture-empty">Waiting for first frame…</div>`;
    card.classList.remove("alert", "warn");
    statusEl.classList.remove("alert", "warn");
    text.className = "gl-status-text";
    text.textContent = "All clear";
    sub.textContent = "";
    ago.textContent = "";
    return;
  }

  // `serialize_analysis` flattens ScreenAnalysis into a single dict —
  // fields live directly on `latest`, not nested under `classification`.
  // Prefer chat_messages for a richer rendering; fall back to the
  // screenshot image when the frame has no structured messages.
  const msgs = latest.chat_messages || [];
  if (msgs.length > 0) {
    const platformName = latest.platform || "—";
    const rows = msgs.slice(0, 4).map((m) => {
      const cls = m.flag ? "red" : "grn";
      return `<div class="cc-msg"><span class="cc-sender ${cls}">${escapeHtml(m.sender || "")}:</span> <span>${escapeHtml(m.text || "")}</span></div>`;
    }).join("");
    frame.innerHTML = `
      <div class="gl-capture-chat">
        <div class="cc-platform">${escapeHtml(platformName)}</div>
        ${rows}
      </div>`;
  } else if (latest.screenshot_url) {
    frame.innerHTML = `<img src="${latest.screenshot_url}" alt="live capture" class="gl-capture-img" data-lightbox="1">`;
  } else {
    frame.innerHTML = `<div class="gl-capture-empty">No preview available</div>`;
  }

  const lvl = latest.threat_level || "safe";
  const cls = levelClass(lvl);
  card.classList.toggle("alert", cls === "alert");
  card.classList.toggle("warn", cls === "warn");
  statusEl.classList.toggle("alert", cls === "alert");
  statusEl.classList.toggle("warn", cls === "warn");
  text.className = `gl-status-text ${cls === "safe" ? "" : cls}`;
  sub.className = `gl-status-sub ${cls === "safe" ? "" : cls}`;

  const catLabel = (latest.category && latest.category !== "none") ? latest.category : "";
  text.textContent = cls === "alert"
    ? (catLabel ? `Alert · ${catLabel}` : "Alert")
    : cls === "warn" ? (catLabel ? `Concerning · ${catLabel}` : "Concerning") : "All clear";
  // Sub-line: short summary only (or fallback to platform). The full
  // narrative is on the conversation card; here we want one short hint.
  sub.textContent = latest.reasoning || latest.platform || "";
  sub.title = latest.reasoning || "";
  // Blink the status dot only when the screenshot actually changes,
  // not on every SSE tick.
  const frameKey = latest.screenshot_url || latest.timestamp || "";
  if (ui.lastFrameKey !== frameKey) {
    ui.lastFrameKey = frameKey;
    statusEl.classList.remove("tick");
    void statusEl.offsetWidth;
    statusEl.classList.add("tick");
  }
  ago.textContent = timeAgo(latest.timestamp);
}

/* ---------------------------- session overview ---------------------- */
function renderSessionOverview(snapshot) {
  const narr = snapshot.session_narrative || {};
  const convs = snapshot.conversations || [];
  const envs = snapshot.environments || [];

  // Hero — tone class also applied to the hero block for background gradient.
  const toneCls = narr.tone === "alert" ? "alert" : narr.tone === "warning" ? "warn" : "";
  const hero = $("overviewHero");
  const title = $("heroTitle");
  const sub = $("heroSub");
  hero.className = "gl-overview-hero" + (toneCls ? " " + toneCls : "");
  title.className = "gl-hero-title " + toneCls;
  sub.className = "gl-hero-sub " + toneCls;
  title.textContent = narr.headline || "Monitoring";
  sub.textContent = narr.subhead || "";
  $("heroIcon").innerHTML = toneCls === "alert"
    ? `<svg viewBox="0 0 36 36" fill="none"><circle cx="18" cy="18" r="14" stroke="rgba(239,68,68,0.28)" stroke-width="1.5"/><path d="M18 11v8M18 23v0.5" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round"/></svg>`
    : toneCls === "warn"
      ? `<svg viewBox="0 0 36 36" fill="none"><circle cx="18" cy="18" r="14" stroke="rgba(234,179,8,0.28)" stroke-width="1.5"/><path d="M18 11v8M18 23v0.5" stroke="#eab308" stroke-width="2.5" stroke-linecap="round"/></svg>`
      : `<svg viewBox="0 0 36 36" fill="none"><circle cx="18" cy="18" r="14" stroke="rgba(34,197,94,0.28)" stroke-width="1.5"/><path d="M11 18.5L15.5 23L25 13" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

  // Stats
  $("ovMonitored").textContent = narr.monitored || "0s";
  $("ovConversations").textContent = narr.conversations_count ?? 0;
  $("ovSafeRate").textContent = `${narr.safe_rate ?? 100}%`;
  $("ovSafeRate").className = "gl-stat-val gl-green";
  const peak = (narr.peak || "safe").toUpperCase();
  const peakEl = $("ovPeak");
  peakEl.textContent = peak;
  peakEl.className = "gl-stat-val gl-peak " + (
    narr.peak === "alert" || narr.peak === "critical" ? "alert"
    : narr.peak === "warning" ? "warn"
    : narr.peak === "caution" ? "caution"
    : "safe"
  );

  // Narrative
  const intro = $("narrativeIntro");
  const concernsEl = $("narrativeConcerns");
  const safeEl = $("narrativeSafe");
  const total = convs.length + envs.length;
  if (total === 0) {
    intro.innerHTML = "Session in progress — nothing flagged yet.";
  } else {
    const convCount = convs.length;
    const convText = `${convCount} conversation${convCount === 1 ? "" : "s"}`;
    const concernText = narr.concerns && narr.concerns.length
      ? ` · <b class="gl-intro-flag">${narr.concerns.length} concern${narr.concerns.length === 1 ? "" : "s"}</b>`
      : "";
    intro.innerHTML = `Monitored for <b>${narr.monitored}</b> · ${convText}${concernText}`;
  }

  concernsEl.innerHTML = "";
  for (const c of narr.concerns || []) {
    const cls = levelClass(c.level);
    const row = document.createElement("div");
    row.className = "gl-concern-row";
    row.innerHTML = `
      <div class="gl-concern-dot ${cls === "alert" ? "" : "warn"}"></div>
      <div class="gl-concern-text ${cls === "alert" ? "" : "warn"}"><b>${escapeHtml(c.name)}</b> — ${escapeHtml(c.summary || c.category)}</div>`;
    concernsEl.appendChild(row);
  }

  // Safe activities — modern chip row. Header text adapts to whether
  // there are also concerns (so we don't say "All clear" alongside
  // a "Concerning patterns" hero).
  if (narr.safe_count > 0) {
    const safeConvs = (snapshot.conversations || []).filter((c) => c.threat_level === "safe");
    const hasConcerns = (narr.concerns || []).length > 0;
    const headerLabel = hasConcerns
      ? `${narr.safe_count} other${narr.safe_count === 1 ? "" : "s"} look safe`
      : "All clear";
    const tokens = safeConvs.slice(0, 6).map((c) => {
      const fam = platformFamily(c.platform);
      const names = (c.participants && c.participants.length > 0) ? c.participants : [c.participant];
      const label = names.slice(0, 2).join(", ") + (names.length > 2 ? ` +${names.length - 2}` : "");
      return `<span class="gl-safe-chip"><span class="gl-safe-chip-dot ${fam}"></span>${escapeHtml(label)}</span>`;
    });
    const overflow = safeConvs.length > 6
      ? `<span class="gl-safe-chip more">+${safeConvs.length - 6}</span>` : "";
    safeEl.innerHTML = `
      <div class="gl-safe-header">
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M3 8.5L6.5 12L13 4.5" stroke="#22c55e" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span>${escapeHtml(headerLabel)}</span>
      </div>
      <div class="gl-safe-chips">${tokens.join("")}${overflow}</div>`;
  } else {
    safeEl.innerHTML = "";
  }

  // Actions
  const actionsList = $("actionsList");
  actionsList.innerHTML = "";
  (narr.what_to_do || []).forEach((txt, i) => {
    const row = document.createElement("div");
    row.className = "gl-action-row";
    row.innerHTML = `<div class="gl-action-num">${i + 1}</div><div>${escapeHtml(txt)}</div>`;
    actionsList.appendChild(row);
  });

}

/* ---------------------------- conversation detail ------------------- */
function renderConversationDetail(snapshot, sel) {
  const c = (snapshot.conversations || []).find(
    (x) => x.platform === sel.platform && x.participant === sel.participant
  );
  if (!c) {
    showState("stateSession");
    return;
  }

  const pct = Math.round(c.confidence || 0);
  const lvl = levelClass(c.threat_level);
  const fam = platformFamily(c.platform);

  const names = (c.participants && c.participants.length > 0)
    ? c.participants
    : (c.participant ? [c.participant] : []);
  const shown = names.slice(0, 3).join(", ");
  const extra = names.length > 3 ? ` +${names.length - 3}` : "";
  const title = shown ? shown + extra : "Unknown";

  const avatar = $("convAvatar");
  // Brand color comes from gl-tile; severity is shown via the outer ring
  // styled by the data-tone attribute (see CSS).
  avatar.className = `gl-avatar-circle gl-tile ${fam}`;
  avatar.dataset.tone = lvl;
  avatar.innerHTML = platformLogo(fam);
  avatar.title = platformLabel(c.platform);

  const name = $("convName");
  name.className = "gl-detail-name " + (lvl === "safe" ? "safe" : lvl);
  name.textContent = title;
  name.title = names.join(", ");

  const sub = $("convSub");
  const ago = c.last_seen ? timeAgo(c.last_seen) : "";
  sub.textContent = ago;

  const conf = $("convConfidence");
  conf.className = "gl-detail-confidence " + (lvl === "safe" ? "safe" : lvl);
  conf.innerHTML = `${pct}<small>%</small>`;

  const threat = $("convThreat");
  threat.className = `gl-threat-summary ${lvl === "safe" ? "safe" : lvl === "warn" ? "warn" : ""}`;
  const stage = c.grooming_stage || "none";
  const stageIdx = ["none","targeting","trust_building","isolation","desensitization","maintaining_control"].indexOf(stage);
  const titleEl = $("convThreatTitle");
  titleEl.className = "gl-threat-title " + (lvl === "safe" ? "safe" : lvl === "warn" ? "warn" : "");
  if (stage !== "none" && stageIdx > 0) {
    titleEl.textContent = `${c.category} — stage ${stageIdx}/5`;
  } else if (c.category && c.category !== "none") {
    titleEl.textContent = c.category;
  } else {
    titleEl.textContent = lvl === "safe" ? "Safe" : "Observed";
  }
  $("convThreatBody").textContent = c.short_summary || c.narrative || "No narrative yet.";
  const bar = $("convStageBar");
  if (stageIdx > 0) {
    bar.hidden = false;
    [...bar.children].forEach((span, i) => {
      span.className = i < stageIdx ? "on" : i === stageIdx ? "dim" : "";
    });
  } else {
    bar.hidden = true;
  }

  // Screenshot — latest captured frame for this conversation only.
  const shotsEl = $("convScreenshots");
  const shotsLabel = $("convScreenshotsLabel");
  const allShots = c.screenshots || [];
  const latestShot = allShots.length > 0 ? allShots[allShots.length - 1] : null;
  if (latestShot) {
    shotsLabel.hidden = false;
    shotsEl.hidden = false;
    shotsEl.innerHTML = `
      <div class="gl-screenshot single" title="${escapeHtml(latestShot.timestamp || "")}">
        <img src="${escapeHtml(latestShot.url)}" alt="latest capture" data-lightbox="1">
      </div>`;
  } else {
    shotsLabel.hidden = true;
    shotsEl.hidden = true;
    shotsEl.innerHTML = "";
  }

  // Arc — reconstruct from indicators (we don't have per-message stream here
  // yet, so render indicators as escalating dots).
  const arc = $("convArc");
  arc.innerHTML = "";
  const indicators = c.indicators || [];
  if (indicators.length === 0) {
    const row = document.createElement("div");
    row.className = "gl-arc-item";
    row.innerHTML = `<div class="gl-arc-dot"></div><div class="gl-arc-body"><div class="gl-arc-text">No flagged messages yet</div></div>`;
    arc.appendChild(row);
  } else {
    indicators.forEach((ind, i) => {
      const isAlert = lvl === "alert" && i >= indicators.length - 2;
      const dotCls = isAlert ? "alert" : lvl === "warn" ? "warn" : "";
      const row = document.createElement("div");
      row.className = "gl-arc-item";
      row.innerHTML = `
        <div class="gl-arc-dot ${dotCls}"></div>
        <div class="gl-arc-body">
          <div class="gl-arc-text ${dotCls}">${escapeHtml(prettyIndicator(ind))}</div>
          ${isAlert ? '<div class="gl-arc-label alert">Alert trigger</div>' : ""}
        </div>`;
      arc.appendChild(row);
    });
  }

  // AI reasoning — use the LLM's chain-of-thought directly.
  // Fall back to narrative, then to a minimal template if neither is available.
  const reasoningText = c.reasoning && c.reasoning.trim()
    ? c.reasoning
    : c.narrative && c.narrative.trim()
      ? c.narrative
      : `No reasoning available yet. Verdict: ${lvl.toUpperCase()} — ${c.category} — ${pct}%.`;
  $("convReasoning").textContent = reasoningText;

  // Actions
  const actList = $("convActions");
  actList.innerHTML = "";
  const actions = defaultActionsFor(c);
  actions.forEach((txt, i) => {
    const row = document.createElement("div");
    row.className = "gl-action-row";
    row.innerHTML = `<div class="gl-action-num">${i + 1}</div><div>${escapeHtml(txt)}</div>`;
    actList.appendChild(row);
  });

}

function defaultActionsFor(c) {
  const category = (c.category || "").toLowerCase();
  if (category.includes("grooming")) {
    return [
      "Talk to your child calmly about this conversation",
      `Ask who "${c.participant}" is — they may not know them`,
      "Block and report the account together",
    ];
  }
  if (category.includes("bullying")) {
    return [
      "Offer emotional support — this is not your child's fault",
      "Screenshot the conversation for school if needed",
      "Help your child block the user",
    ];
  }
  if (category.includes("scam")) {
    return [
      "Do not click any links or share credentials",
      "Show your child how to spot phishing",
      "Report the account to the platform",
    ];
  }
  return ["Review the conversation", "Check in with your child", "Decide next steps together"];
}

/* ---------------------------- environment detail -------------------- */
function renderEnvironmentDetail(snapshot, sel) {
  const e = (snapshot.environments || []).find(
    (x) => x.platform === sel.platform && x.context === sel.context
  );
  if (!e) {
    showState("stateSession");
    return;
  }

  const lvl = levelClass(e.overall_safety);
  const fam = platformFamily(e.platform);

  const avatar = $("envAvatar");
  avatar.className = `gl-avatar-square ${fam}`;
  avatar.textContent = platformLetters[fam] || "?";

  const name = $("envName");
  name.className = "gl-detail-name " + (lvl === "safe" ? "safe" : lvl);
  name.textContent = e.platform;

  const duration = prettyDuration(
    (new Date(e.last_seen).getTime() - new Date(e.first_seen).getTime()) / 1000
  );
  $("envSub").textContent = `${e.user_count || 0} users · ${duration} · ${e.content_type || "space"}`;

  const safety = $("envSafety");
  safety.className = "gl-detail-confidence " + (lvl === "safe" ? "safe" : lvl);
  safety.textContent = lvl === "safe" ? "SAFE" : lvl.toUpperCase();

  const threat = $("envThreat");
  threat.className = `gl-threat-summary ${lvl === "safe" ? "safe" : lvl === "warn" ? "warn" : ""}`;
  $("envThreatTitle").className = "gl-threat-title " + (lvl === "safe" ? "safe" : lvl === "warn" ? "warn" : "");
  $("envThreatTitle").textContent = lvl === "alert"
    ? "Concerning activity in public space"
    : lvl === "warn" ? "Watch this space" : "Normal space";
  $("envThreatBody").textContent = e.content_summary || "No summary yet.";

  // Users list — promoted users highlighted, other users safe
  const usersEl = $("envUsers");
  usersEl.innerHTML = "";
  const promoted = e.promoted_users || [];
  const allConvs = (snapshot.conversations || []).filter((c) => {
    const pr = String(c.source || "").startsWith("promoted_from_");
    return pr && promoted.includes(c.participant);
  });
  allConvs.forEach((c) => {
    const row = document.createElement("div");
    row.className = "gl-user-row alert";
    row.innerHTML = `
      <div class="gl-user-avatar alert">${initials(c.participant)}</div>
      <div class="gl-user-main">
        <div class="gl-user-top">
          <span class="gl-user-name alert">${escapeHtml(c.participant)}</span>
          <span class="gl-promoted-pill">promoted</span>
        </div>
        <div class="gl-user-sub alert">${escapeHtml((c.indicators || []).slice(0,2).join(", ") || c.category || "targeting")}</div>
      </div>`;
    usersEl.appendChild(row);
  });
  // Remaining users (we only know names via extracted_users approximated by user_count)
  const safeCount = Math.max(0, (e.user_count || 0) - promoted.length);
  if (safeCount > 0) {
    const row = document.createElement("div");
    row.className = "gl-user-row";
    row.innerHTML = `
      <div class="gl-user-avatar">
        <svg width="10" height="10" viewBox="0 0 16 16" fill="none"><path d="M5 8.5L7 10.5L11 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </div>
      <div class="gl-user-main">
        <div class="gl-user-top"><span class="gl-user-name">${safeCount} other user${safeCount === 1 ? "" : "s"}</span></div>
        <div class="gl-user-sub">Safe — normal activity</div>
      </div>`;
    usersEl.appendChild(row);
  }

  // Reasoning
  const rs = [
    `1: Platform: ${e.platform}`,
    `2: ${e.user_count || 0} users, public space`,
    `3: Content type: ${e.content_type || "unknown"}`,
  ];
  if (promoted.length > 0) {
    rs.push(`4: Targeting detected — promoted: ${promoted.join(", ")}`);
  }
  (e.indicators || []).forEach((ind) => rs.push(`   → ${ind}`));
  rs.push(`${lvl === "alert" ? "ALERT" : lvl.toUpperCase()} — ${e.platform}`);
  $("envReasoning").textContent = rs.join("\n");

  // Actions
  const actList = $("envActions");
  actList.innerHTML = "";
  const actions = promoted.length > 0
    ? [
      `Ask your child about ${promoted[0]}`,
      `Review the ${e.platform} environment`,
      "Consider stricter platform settings",
    ]
    : [`Monitor the ${e.platform} environment`, "Check that content is age-appropriate"];
  actions.forEach((txt, i) => {
    const row = document.createElement("div");
    row.className = "gl-action-row";
    row.innerHTML = `<div class="gl-action-num">${i + 1}</div><div>${escapeHtml(txt)}</div>`;
    actList.appendChild(row);
  });
}

/* ---------------------------- state switcher ------------------------ */
function showState(which) {
  ["stateSession", "stateConversation", "stateEnvironment"].forEach((id) => {
    $(id).hidden = id !== which;
  });
}

function selectionKey(sel) {
  if (!sel) return null;
  return sel.kind === "conversation"
    ? `c:${sel.platform}:${sel.participant}`
    : `e:${sel.platform}:${sel.context}`;
}

/* ---------------------------- main render --------------------------- */
function render() {
  const snapshot = ui.snapshot;
  if (!snapshot) return;

  // Header
  const dot = $("statusDot");
  dot.classList.remove("paused", "off");
  const isActive = snapshot.monitoring && !snapshot.paused;
  if (!snapshot.monitoring && !snapshot.paused) dot.classList.add("off");
  else if (snapshot.paused) dot.classList.add("paused");
  $("statusLabel").textContent = snapshot.paused
    ? "Paused"
    : snapshot.monitoring ? "Active" : "Off";
  $("modelChip").textContent = snapshot.model_name || "—";

  // Pause button reflects the actual state — icon + label flip together.
  const pauseBtn = $("pauseBtn");
  const pauseIcon = $("pauseIcon");
  const pauseLabel = $("pauseLabel");
  if (snapshot.paused) {
    pauseBtn.classList.add("paused");
    pauseIcon.textContent = "▶";
    pauseLabel.textContent = "Resume";
  } else {
    pauseBtn.classList.remove("paused");
    pauseIcon.textContent = "⏸";
    pauseLabel.textContent = "Pause";
  }

  // Capture pause overlay
  const overlay = $("captureOverlay");
  if (snapshot.paused) {
    overlay.classList.remove("hidden");
    $("captureOverlaySub").textContent = `Paused at ${snapshot.session_duration || "0s"}`;
    $("captureCard").classList.add("paused");
  } else {
    overlay.classList.add("hidden");
    $("captureCard").classList.remove("paused");
  }

  // Unread counter = flagged items the parent hasn't clicked yet.
  // `alert_total` is kept for the left-panel stats row (lifetime count),
  // but the bell is inbox-style and counts UNREAD only.
  const flaggedItems = gatherFlaggedItems(snapshot);
  const unreadCount = flaggedItems.filter(
    (it) => !ui.seenAlerts.has(alertId(it.kind, it.data))
  ).length;
  const bell = $("bellWrap");
  const badge = $("bellBadge");
  if (unreadCount > 0) {
    bell.classList.add("has-alerts");
    badge.hidden = false;
    badge.textContent = String(unreadCount);
  } else {
    bell.classList.remove("has-alerts");
    badge.hidden = true;
  }

  renderAlertsMenu(snapshot, flaggedItems);

  // Left — capture + stats + activity
  renderCapture(snapshot);
  const convs = snapshot.conversations || [];
  const envs = snapshot.environments || [];

  renderActivity(convs);

  // Right — session / conversation / environment
  if (ui.selection) {
    if (ui.selection.kind === "conversation") {
      showState("stateConversation");
      renderConversationDetail(snapshot, ui.selection);
    } else {
      showState("stateEnvironment");
      renderEnvironmentDetail(snapshot, ui.selection);
    }
  } else {
    showState("stateSession");
    renderSessionOverview(snapshot);
  }

  // Privacy footer details
  const priv = snapshot.privacy || {};
  const net = priv.network || {};
  $("privacySub").textContent = net.ollama_local
    ? `0 bytes to cloud`
    : `NOT LOCAL — ${net.ollama_host || "?"}`;

  // Auto-show State 2 for the newest alerting conversation when no selection yet.
  // Key includes threat_level so an escalation (caution→alert on the same
  // person) produces a new key and re-pops the detail view — otherwise the
  // parent would miss the new severity if they were on the session overview.
  const topAlert = (convs || []).find((c) => c.threat_level === "alert" || c.threat_level === "critical");
  if (topAlert && !ui.selection) {
    const key = `c:${topAlert.platform}:${topAlert.participant}:${topAlert.threat_level}`;
    if (ui.lastAutoAlertKey !== key) {
      ui.lastAutoAlertKey = key;
      ui.selection = { kind: "conversation", platform: topAlert.platform, participant: topAlert.participant };
      showState("stateConversation");
      renderConversationDetail(snapshot, ui.selection);
    }
  }
}

/* ---------------------------- alerts menu --------------------------- */
// The bell is the primary entry point for "what needs attention".
// The dropdown aggregates any flagged conversation or environment and
// lets the parent click through to the same detail view they'd see from
// the activity list. Safe-only sessions get an empty-state message.

function gatherFlaggedItems(snapshot) {
  // Alerts are per-user. Environments are context — their concern is
  // surfaced through their promoted users, who are already tracked as
  // conversations. Firing a second "discord environment warning" alert
  // on top of "NitroBot on Discord" would double-count the same incident.
  //
  // The only case where an environment would earn its own bell alert is
  // a space-level concern with no promotable party (e.g., exposure to
  // broadly inappropriate content). We conservatively skip that for now;
  // the environment still appears in the left-panel activity list as
  // context, and will drive a session-narrative entry.
  const convs = snapshot.conversations || [];
  const items = convs
    .filter((c) => c.threat_level !== "safe")
    .map((c) => ({ kind: "conversation", data: c, level: c.threat_level }));
  items.sort((a, b) => {
    const order = { alert: 0, critical: 0, warning: 1, caution: 2 };
    return (order[a.level] ?? 9) - (order[b.level] ?? 9);
  });
  return items;
}

function renderAlertsMenu(snapshot, items) {
  const list = $("alertsList");
  const empty = $("alertsEmpty");
  const head = $("alertsHeadText");

  const unread = items.filter((it) => !ui.seenAlerts.has(alertId(it.kind, it.data)));
  head.textContent = unread.length > 0
    ? `Alerts (${unread.length} new)`
    : items.length > 0 ? `Alerts (${items.length} read)` : "Alerts";

  list.innerHTML = "";
  if (items.length === 0) {
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  for (const it of items) {
    const row = document.createElement("div");
    const lvl = levelClass(it.level);
    const key = alertId(it.kind, it.data);
    const isUnread = !ui.seenAlerts.has(key);
    row.className = `gl-alert-item ${lvl === "safe" ? "" : lvl} ${isUnread ? "unread" : "read"}`;
    if (it.kind === "conversation") {
      const c = it.data;
      const names = (c.participants && c.participants.length > 0)
        ? c.participants
        : (c.participant ? [c.participant] : []);
      const shown = names.slice(0, 3).join(", ");
      const extra = names.length > 3 ? ` +${names.length - 3}` : "";
      const title = shown ? shown + extra : "Unknown";
      const firstAgo = c.first_seen ? timeAgo(c.first_seen) : "";
      row.innerHTML = `
        ${isUnread ? '<span class="gl-alert-dot"></span>' : ""}
        <div class="gl-alert-icon ${lvl}">${initials(names[0] || "?")}</div>
        <div class="gl-alert-main">
          <div class="gl-alert-top ${lvl}"><span class="gl-alert-name" title="${escapeHtml(names.join(", "))}">${escapeHtml(title)}</span><span class="gl-alert-time">${escapeHtml(firstAgo || c.platform)}</span></div>
          <div class="gl-alert-sub">${escapeHtml(shortNarrative(c))}</div>
        </div>`;
      row.addEventListener("click", () => {
        markSeen(key);
        ui.selection = { kind: "conversation", platform: c.platform, participant: c.participant };
        closeAlertsMenu();
        render();
      });
    } else {
      const e = it.data;
      const fam = platformFamily(e.platform);
      row.innerHTML = `
        ${isUnread ? '<span class="gl-alert-dot"></span>' : ""}
        <div class="gl-alert-icon env ${fam}">${platformLetters[fam] || "?"}</div>
        <div class="gl-alert-main">
          <div class="gl-alert-top ${lvl}"><span class="gl-alert-name">${escapeHtml(e.platform)}</span><span class="gl-alert-time">${e.user_count || 0} users</span></div>
          <div class="gl-alert-sub">${escapeHtml(e.content_summary || "concerning activity")}</div>
        </div>`;
      row.addEventListener("click", () => {
        markSeen(key);
        ui.selection = { kind: "environment", platform: e.platform, context: e.context };
        closeAlertsMenu();
        render();
      });
    }
    list.appendChild(row);
  }
}

function toggleAlertsMenu() {
  const m = $("alertsMenu");
  m.hidden = !m.hidden;
}
function closeAlertsMenu() { $("alertsMenu").hidden = true; }

/* ---------------------------- events -------------------------------- */
document.addEventListener("click", (evt) => {
  const back = evt.target.closest("[data-back]");
  if (back) {
    ui.selection = null;
    render();
    return;
  }
  // Bell toggles the alerts dropdown.
  if (evt.target.closest("#bellWrap")) {
    toggleAlertsMenu();
    return;
  }
  if (evt.target.closest("#alertsClose")) {
    closeAlertsMenu();
    return;
  }
  if (evt.target.closest("#alertsMarkAll")) {
    const items = gatherFlaggedItems(ui.snapshot || {});
    items.forEach((it) => markSeen(alertId(it.kind, it.data)));
    render();
    return;
  }
  // Click outside the menu closes it.
  const inMenu = evt.target.closest("#alertsMenu");
  if (!inMenu) closeAlertsMenu();
});

$("pauseBtn").addEventListener("click", async () => {
  if (!ui.snapshot) return;
  const wasPaused = Boolean(ui.snapshot.paused);
  const path = wasPaused ? "/api/resume" : "/api/pause";
  // Optimistic flip so the button doesn't feel dead while the POST
  // is in flight. The next SSE frame will either confirm or correct it.
  ui.snapshot = { ...ui.snapshot, paused: !wasPaused };
  render();
  try {
    const res = await fetch(path, { method: "POST" });
    if (!res.ok) {
      // Roll back on server error — the next SSE frame will be authoritative.
      ui.snapshot = { ...ui.snapshot, paused: wasPaused };
      render();
    }
  } catch {
    ui.snapshot = { ...ui.snapshot, paused: wasPaused };
    render();
  }
});

/* ---------------------------- SSE ----------------------------------- */
function connect() {
  const es = new EventSource("/api/stream");
  es.onmessage = (evt) => {
    try {
      ui.snapshot = JSON.parse(evt.data);
      render();
    } catch (e) {
      console.warn("SSE parse error", e);
    }
  };
  es.onerror = () => {
    es.close();
    setTimeout(connect, 2000);
  };
}

/* ---------------------------- util ---------------------------------- */
function prettyIndicator(s) {
  if (!s) return "";
  const cleaned = String(s).replace(/[_\-]+/g, " ").trim();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1).toLowerCase();
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/* ---------------------------- lightbox ------------------------------ */
function openLightbox(src) {
  const box = $("lightbox");
  const img = $("lightboxImg");
  img.src = src;
  box.hidden = false;
  document.body.style.overflow = "hidden";
}
function closeLightbox() {
  $("lightbox").hidden = true;
  $("lightboxImg").src = "";
  document.body.style.overflow = "";
}
document.addEventListener("click", (e) => {
  const img = e.target.closest("[data-lightbox]");
  if (img && img.tagName === "IMG") {
    openLightbox(img.src);
    return;
  }
  if (e.target.id === "lightbox" || e.target.id === "lightboxClose") {
    closeLightbox();
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("lightbox").hidden) closeLightbox();
});

/* ---------------------------- bootstrap ----------------------------- */
fetch("/api/state").then((r) => r.json()).then((s) => {
  ui.snapshot = s;
  render();
  connect();
}).catch(() => connect());
