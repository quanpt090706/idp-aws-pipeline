"""Local HTTP API compatible with the frontend document API contract."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .extractor import LocalOcrError, extract_text
from .invoice_text import parse_invoice_text


MAX_BYTES = 10 * 1024 * 1024
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
DATA_DIR = Path(os.environ.get("LOCAL_OCR_DATA_DIR", ".local-ocr"))
DOCUMENTS_FILE = DATA_DIR / "documents.json"
UPLOAD_DIR = DATA_DIR / "uploads"
LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load() -> list[dict]:
    with LOCK:
        if not DOCUMENTS_FILE.exists():
            return []
        try:
            value = json.loads(DOCUMENTS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return value if isinstance(value, list) else []


def _save(documents: list[dict]) -> None:
    with LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temporary = DOCUMENTS_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(documents, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(DOCUMENTS_FILE)


def _public(document: dict) -> dict:
    return {key: value for key, value in document.items() if key not in {"upload_path", "content_type"}}


def _process(document_id: str, path: Path) -> None:
    documents = _load()
    document = next((item for item in documents if item["document_id"] == document_id), None)
    if document is None:
        return
    updates: dict = {}
    try:
        extracted_text = extract_text(path)
        if document["document_type"] != "INVOICE":
            raise LocalOcrError("OCR local tạm thời mới hỗ trợ hóa đơn tiếng Anh.")
        result = parse_invoice_text(extracted_text.text, extracted_text.confidence)
        updates.update(result)
        updates["status"] = "NEEDS_REVIEW" if result["warnings"] else "SUCCEEDED"
        updates["local_ocr_engine"] = extracted_text.engine
    except Exception as error:
        updates["status"] = "FAILED"
        updates["error_code"] = type(error).__name__
        updates["error_message"] = str(error)[:500]
    updates["updated_at"] = _now()
    # Reload under one lock so two simultaneous OCR jobs do not overwrite each
    # other's result in the development JSON store.
    with LOCK:
        latest = _load()
        current = next((item for item in latest if item["document_id"] == document_id), None)
        if current is not None:
            current.update(updates)
            _save(latest)


class Handler(BaseHTTPRequestHandler):
    server_version = "IdpLocalOcr/1.0"

    def _headers(self, status: int, content_type: str = "application/json") -> None:
        origin = self.headers.get("Origin", "")
        parsed_origin = urlparse(origin)
        is_local_origin = (
            parsed_origin.scheme == "http"
            and parsed_origin.hostname in {"127.0.0.1", "localhost"}
            and parsed_origin.port is not None
        )
        allowed_origin = origin if is_local_origin else "http://127.0.0.1:5173"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", allowed_origin)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, If-None-Match")
        self.end_headers()

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._headers(status)
        self.wfile.write(body)

    def _body(self, maximum: int = 8192) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > maximum:
            raise ValueError("INVALID_BODY")
        return self.rfile.read(length)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._headers(HTTPStatus.NO_CONTENT)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/documents":
            self._json(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"})
            return
        try:
            payload = json.loads(self._body().decode("utf-8"))
            if set(payload) != {"file_name", "document_type", "content_type"}:
                raise ValueError("INVALID_INPUT")
            name = payload["file_name"]
            if not isinstance(name, str) or not name or len(name) > 255 or re.search(r"[\\/\x00-\x1f\x7f]", name):
                raise ValueError("INVALID_FILE_NAME")
            suffix = Path(name).suffix.lower()
            if CONTENT_TYPES.get(suffix) != payload["content_type"]:
                raise ValueError("UNSUPPORTED_FILE_TYPE")
            if payload["document_type"] not in {"INVOICE", "TRANSCRIPT"}:
                raise ValueError("INVALID_DOCUMENT_TYPE")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error) or "INVALID_INPUT"})
            return

        document_id = str(uuid.uuid4())
        now = _now()
        document = {
            "document_id": document_id,
            "document_type": payload["document_type"],
            "file_name": name,
            "content_type": payload["content_type"],
            "status": "UPLOAD_PENDING",
            "created_at": now,
            "updated_at": now,
        }
        with LOCK:
            documents = _load()
            documents.insert(0, document)
            _save(documents)
        origin = f"http://{self.server.server_address[0]}:{self.server.server_address[1]}"
        self._json(HTTPStatus.CREATED, {
            "document": _public(document),
            "upload_url": f"{origin}/uploads/{document_id}",
            "upload_method": "PUT",
            "upload_headers": {"Content-Type": payload["content_type"], "If-None-Match": "*"},
        })

    def do_PUT(self) -> None:  # noqa: N802
        match = re.fullmatch(r"/uploads/([0-9a-f-]{36})", urlparse(self.path).path)
        if not match:
            self._json(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"})
            return
        document_id = match.group(1)
        documents = _load()
        document = next((item for item in documents if item["document_id"] == document_id), None)
        if document is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"})
            return
        if document["status"] != "UPLOAD_PENDING":
            self._json(HTTPStatus.PRECONDITION_FAILED, {"error": "UPLOAD_EXISTS"})
            return
        try:
            body = self._body(MAX_BYTES)
        except ValueError:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "FILE_TOO_LARGE"})
            return
        if not body:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "FILE_EMPTY"})
            return
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        path = UPLOAD_DIR / f"{document_id}{Path(document['file_name']).suffix.lower()}"
        path.write_bytes(body)
        with LOCK:
            documents = _load()
            document = next((item for item in documents if item["document_id"] == document_id), None)
            if document is None or document["status"] != "UPLOAD_PENDING":
                self._json(HTTPStatus.PRECONDITION_FAILED, {"error": "UPLOAD_EXISTS"})
                return
            document["status"] = "PROCESSING"
            document["updated_at"] = _now()
            _save(documents)
        threading.Thread(target=_process, args=(document_id, path), daemon=True).start()
        self._json(HTTPStatus.ACCEPTED, {"status": "PROCESSING"})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        documents = _load()
        if parsed.path == "/documents":
            try:
                limit = min(max(int(parse_qs(parsed.query).get("limit", ["20"])[0]), 1), 100)
                offset = max(int(parse_qs(parsed.query).get("cursor", ["0"])[0]), 0)
            except ValueError:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "INVALID_CURSOR"})
                return
            page = documents[offset:offset + limit]
            next_cursor = str(offset + limit) if offset + limit < len(documents) else None
            self._json(HTTPStatus.OK, {"documents": [_public(item) for item in page], "next_cursor": next_cursor})
            return
        match = re.fullmatch(r"/documents/([0-9a-f-]{36})", parsed.path)
        if match:
            document = next((item for item in documents if item["document_id"] == match.group(1)), None)
            if document is not None:
                self._json(HTTPStatus.OK, {"document": _public(document)})
                return
        self._json(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"})

    def log_message(self, format: str, *args: object) -> None:
        print(f"[local-ocr] {self.address_string()} {format % args}")


def main() -> None:
    host = os.environ.get("LOCAL_OCR_HOST", "127.0.0.1")
    port = int(os.environ.get("LOCAL_OCR_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Local OCR API: http://{host}:{port}")
    print("Dữ liệu local nằm trong .local-ocr/ và không được commit.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
