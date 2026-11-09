export class ApiError extends Error {
  constructor(code, status) {
    super(code);
    this.code = code;
    this.status = status;
  }
}

export class DocumentApi {
  constructor(baseUrl, getToken, fetchImpl = globalThis.fetch.bind(globalThis)) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.getToken = getToken;
    this.fetch = fetchImpl;
  }

  async request(method, path, body) {
    const token = this.getToken();
    if (!token) throw new ApiError("SESSION_EXPIRED", 401);
    const response = await this.fetch(`${this.baseUrl}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    let data;
    try { data = await response.json(); } catch { data = {}; }
    if (!response.ok) throw new ApiError(data.error || "API_ERROR", response.status);
    return data;
  }

  async create(file, documentType, contentType) {
    return this.request("POST", "/documents", {
      file_name: file.name, document_type: documentType, content_type: contentType,
    });
  }

  async upload(created, file) {
    const response = await this.fetch(created.upload_url, {
      method: "PUT", headers: created.upload_headers, body: file,
    });
    if (!response.ok) throw new ApiError("UPLOAD_FAILED", response.status);
  }

  async list(cursor = null) {
    const query = new URLSearchParams({ limit: "20" });
    if (cursor) query.set("cursor", cursor);
    return this.request("GET", `/documents?${query}`);
  }

  async detail(id) {
    return this.request("GET", `/documents/${encodeURIComponent(id)}`);
  }
}
