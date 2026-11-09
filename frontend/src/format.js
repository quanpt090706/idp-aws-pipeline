export const TERMINAL = new Set(["SUCCEEDED", "NEEDS_REVIEW", "FAILED", "REJECTED"]);

export const STATUS_LABELS = {
  UPLOAD_PENDING: "Chờ tải lên",
  QUEUED: "Đang xếp hàng",
  PROCESSING: "Đang xử lý",
  SUCCEEDED: "Hoàn thành",
  NEEDS_REVIEW: "Cần kiểm tra",
  FAILED: "Xử lý thất bại",
  REJECTED: "Tệp bị từ chối",
};

const REJECT_LABELS = {
  UNSUPPORTED_EXTENSION: "Định dạng tệp không được hỗ trợ.",
  FILE_EMPTY: "Tệp không có dữ liệu.",
  FILE_TOO_LARGE: "Tệp vượt quá 10 MiB.",
  CONTENT_MISMATCH: "Nội dung tệp không khớp định dạng đã chọn.",
  INVALID_DOCUMENT_TYPE: "Loại tài liệu không hợp lệ.",
};

const CONTENT_TYPES = {
  pdf: "application/pdf",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
};

export function validateFile(file) {
  if (!file) throw new Error("Hãy chọn một tệp.");
  if (!file.size) throw new Error("Tệp không có dữ liệu.");
  if (file.size > 10 * 1024 * 1024) throw new Error("Tệp vượt quá 10 MiB.");
  if (!file.name || file.name.length > 255 || /[\\/\u0000-\u001f\u007f]/u.test(file.name)) {
    throw new Error("Tên tệp không hợp lệ.");
  }
  const extension = file.name.split(".").pop()?.toLowerCase();
  const contentType = CONTENT_TYPES[extension];
  if (!contentType || (file.type && file.type !== contentType)) {
    throw new Error("Chỉ nhận PDF, JPG hoặc PNG đúng định dạng.");
  }
  return contentType;
}

export function documentMessage(doc) {
  if (doc.status === "REJECTED") return REJECT_LABELS[doc.reject_reason] || "Tệp không được chấp nhận.";
  if (doc.status === "FAILED") return "Hệ thống chưa xử lý được tài liệu. Hãy thử lại sau.";
  if (doc.status === "NEEDS_REVIEW") return "Kết quả cần được kiểm tra trước khi sử dụng.";
  return "";
}

export function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return new Intl.NumberFormat("vi-VN").format(value);
  return String(value);
}

export function displayValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export function warningText(warning) {
  if (typeof warning === "string") return warning;
  if (warning && typeof warning === "object") return warning.message || warning.code || "Cần kiểm tra kết quả.";
  return "Cần kiểm tra kết quả.";
}
