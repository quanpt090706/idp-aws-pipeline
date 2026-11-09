export function configFromEnv(env) {
  const apiUrl = env.TV1_API_URL?.trim() || "";
  const cognitoDomain = env.TV1_COGNITO_DOMAIN?.trim() || "";
  const clientId = env.TV1_COGNITO_CLIENT_ID?.trim() || "";
  const supplied = [apiUrl, cognitoDomain, clientId].filter(Boolean).length;
  if (supplied !== 0 && supplied !== 3) {
    throw new Error("Set all three TV1_API_URL, TV1_COGNITO_DOMAIN and TV1_COGNITO_CLIENT_ID variables.");
  }
  if (env.TV1_DEPLOY === "1" && supplied !== 3) {
    throw new Error("A deployment build requires real API and Cognito configuration.");
  }
  if (!supplied) return { mode: "mock" };
  const api = new URL(apiUrl);
  const cognito = new URL(cognitoDomain);
  if (api.protocol !== "https:" || cognito.protocol !== "https:") {
    throw new Error("Production API and Cognito URLs must use HTTPS.");
  }
  if (!/^[A-Za-z0-9]+$/.test(clientId)) {
    throw new Error("Invalid Cognito client ID.");
  }
  return {
    mode: "live",
    apiUrl: api.origin,
    cognitoDomain: cognito.origin,
    clientId,
  };
}
