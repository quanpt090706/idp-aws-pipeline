const TOKEN_KEY = "idp-tv1-token";
const STATE_KEY = "idp-tv1-oauth-state";
const VERIFIER_KEY = "idp-tv1-oauth-verifier";

function base64url(bytes) {
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function redirectUri(location) {
  return `${location.origin}/`;
}

export async function loginUrl(config, storage, cryptoApi, location) {
  const verifier = base64url(cryptoApi.getRandomValues(new Uint8Array(32)));
  const state = base64url(cryptoApi.getRandomValues(new Uint8Array(24)));
  const challenge = base64url(new Uint8Array(await cryptoApi.subtle.digest("SHA-256", new TextEncoder().encode(verifier))));
  storage.setItem(STATE_KEY, state);
  storage.setItem(VERIFIER_KEY, verifier);
  const url = new URL("/oauth2/authorize", config.cognitoDomain);
  url.search = new URLSearchParams({
    response_type: "code", client_id: config.clientId,
    redirect_uri: redirectUri(location), scope: "openid email profile",
    code_challenge_method: "S256", code_challenge: challenge, state,
  }).toString();
  return url.toString();
}

export async function completeLogin(config, storage, fetchImpl, location, historyApi = history) {
  const params = new URLSearchParams(location.search);
  if (!params.has("code") && !params.has("error")) return false;
  const state = storage.getItem(STATE_KEY);
  const verifier = storage.getItem(VERIFIER_KEY);
  storage.removeItem(STATE_KEY);
  storage.removeItem(VERIFIER_KEY);
  if (params.has("error")) throw new Error("Đăng nhập bị hủy hoặc thất bại.");
  if (!state || params.get("state") !== state || !verifier) {
    throw new Error("Phiên đăng nhập không hợp lệ. Hãy đăng nhập lại.");
  }
  const response = await fetchImpl(`${config.cognitoDomain}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code", client_id: config.clientId,
      code: params.get("code"), redirect_uri: redirectUri(location), code_verifier: verifier,
    }),
  });
  if (!response.ok) throw new Error("Không thể hoàn tất đăng nhập. Hãy thử lại.");
  const body = await response.json();
  if (typeof body.id_token !== "string") throw new Error("Phản hồi đăng nhập không hợp lệ.");
  storage.setItem(TOKEN_KEY, body.id_token);
  historyApi.replaceState({}, "", redirectUri(location));
  return true;
}

export function idToken(storage) {
  const token = storage.getItem(TOKEN_KEY);
  if (!token) return null;
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    if (typeof payload.exp !== "number" || payload.exp * 1000 <= Date.now() + 30000) {
      storage.removeItem(TOKEN_KEY);
      return null;
    }
    return token;
  } catch {
    storage.removeItem(TOKEN_KEY);
    return null;
  }
}

export function mockLogin(storage) { storage.setItem(TOKEN_KEY, "mock"); }
export function isMockLoggedIn(storage) { return storage.getItem(TOKEN_KEY) === "mock"; }
export function clearSession(storage) { storage.removeItem(TOKEN_KEY); }

export function logoutUrl(config, storage, location) {
  storage.removeItem(TOKEN_KEY);
  if (config.mode === "mock") return null;
  const url = new URL("/logout", config.cognitoDomain);
  url.search = new URLSearchParams({
    client_id: config.clientId, logout_uri: redirectUri(location),
  }).toString();
  return url.toString();
}
