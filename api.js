/* LabGuard API client. No credentials are embedded in this file. */
(() => {
  "use strict";
  const jwtKey = "labguard_cognito_jwt_session";
  const getConfig = () => {
    try {
      const s = JSON.parse(localStorage.getItem("labguard_demo_v1") || "{}");
      return s.config || { apiBaseUrl: "", mode: "demo" };
    } catch (_) { return { apiBaseUrl: "", mode: "demo" }; }
  };
  async function request(path, options = {}) {
    const cfg = getConfig();
    if (!cfg.apiBaseUrl || !/^https:\/\/.+/i.test(cfg.apiBaseUrl)) {
      throw new Error("Configure the HTTPS API Gateway URL in Settings first.");
    }
    const token = sessionStorage.getItem(jwtKey) || "";
    if (path !== "/health" && !token) throw new Error("Live mode requires a Cognito JWT. Paste a short-lived token in Settings.");
    let response;
    try {
      response = await fetch(cfg.apiBaseUrl.replace(/\/+$/, "") + path, {
        method: options.method || "GET",
        headers: {
          ...(path !== "/health" ? { Authorization: "Bearer " + token } : {}),
          ...(options.body ? { "Content-Type": "application/json" } : {})
        },
        body: options.body ? JSON.stringify(options.body) : undefined,
        cache: "no-store"
      });
    } catch (_) {
      throw new Error("Could not reach the backend. Check the API URL, internet connection, and CORS configuration.");
    }
    let payload = {};
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(payload.error || `Backend request failed (${response.status}).`);
    return payload;
  }
  window.LabGuardApi = {
    setJwt(token) {
      const clean = String(token || "").trim();
      if (clean) sessionStorage.setItem(jwtKey, clean);
      else sessionStorage.removeItem(jwtKey);
    },
    hasJwt() { return Boolean(sessionStorage.getItem(jwtKey)); },
    health: () => request("/health"),
    listIncidents: () => request("/incidents?pageSize=100"),
    createIncident: data => request("/incidents", { method: "POST", body: data }),
    updateIncident: (id, data) => request("/incidents/" + encodeURIComponent(id), { method: "PATCH", body: data }),
    labStatus: () => request("/lab/status"),
    notifications: () => request("/notifications?pageSize=100")
  };
})();
