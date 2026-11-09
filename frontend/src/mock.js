const KEY = "idp-tv1-mock-documents";

export class MockApi {
  constructor(storage, fetchImpl = globalThis.fetch.bind(globalThis)) {
    this.storage = storage;
    this.fetch = fetchImpl;
  }

  read() {
    try { return JSON.parse(this.storage.getItem(KEY) || "[]"); }
    catch { return []; }
  }

  save(documents) { this.storage.setItem(KEY, JSON.stringify(documents)); }

  async create(file, documentType) {
    const now = new Date().toISOString();
    const document = {
      document_id: crypto.randomUUID(), document_type: documentType,
      file_name: file.name, status: "UPLOAD_PENDING",
      created_at: now, updated_at: now,
    };
    this.save([document, ...this.read()]);
    return { document };
  }

  async upload(created) {
    const documents = this.read();
    const document = documents.find(doc => doc.document_id === created.document.document_id);
    document.status = "PROCESSING";
    document.ready_at = Date.now() + 2500;
    document.updated_at = new Date().toISOString();
    this.save(documents);
  }

  async list(cursor = null) {
    const documents = this.read();
    const offset = cursor ? Number(cursor) : 0;
    return {
      documents: documents.slice(offset, offset + 20),
      next_cursor: offset + 20 < documents.length ? String(offset + 20) : null,
    };
  }

  async detail(id) {
    const documents = this.read();
    const document = documents.find(doc => doc.document_id === id);
    if (!document) throw new Error("Không tìm thấy tài liệu.");
    if (document.status === "PROCESSING" && Date.now() >= document.ready_at) {
      const fixture = document.document_type === "INVOICE" ? "invoice" : "transcript";
      const response = await this.fetch(`/mock/${fixture}.json`);
      if (!response.ok) throw new Error("Không tải được dữ liệu mẫu.");
      const result = await response.json();
      Object.assign(document, result, {
        status: "SUCCEEDED", updated_at: new Date().toISOString(),
      });
      delete document.ready_at;
      this.save(documents);
    }
    return { document };
  }
}
