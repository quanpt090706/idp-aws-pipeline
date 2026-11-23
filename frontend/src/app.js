import { ApiError, DocumentApi } from "./api.js";
import { clearSession, completeLogin, idToken, isMockLoggedIn, loginUrl, logoutUrl, mockLogin } from "./auth.js";
import { displayValue, documentMessage, formatNumber, STATUS_LABELS, TERMINAL, validateFile, warningText } from "./format.js";
import { MockApi } from "./mock.js";

const byId = id => document.getElementById(id);
const storage = sessionStorage;
let config;
let api;
let selectedId = null;
let nextCursor = null;
let pollTimer = null;
let pollGeneration = 0;

function showNotice(message, isError = false) {
  const node = byId("notice");
  node.textContent = message;
  node.classList.toggle("error", isError);
  node.hidden = !message;
}

function friendlyError(error) {
  if (!(error instanceof ApiError)) return error?.message || "Đã có lỗi xảy ra. Hãy thử lại.";
  const messages = {
    SESSION_EXPIRED: "Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.",
    UNAUTHORIZED: "Phiên đăng nhập không hợp lệ. Hãy đăng nhập lại.",
    INVALID_FILE_NAME: "Tên tệp không hợp lệ.",
    UNSUPPORTED_FILE_TYPE: "Tệp không đúng định dạng PDF, JPG hoặc PNG.",
    INVALID_DOCUMENT_TYPE: "Loại tài liệu không hợp lệ.",
    INVALID_INPUT: "Thông tin tài liệu không hợp lệ.",
    UPLOAD_FAILED: error.status === 412 ? "Tệp đã tồn tại. Hãy tải lên lại để tạo tài liệu mới." : "Tải tệp lên thất bại. Hãy thử lại.",
  };
  return messages[error.code] || "Không thể hoàn thành yêu cầu. Hãy thử lại.";
}

function handleError(error) {
  showNotice(friendlyError(error), true);
  if (error instanceof ApiError && error.status === 401) {
    clearSession(storage);
    stopPolling();
    showWorkspace(false);
  }
}

function showWorkspace(loggedIn) {
  byId("login-panel").hidden = loggedIn;
  byId("workspace").hidden = !loggedIn;
  byId("logout-button").hidden = !loggedIn;
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function statusPill(status) {
  const pill = node("span", `status-pill ${String(status || "").toLowerCase()}`, STATUS_LABELS[status] || status || "Không rõ");
  return pill;
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "—" : new Intl.DateTimeFormat("vi-VN", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function renderList(documents, append = false) {
  const list = byId("documents-list");
  if (!append) list.replaceChildren();
  for (const doc of documents) {
    const item = node("li");
    const button = node("button", "document-item");
    button.type = "button";
    button.addEventListener("click", () => selectDocument(doc.document_id));
    button.append(node("span", "document-icon", doc.document_type === "INVOICE" ? "▤" : "▦"));
    const description = node("span", "document-text");
    description.append(node("span", "document-name", doc.file_name || "Tài liệu"));
    description.append(node("span", "document-meta", `${doc.document_type === "INVOICE" ? "Hóa đơn" : "Bảng điểm"} · ${formatDate(doc.created_at)}`));
    button.append(description, statusPill(doc.status));
    item.append(button);
    list.append(item);
  }
  byId("documents-empty").hidden = list.children.length > 0;
}

async function loadDocuments(append = false) {
  const page = await api.list(append ? nextCursor : null);
  renderList(page.documents, append);
  nextCursor = page.next_cursor;
  byId("more-button").hidden = !nextCursor;
}

function field(label, value) {
  const box = node("div", "field");
  box.append(node("span", "field-label", label), node("span", "field-value", displayValue(value)));
  return box;
}

function table(headers, rows) {
  const wrapper = node("div", "table-scroll");
  const tableNode = node("table");
  const thead = node("thead");
  const headRow = node("tr");
  for (const header of headers) headRow.append(node("th", "", header));
  thead.append(headRow);
  const tbody = node("tbody");
  for (const row of rows) {
    const tr = node("tr");
    for (const value of row) tr.append(node("td", "", displayValue(value)));
    tbody.append(tr);
  }
  tableNode.append(thead, tbody);
  wrapper.append(tableNode);
  return wrapper;
}

function resultFields(doc, container) {
  const data = doc.extracted || {};
  const grid = node("div", "field-grid");
  if (doc.document_type === "INVOICE") {
    grid.append(
      field("Đơn vị bán", data.vendor_name ?? data.vendor),
      field("Số hóa đơn", data.invoice_number ?? data.invoice_no),
      field("Ngày hóa đơn", data.invoice_date),
      field("Tạm tính", formatNumber(data.subtotal)),
      field("Thuế", formatNumber(data.tax_amount)),
      field("Tổng tiền", `${formatNumber(data.total_amount)} ${data.currency || ""}`.trim()),
    );
    container.append(grid);
    if (Array.isArray(data.items) && data.items.length) {
      container.append(node("h3", "", "Sản phẩm / dịch vụ"));
      container.append(table(["Mô tả", "Số lượng", "Đơn giá", "Thành tiền"], data.items.map(item => [
        item.description, formatNumber(item.quantity ?? item.qty), formatNumber(item.unit_price), formatNumber(item.amount),
      ])));
    }
  } else {
    grid.append(
      field("Mã sinh viên", data.student_id), field("Họ tên", data.student_name),
      field("Trường", data.school_name), field("Năm học", data.academic_year),
      field("GPA", formatNumber(data.gpa)),
    );
    container.append(grid);
    if (Array.isArray(data.subjects) && data.subjects.length) {
      container.append(node("h3", "", "Kết quả môn học"));
      container.append(table(["Mã", "Môn học", "Tín chỉ", "Điểm", "Điểm chữ"], data.subjects.map(subject => [
        subject.code, subject.name, formatNumber(subject.credits), formatNumber(subject.score), subject.letter_grade,
      ])));
    }
  }
  if (typeof doc.confidence === "number") container.append(node("p", "result-message", `Độ tin cậy tổng thể: ${formatNumber(doc.confidence)}%`));
  if (Array.isArray(doc.warnings) && doc.warnings.length) {
    container.append(node("h3", "", "Cần chú ý"));
    const warnings = node("ul", "warning-list");
    for (const warning of doc.warnings) warnings.append(node("li", "", warningText(warning)));
    container.append(warnings);
  }
}

function renderDetail(doc) {
  byId("result-empty").hidden = true;
  const content = byId("result-content");
  content.hidden = false;
  content.replaceChildren();
  const pill = byId("result-status");
  pill.hidden = false;
  pill.className = `status-pill ${String(doc.status || "").toLowerCase()}`;
  pill.textContent = STATUS_LABELS[doc.status] || doc.status;
  const summary = node("div", "result-summary");
  summary.append(node("strong", "", doc.file_name || "Tài liệu"), node("small", "", formatDate(doc.updated_at)));
  content.append(summary);
  const message = documentMessage(doc);
  if (message) content.append(node("p", "result-message", message));
  if (!TERMINAL.has(doc.status)) content.append(node("p", "result-message", "Hệ thống đang xử lý. Trạng thái sẽ tự cập nhật."));
  if (["SUCCEEDED", "NEEDS_REVIEW"].includes(doc.status)) resultFields(doc, content);
}

function stopPolling() {
  pollGeneration += 1;
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = null;
}

async function selectDocument(id) {
  stopPolling();
  selectedId = id;
  const generation = pollGeneration;
  let attempts = 0;
  async function refreshDetail() {
    if (generation !== pollGeneration) return;
    try {
      const { document: doc } = await api.detail(id);
      if (generation !== pollGeneration) return;
      renderDetail(doc);
      if (TERMINAL.has(doc.status)) {
        await loadDocuments();
        return;
      }
      if (++attempts >= 120) {
        showNotice("Đã tạm dừng tự cập nhật. Chọn tài liệu hoặc bấm Làm mới để kiểm tra tiếp.");
        return;
      }
      pollTimer = setTimeout(refreshDetail, 3000);
    } catch (error) { handleError(error); }
  }
  await refreshDetail();
}

async function init() {
  try {
    const response = await fetch("/config.json", { cache: "no-store" });
    if (!response.ok) throw new Error("Không tải được cấu hình ứng dụng.");
    config = await response.json();
    byId("mode-badge").textContent = config.mode === "mock" ? "Bản demo" : "Kết nối AWS";
    byId("login-explanation").textContent = config.mode === "mock"
      ? "Đăng nhập demo để thử giao diện với dữ liệu mẫu."
      : "Đăng nhập an toàn bằng tài khoản Cognito của bạn.";
    if (config.mode === "live") await completeLogin(config, storage, fetch.bind(window), location);
    const loggedIn = config.mode === "mock" ? isMockLoggedIn(storage) : Boolean(idToken(storage));
    api = config.mode === "mock" ? new MockApi(storage) : new DocumentApi(config.apiUrl, () => idToken(storage));
    showWorkspace(loggedIn);
    if (loggedIn) await loadDocuments();
  } catch (error) { handleError(error); }
}

byId("login-button").addEventListener("click", async () => {
  try {
    showNotice("");
    if (config.mode === "mock") {
      mockLogin(storage);
      showWorkspace(true);
      await loadDocuments();
    } else {
      location.assign(await loginUrl(config, storage, crypto, location));
    }
  } catch (error) { handleError(error); }
});

byId("logout-button").addEventListener("click", () => {
  stopPolling();
  const url = logoutUrl(config, storage, location);
  if (url) location.assign(url);
  else { showWorkspace(false); showNotice(""); }
});

byId("upload-form").addEventListener("submit", async event => {
  event.preventDefault();
  const button = byId("upload-button");
  button.disabled = true;
  try {
    showNotice("");
    const file = byId("document-file").files[0];
    const contentType = validateFile(file);
    const created = await api.create(file, byId("document-type").value, contentType);
    await api.upload(created, file);
    byId("upload-form").reset();
    showNotice("Đã tải tệp lên. Hệ thống đang xử lý tài liệu.");
    await loadDocuments();
    await selectDocument(created.document.document_id);
  } catch (error) { handleError(error); }
  finally { button.disabled = false; }
});

byId("refresh-button").addEventListener("click", async () => {
  try {
    await loadDocuments();
    if (selectedId) await selectDocument(selectedId);
  } catch (error) { handleError(error); }
});
byId("more-button").addEventListener("click", async () => {
  try { await loadDocuments(true); } catch (error) { handleError(error); }
});

await init();
