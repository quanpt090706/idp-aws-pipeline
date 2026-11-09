import assert from "node:assert/strict";
import { test } from "node:test";
import { webcrypto } from "node:crypto";
import { configFromEnv } from "../scripts/config.mjs";
import { ApiError, DocumentApi } from "../src/api.js";
import { completeLogin, idToken, loginUrl, logoutUrl } from "../src/auth.js";
import { documentMessage, validateFile, warningText } from "../src/format.js";
import { MockApi } from "../src/mock.js";

function storage() {
  const data = new Map();
  return {
    getItem: key => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, value),
    removeItem: key => data.delete(key),
  };
}

const config = {
  mode: "live", apiUrl: "https://api.example.test", clientId: "abc123",
  cognitoDomain: "https://login.example.test",
};

test("build configuration requires a complete HTTPS set for deployment", () => {
  assert.deepEqual(configFromEnv({}), { mode: "mock" });
  assert.throws(() => configFromEnv({ TV1_DEPLOY: "1" }), /requires real/);
  assert.throws(() => configFromEnv({ TV1_API_URL: "https://api.example.test" }), /all three/);
  assert.throws(() => configFromEnv({
    TV1_API_URL: "http://api.example.test", TV1_COGNITO_DOMAIN: config.cognitoDomain,
    TV1_COGNITO_CLIENT_ID: config.clientId,
  }), /HTTPS/);
});

test("browser rejects empty, oversized and misleading files before API call", () => {
  assert.equal(validateFile({ name: "invoice.PDF", size: 1024, type: "application/pdf" }), "application/pdf");
  assert.throws(() => validateFile({ name: "empty.pdf", size: 0 }), /không có dữ liệu/);
  assert.throws(() => validateFile({ name: "large.pdf", size: 10 * 1024 * 1024 + 1 }), /10 MiB/);
  assert.throws(() => validateFile({ name: "image.pdf", size: 2, type: "image/png" }), /đúng định dạng/);
  assert.throws(() => validateFile({ name: "../image.png", size: 2 }), /Tên tệp/);
  assert.equal(documentMessage({ status: "REJECTED", reject_reason: "CONTENT_MISMATCH" }),
    "Nội dung tệp không khớp định dạng đã chọn.");
  assert.equal(warningText("LOW_CONFIDENCE"), "LOW_CONFIDENCE");
  assert.equal(warningText({ code: "LOW_CONFIDENCE", message: "Kiểm tra tổng tiền" }), "Kiểm tra tổng tiền");
});

test("API sends JWT only to API and uses returned signed headers for S3", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith("/documents")) return { ok: true, json: async () => ({
      document: { document_id: "doc-1" }, upload_url: "https://bucket.s3.amazonaws.com/key",
      upload_headers: { "Content-Type": "application/pdf", "If-None-Match": "*" },
    }) };
    return { ok: true };
  };
  const api = new DocumentApi(config.apiUrl, () => "id-token", fetchImpl);
  const file = { name: "one.pdf" };
  const created = await api.create(file, "INVOICE", "application/pdf");
  await api.upload(created, file);
  assert.equal(calls[0].options.headers.Authorization, "Bearer id-token");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    file_name: "one.pdf", document_type: "INVOICE", content_type: "application/pdf",
  });
  assert.equal(calls[1].options.headers.Authorization, undefined);
  assert.equal(calls[1].options.headers["If-None-Match"], "*");
  assert.equal(calls[1].options.body, file);
});

test("API rejects expired session and surfaces server errors", async () => {
  const noToken = new DocumentApi(config.apiUrl, () => null, () => { throw new Error("should not fetch"); });
  await assert.rejects(noToken.list(), error => error instanceof ApiError && error.code === "SESSION_EXPIRED");
  const rejected = new DocumentApi(config.apiUrl, () => "token", async () => ({
    ok: false, status: 400, json: async () => ({ error: "INVALID_FILE_NAME" }),
  }));
  await assert.rejects(rejected.detail("doc-1"), error => error.code === "INVALID_FILE_NAME");
});

test("PKCE login checks state, stores ID token, and removes callback code", async () => {
  const session = storage();
  const location = { origin: "https://site.example.test", search: "" };
  const url = new URL(await loginUrl(config, session, webcrypto, location));
  assert.equal(url.searchParams.get("code_challenge_method"), "S256");
  assert.equal(url.searchParams.get("redirect_uri"), "https://site.example.test/");
  const state = url.searchParams.get("state");
  const future = Math.floor(Date.now() / 1000) + 3600;
  const token = `header.${Buffer.from(JSON.stringify({ exp: future })).toString("base64url")}.signature`;
  location.search = `?code=code-1&state=${state}`;
  let clearedUrl;
  const fetchImpl = async (endpoint, options) => {
    assert.equal(endpoint, "https://login.example.test/oauth2/token");
    assert.equal(options.body.get("grant_type"), "authorization_code");
    assert.ok(options.body.get("code_verifier"));
    return { ok: true, json: async () => ({ id_token: token }) };
  };
  assert.equal(await completeLogin(config, session, fetchImpl, location,
    { replaceState: (_state, _title, url) => { clearedUrl = url; } }), true);
  assert.equal(idToken(session), token);
  assert.equal(clearedUrl, "https://site.example.test/");
  assert.equal(new URL(logoutUrl(config, session, location)).pathname, "/logout");
  assert.equal(idToken(session), null);
});

test("PKCE callback rejects mismatched state", async () => {
  const session = storage();
  await loginUrl(config, session, webcrypto, { origin: "https://site.example.test" });
  await assert.rejects(completeLogin(config, session, () => { throw new Error("should not fetch"); },
    { origin: "https://site.example.test", search: "?code=abc&state=wrong" },
    { replaceState: () => {} }), /không hợp lệ/);
});

test("mock upload transitions to fixture result", async () => {
  const session = storage();
  const mock = new MockApi(session, async () => ({
    ok: true, json: async () => ({ document_type: "TRANSCRIPT", confidence: 94.8,
      warnings: [], extracted: { student_name: "Demo" } }),
  }));
  const created = await mock.create({ name: "grades.pdf" }, "TRANSCRIPT");
  await mock.upload(created);
  const pending = await mock.detail(created.document.document_id);
  assert.equal(pending.document.status, "PROCESSING");
  const docs = mock.read();
  docs[0].ready_at = 0;
  mock.save(docs);
  const result = await mock.detail(created.document.document_id);
  assert.equal(result.document.status, "SUCCEEDED");
  assert.equal(result.document.extracted.student_name, "Demo");
  assert.equal((await mock.list()).documents.length, 1);
});
