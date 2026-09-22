// src/index.ts
var RUNTIME_SCRIPT_ID = "featurebase-sdk";
function isFeaturebaseDevMode() {
  var _a;
  if (typeof window !== "undefined") {
    const flag = window.FEATUREBASE_ENV;
    if (flag === "development") return true;
  }
  try {
    if (typeof process !== "undefined" && ((_a = process.env) == null ? void 0 : _a.NEXT_PUBLIC_ENVIRONMENT) === "development") {
      return true;
    }
  } catch (e) {
  }
  return false;
}
function getRuntimeScriptSrc() {
  return isFeaturebaseDevMode() ? "https://sdk.fbasedev.com/dist/sdk.js" : "https://do.featurebase.app/js/sdk.js";
}
function getResolverBaseUrl() {
  return isFeaturebaseDevMode() ? "https://do.fbasedev.com/v1/organization/by-id/" : "https://do.featurebase.app/v1/organization/by-id/";
}
var RESOLVER_CACHE_PREFIX = "featurebase-js:org:";
var RESOLVER_CACHE_TTL_MS = 20 * 60 * 1e3;
var bootedAppId = null;
var isReady = false;
var readyCallbacks = [];
var SHUTDOWN_GRACE_MS = 250;
var BOOT_WINDOW_MS = 2e3;
var BOOT_LIMIT = 10;
var BOOT_COOLDOWN_MS = 3e4;
var pendingShutdownTimer = null;
var recentBootTimestamps = [];
var bootCooldownUntil = 0;
var bootCooldownLogged = false;
var bootCooldownLoggedTimer = null;
function flushReady() {
  isReady = true;
  const pending = readyCallbacks;
  readyCallbacks = [];
  for (const cb of pending) {
    try {
      cb();
    } catch (err) {
      console.error("[featurebase-js] whenReady callback threw:", err);
    }
  }
}
function isBrowser() {
  return typeof window !== "undefined" && typeof document !== "undefined";
}
function ensureLoaded() {
  if (!isBrowser()) return;
  if (typeof window.Featurebase !== "function") {
    const stub = function queueStub(...args) {
      (stub.q || (stub.q = [])).push(args);
    };
    stub.q = [];
    window.Featurebase = stub;
  }
  if (!document.getElementById(RUNTIME_SCRIPT_ID)) {
    const script = document.createElement("script");
    script.id = RUNTIME_SCRIPT_ID;
    script.src = getRuntimeScriptSrc();
    script.defer = true;
    document.head.appendChild(script);
  }
}
function normalizeSettings(settings) {
  var _a, _b, _c, _d, _e, _f, _g, _h, _i, _j, _k, _l, _m, _n;
  const appId = (_a = settings.appId) != null ? _a : settings.app_id;
  if (typeof appId !== "string" || appId.length === 0) {
    throw new Error("[featurebase-js] `appId` is required.");
  }
  const out = { appId: String(appId) };
  const userId = (_b = settings.userId) != null ? _b : settings.user_id;
  if (userId !== void 0) out.userId = String(userId);
  if (settings.email !== void 0) out.email = settings.email;
  if (settings.name !== void 0) out.name = settings.name;
  const userHash = (_c = settings.userHash) != null ? _c : settings.user_hash;
  if (userHash !== void 0) out.userHash = userHash;
  if (settings.featurebaseJwt !== void 0) out.featurebaseJwt = settings.featurebaseJwt;
  const createdAt = (_d = settings.createdAt) != null ? _d : settings.created_at;
  if (createdAt !== void 0) out.createdAt = String(createdAt);
  if (settings.company !== void 0) out.company = settings.company;
  if (settings.companies !== void 0) out.companies = settings.companies;
  if (settings.$brandId !== void 0) out.$brandId = settings.$brandId;
  const theme = (_f = (_e = settings.theme) != null ? _e : settings.themeMode) != null ? _f : settings.theme_mode;
  if (theme !== void 0) out.theme = theme;
  const language = (_h = (_g = settings.language) != null ? _g : settings.languageOverride) != null ? _h : settings.language_override;
  if (language !== void 0) out.language = language;
  const hideDefaultLauncher = (_i = settings.hideDefaultLauncher) != null ? _i : settings.hide_default_launcher;
  if (hideDefaultLauncher !== void 0) out.hideDefaultLauncher = hideDefaultLauncher;
  if (settings.alignment !== void 0) out.alignment = settings.alignment;
  const horizontalPadding = (_j = settings.horizontalPadding) != null ? _j : settings.horizontal_padding;
  if (horizontalPadding !== void 0) out.horizontalPadding = horizontalPadding;
  const verticalPadding = (_k = settings.verticalPadding) != null ? _k : settings.vertical_padding;
  if (verticalPadding !== void 0) out.verticalPadding = verticalPadding;
  const actionColor = (_l = settings.actionColor) != null ? _l : settings.action_color;
  if (actionColor !== void 0) out.actionColor = actionColor;
  const backgroundColor = (_m = settings.backgroundColor) != null ? _m : settings.background_color;
  if (backgroundColor !== void 0) out.backgroundColor = backgroundColor;
  const customData = (_n = settings.customData) != null ? _n : settings.custom_data;
  if (customData !== void 0) out.customData = customData;
  const handled = /* @__PURE__ */ new Set([
    "appId",
    "app_id",
    "messenger",
    "userId",
    "user_id",
    "email",
    "name",
    "userHash",
    "user_hash",
    "featurebaseJwt",
    "createdAt",
    "created_at",
    "company",
    "companies",
    "$brandId",
    "theme",
    "themeMode",
    "theme_mode",
    "language",
    "languageOverride",
    "language_override",
    "hideDefaultLauncher",
    "hide_default_launcher",
    "alignment",
    "horizontalPadding",
    "horizontal_padding",
    "verticalPadding",
    "vertical_padding",
    "actionColor",
    "action_color",
    "backgroundColor",
    "background_color",
    "customData",
    "custom_data"
  ]);
  for (const [key, value] of Object.entries(settings)) {
    if (!handled.has(key) && value !== void 0) out[key] = value;
  }
  return out;
}
function Featurebase(settings) {
  var _a;
  if (!isBrowser()) return;
  ensureLoaded();
  const appId = (_a = settings.appId) != null ? _a : settings.app_id;
  if (appId === void 0) {
    throw new Error(
      "[featurebase-js] Featurebase() requires `appId`. Pass the value the dashboard shows under Settings \u2192 Support \u2192 Installation."
    );
  }
  syncWidgetIdentityFromSettings(settings);
  const apply = (info) => {
    setWidgetSlug(info.slug);
    const wantsMessenger = settings.messenger !== false && info.modules.support;
    if (wantsMessenger) {
      bootMessenger(settings);
    }
  };
  const cached = peekResolverCache(appId);
  if (cached) {
    apply(cached);
    return;
  }
  resolveOrganization(appId).then(apply, (err) => {
    console.error("[featurebase-js] failed to resolve organization for appId=" + appId + ":", err);
    drainPendingDispatches(err instanceof Error ? err : new Error(String(err)));
  });
}
function bootMessenger(settings) {
  const normalized = normalizeSettings(settings);
  attachResolvedOrganization(normalized);
  if (pendingShutdownTimer !== null) {
    clearTimeout(pendingShutdownTimer);
    pendingShutdownTimer = null;
    if (bootedAppId !== normalized.appId) {
      flushShutdownNow();
    }
  } else if (bootedAppId !== null && bootedAppId !== normalized.appId) {
    flushShutdownNow();
  }
  if (bootedAppId === normalized.appId) {
    window.Featurebase("identify", normalized);
    return;
  }
  if (shouldBackOffFromBoot(normalized.appId)) return;
  window.Featurebase("boot", normalized, (error) => {
    if (error) console.error("[featurebase-js] boot reported an error:", error);
    flushReady();
  });
  bootedAppId = normalized.appId;
}
function flushShutdownNow() {
  if (pendingShutdownTimer !== null) {
    clearTimeout(pendingShutdownTimer);
    pendingShutdownTimer = null;
  }
  if (!isBrowser()) return;
  if (typeof window.Featurebase === "function") {
    window.Featurebase("shutdown");
  }
  bootedAppId = null;
  isReady = false;
  readyCallbacks = [];
}
function shouldBackOffFromBoot(appId) {
  const now = Date.now();
  if (now < bootCooldownUntil) return true;
  while (recentBootTimestamps.length > 0 && now - recentBootTimestamps[0] > BOOT_WINDOW_MS) {
    recentBootTimestamps.shift();
  }
  recentBootTimestamps.push(now);
  if (recentBootTimestamps.length > BOOT_LIMIT) {
    bootCooldownUntil = now + BOOT_COOLDOWN_MS;
    recentBootTimestamps.length = 0;
    if (!bootCooldownLogged) {
      bootCooldownLogged = true;
      console.error(
        `[featurebase-js] boot/shutdown loop detected for appId=${appId} \u2014 >${BOOT_LIMIT} cycles in ${BOOT_WINDOW_MS}ms. Pausing further boot dispatches for ${BOOT_COOLDOWN_MS / 1e3}s. The most common cause is a <FeaturebaseProvider> being unmounted on every render \u2014 for example, wrapping it in a component declared inside another component's render body, or remounting via an unstable \`key\`. See https://featurebase.app/docs/sdk/react#stable-mount`
      );
      if (bootCooldownLoggedTimer !== null) clearTimeout(bootCooldownLoggedTimer);
      bootCooldownLoggedTimer = setTimeout(() => {
        bootCooldownLogged = false;
        bootCooldownLoggedTimer = null;
      }, BOOT_COOLDOWN_MS);
    }
    return true;
  }
  return false;
}
function syncWidgetIdentityFromSettings(settings) {
  var _a, _b;
  const identity = {};
  if (settings.featurebaseJwt !== void 0) {
    identity.featurebaseJwt = settings.featurebaseJwt;
  }
  if (typeof settings.jwtToken === "string") {
    identity.jwtToken = settings.jwtToken;
  }
  const userId = (_a = settings.userId) != null ? _a : settings.user_id;
  if (userId !== void 0) {
    identity.userId = String(userId);
  }
  if (settings.email !== void 0) identity.email = settings.email;
  const userHash = (_b = settings.userHash) != null ? _b : settings.user_hash;
  if (userHash !== void 0) identity.userHash = userHash;
  if (Object.keys(identity).length > 0) {
    configure(identity);
  }
}
function setWidgetSlug(slug) {
  resolvedOrgSlug = slug;
  flushPendingDispatches();
}
function boot(settings) {
  var _a;
  if (!isBrowser()) return;
  ensureLoaded();
  const appId = (_a = settings.appId) != null ? _a : settings.app_id;
  if (appId === void 0) {
    throw new Error("[featurebase-js] boot() requires `appId`.");
  }
  bootMessenger(settings);
}
function update(settings) {
  var _a, _b, _c;
  if (!isBrowser()) return;
  ensureLoaded();
  if (!settings) {
    const payload = {};
    attachResolvedOrganization(payload);
    window.Featurebase("identify", payload);
    return;
  }
  const candidate = (_c = (_b = (_a = settings.appId) != null ? _a : settings.app_id) != null ? _b : bootedAppId) != null ? _c : void 0;
  const normalized = candidate ? normalizeSettings({ ...settings, appId: candidate }) : { ...settings };
  attachResolvedOrganization(normalized);
  window.Featurebase("identify", normalized);
}
function attachResolvedOrganization(payload) {
  if (typeof resolvedOrgSlug === "string" && resolvedOrgSlug.length > 0) {
    payload.organization = resolvedOrgSlug;
  }
}
function shutdown() {
  if (!isBrowser()) return;
  ensureLoaded();
  if (pendingShutdownTimer !== null) return;
  pendingShutdownTimer = setTimeout(flushShutdownNow, SHUTDOWN_GRACE_MS);
}
function whenReady(callback) {
  if (!isBrowser()) return;
  if (isReady) {
    queueMicrotask(callback);
    return;
  }
  readyCallbacks.push(callback);
}
function show() {
  call("show");
}
function hide() {
  call("hide");
}
function showSpace(space) {
  call("show", space);
}
function showMessages() {
  call("show", "messages");
}
function showArticle(id) {
  call("showArticle", String(id));
}
function showChangelog(id) {
  call("showChangelog", id !== void 0 ? String(id) : void 0);
}
function showNews(id) {
  call("showChangelog", String(id));
}
function showConversation(id) {
  call("showConversation", String(id));
}
function showNewMessage(text) {
  call("showNewMessage", text);
}
function setTheme(theme) {
  call("setTheme", theme);
}
function setLanguage(lang) {
  call("setLanguage", lang);
}
function onShow(callback) {
  call("onShow", callback);
}
function onHide(callback) {
  call("onHide", callback);
}
function onUnreadCountChange(callback) {
  call("onUnreadCountChange", callback);
}
function onExternalLinkOpen(callback) {
  call("onExternalLinkOpen", callback);
}
var resolverCache = /* @__PURE__ */ new Map();
var pendingResolutions = /* @__PURE__ */ new Map();
var pendingDispatches = [];
function readResolverCacheFromStorage(appId) {
  var _a;
  if (!isBrowser()) return null;
  try {
    const raw = window.localStorage.getItem(RESOLVER_CACHE_PREFIX + appId);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (typeof (parsed == null ? void 0 : parsed.fetchedAt) !== "number") return null;
    if (Date.now() - parsed.fetchedAt > RESOLVER_CACHE_TTL_MS) return null;
    if (typeof ((_a = parsed == null ? void 0 : parsed.info) == null ? void 0 : _a.slug) !== "string") return null;
    return parsed.info;
  } catch (e) {
    return null;
  }
}
function writeResolverCacheToStorage(appId, info) {
  if (!isBrowser()) return;
  try {
    window.localStorage.setItem(
      RESOLVER_CACHE_PREFIX + appId,
      JSON.stringify({ info, fetchedAt: Date.now() })
    );
  } catch (e) {
  }
}
function peekResolverCache(appId) {
  const inMem = resolverCache.get(appId);
  if (inMem) return inMem;
  const stored = readResolverCacheFromStorage(appId);
  if (stored) {
    resolverCache.set(appId, stored);
    return stored;
  }
  return null;
}
function resolveOrganization(appId) {
  if (!isBrowser()) {
    return Promise.reject(new Error("[featurebase-js] resolveOrganization requires a browser environment."));
  }
  const cached = resolverCache.get(appId);
  if (cached) return Promise.resolve(cached);
  const stored = readResolverCacheFromStorage(appId);
  if (stored) {
    resolverCache.set(appId, stored);
    return Promise.resolve(stored);
  }
  const inflight = pendingResolutions.get(appId);
  if (inflight) return inflight;
  const promise = fetch(getResolverBaseUrl() + encodeURIComponent(appId), {
    method: "GET",
    credentials: "omit",
    mode: "cors"
  }).then((res) => {
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    return res.json();
  }).then((body) => {
    var _a;
    if (!body || body.success === false || typeof body.slug !== "string") {
      throw new Error("invalid resolver response");
    }
    const info = {
      slug: body.slug,
      modules: { support: !!((_a = body.modules) == null ? void 0 : _a.support) }
    };
    resolverCache.set(appId, info);
    writeResolverCacheToStorage(appId, info);
    return info;
  }).finally(() => {
    pendingResolutions.delete(appId);
  });
  pendingResolutions.set(appId, promise);
  return promise;
}
function queueDispatch(thunk) {
  pendingDispatches.push(thunk);
}
function flushPendingDispatches() {
  if (pendingDispatches.length === 0) return;
  const queued = pendingDispatches.splice(0, pendingDispatches.length);
  for (const dispatch of queued) {
    try {
      dispatch();
    } catch (err) {
      console.error("[featurebase-js] queued widget dispatch failed:", err);
    }
  }
}
function drainPendingDispatches(reason) {
  if (pendingDispatches.length === 0) return;
  const dropped = pendingDispatches.length;
  pendingDispatches.length = 0;
  console.error(
    `[featurebase-js] dropping ${dropped} queued widget dispatch(es) \u2014 resolver failed:`,
    reason
  );
}
var widgetDefaults = {};
var resolvedOrgSlug;
function configure(defaults) {
  widgetDefaults = { ...widgetDefaults, ...pickDefined(defaults) };
}
function clearConfig() {
  widgetDefaults = {};
  resolvedOrgSlug = void 0;
}
function getWidgetDefaults() {
  return widgetDefaults;
}
function pickDefined(input) {
  const out = {};
  for (const [k, v] of Object.entries(input)) {
    if (v !== void 0) out[k] = v;
  }
  return out;
}
function withWidgetDefaults(config, caller) {
  const merged = { ...widgetDefaults, ...pickDefined(config) };
  if (typeof resolvedOrgSlug !== "string" || resolvedOrgSlug.length === 0) {
    throw new Error(
      `[featurebase-js] ${caller}: workspace not initialized. Call \`Featurebase({ appId: "..." })\` once at startup before invoking widget hooks.`
    );
  }
  return { ...merged, organization: resolvedOrgSlug };
}
function isWidgetSlugKnown() {
  return typeof resolvedOrgSlug === "string" && resolvedOrgSlug.length > 0;
}
function isResolverInFlight() {
  return pendingResolutions.size > 0;
}
function initChangelog(config) {
  if (!isBrowser()) return;
  if (!isWidgetSlugKnown() && isResolverInFlight()) {
    const snapshot = { ...config };
    queueDispatch(() => initChangelog(snapshot));
    return;
  }
  const resolved = withWidgetDefaults(
    config,
    "initChangelog"
  );
  call("init_changelog_widget", resolved);
}
function initLegacyChangelog(config) {
  if (!isBrowser()) return;
  if (!isWidgetSlugKnown() && isResolverInFlight()) {
    const snapshot = { ...config };
    queueDispatch(() => initLegacyChangelog(snapshot));
    return;
  }
  const resolved = withWidgetDefaults(
    config,
    "initLegacyChangelog"
  );
  call("initialize_changelog_widget", resolved);
}
function openChangelogPopup(data) {
  call("manually_open_changelog_popup", data);
}
function markAllChangelogsAsViewed() {
  call("set_all_changelogs_as_viewed");
}
function getUnviewedChangelogCount() {
  return callWithReturn("unviewed_changelog_count");
}
function destroyChangelog() {
  call("destroy_changelog_widget");
}
function initFeedback(config) {
  if (!isBrowser()) return;
  if (!isWidgetSlugKnown() && isResolverInFlight()) {
    const snapshot = { ...config };
    queueDispatch(() => initFeedback(snapshot));
    return;
  }
  const resolved = withWidgetDefaults(
    config,
    "initFeedback"
  );
  call("initialize_feedback_widget", resolved);
}
function destroyFeedback() {
  call("destroy_feedback_widget");
}
function initSurveys(config = {}) {
  if (!isBrowser()) return;
  if (!isWidgetSlugKnown() && isResolverInFlight()) {
    const snapshot = { ...config };
    queueDispatch(() => initSurveys(snapshot));
    return;
  }
  const resolved = withWidgetDefaults(
    config,
    "initSurveys"
  );
  call("initialize_survey_widget", resolved);
}
function initEmbedWidget(config, callback) {
  if (!isBrowser()) return;
  if (!isWidgetSlugKnown() && isResolverInFlight()) {
    const snapshot = { ...config };
    queueDispatch(() => initEmbedWidget(snapshot, callback));
    return;
  }
  const resolved = withWidgetDefaults(
    config,
    "initEmbedWidget"
  );
  call(
    "init_embed_widget",
    resolved,
    callback
  );
}
function call(action, data, callback) {
  if (!isBrowser()) return;
  ensureLoaded();
  if (callback) {
    window.Featurebase(action, data, callback);
  } else {
    window.Featurebase(action, data);
  }
}
function callWithReturn(action, data) {
  if (!isBrowser()) return void 0;
  ensureLoaded();
  const result = window.Featurebase(action, data);
  return result;
}
var SUPPORTED_ACTIONS = [
  "boot",
  "update",
  "shutdown",
  "show",
  "hide",
  "showSpace",
  "showMessages",
  "showArticle",
  "showChangelog",
  "showNews",
  "showConversation",
  "showNewMessage",
  "setTheme",
  "setLanguage",
  "onShow",
  "onHide",
  "onUnreadCountChange",
  "onExternalLinkOpen",
  "configure",
  "clearConfig",
  "resolveOrganization",
  "initChangelog",
  "initLegacyChangelog",
  "openChangelogPopup",
  "markAllChangelogsAsViewed",
  "getUnviewedChangelogCount",
  "destroyChangelog",
  "initFeedback",
  "destroyFeedback",
  "initSurveys",
  "initEmbedWidget"
];
function __resetForTests() {
  bootedAppId = null;
  isReady = false;
  readyCallbacks = [];
  widgetDefaults = {};
  resolvedOrgSlug = void 0;
  resolverCache.clear();
  pendingResolutions.clear();
  pendingDispatches.length = 0;
  if (pendingShutdownTimer !== null) {
    clearTimeout(pendingShutdownTimer);
    pendingShutdownTimer = null;
  }
  if (bootCooldownLoggedTimer !== null) {
    clearTimeout(bootCooldownLoggedTimer);
    bootCooldownLoggedTimer = null;
  }
  recentBootTimestamps.length = 0;
  bootCooldownUntil = 0;
  bootCooldownLogged = false;
}
function __primeResolverForTests(appId, info = {}) {
  var _a, _b;
  resolverCache.set(appId, {
    slug: (_a = info.slug) != null ? _a : "test-org",
    modules: (_b = info.modules) != null ? _b : { support: true }
  });
}

export { SUPPORTED_ACTIONS, __primeResolverForTests, __resetForTests, boot, clearConfig, configure, Featurebase as default, destroyChangelog, destroyFeedback, getUnviewedChangelogCount, getWidgetDefaults, hide, initChangelog, initEmbedWidget, initFeedback, initLegacyChangelog, initSurveys, markAllChangelogsAsViewed, normalizeSettings, onExternalLinkOpen, onHide, onShow, onUnreadCountChange, openChangelogPopup, peekResolverCache, resolveOrganization, setLanguage, setTheme, show, showArticle, showChangelog, showConversation, showMessages, showNewMessage, showNews, showSpace, shutdown, update, whenReady };
//# sourceMappingURL=index.js.map
//# sourceMappingURL=index.js.map