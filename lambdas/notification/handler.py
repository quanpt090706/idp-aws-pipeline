"""Lambda gửi email thông báo kết quả xử lý qua Amazon SES."""
import html
import json
import os
import re
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

DOC_TYPE_MAP = {
    "INVOICE": "Hóa đơn (INVOICE)",
    "TRANSCRIPT": "Bảng điểm (TRANSCRIPT)",
}

USER_FRIENDLY_ERRORS = {
    "States.Timeout": "Quá trình xử lý tài liệu vượt quá thời gian tối đa cho phép (15 phút).",
    "INVALID_DOCUMENT_TYPE": "Loại tài liệu không được hỗ trợ (chỉ chấp nhận Hóa đơn hoặc Bảng điểm).",
    "UNEXPECTED_OCR_STATUS": "Kết quả nhận diện OCR không hợp lệ hoặc thiếu dữ liệu bắt buộc.",
    "TextractExecutionError": "Dịch vụ bóc tách tài liệu Amazon Textract gặp sự cố khi xử lý.",
    "States.TaskFailed": "Một tác vụ trong quy trình xử lý tài liệu gặp sự cố kỹ thuật.",
}

# Khởi tạo boto3 client ở module level để tái dùng HTTP connection (Keep-Alive) giữa các lần invoke
_AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
ses_client = boto3.client("ses", region_name=_AWS_REGION)


def sanitize_header_value(val: str, max_length: int = 60) -> str:
    """Loại bỏ ký tự xuống dòng, thẻ HTML và giới hạn độ dài để chống Header/Subject Injection."""
    cleaned = re.sub(r"<[^>]*>", "", str(val))
    cleaned = re.sub(r"[\r\n\t]+", " ", cleaned).strip()
    if len(cleaned) > max_length:
        return cleaned[:max_length] + "..."
    return cleaned or "Tài liệu"


def get_recipient_email(
    user_id: str,
    document_id: str,
    event_email: Optional[str] = None
) -> Optional[str]:
    """
    Xác định email người nhận theo thứ tự ưu tiên:
    1. DEMO_NOTIFICATION_EMAIL / DEFAULT_RECIPIENT_EMAIL (Sandbox thực hành)
    2. event_email (truyền trong event)
    3. Tra cứu user_email từ DynamoDB Documents table
    4. Trả về None nếu không tìm thấy (không gửi cho chính sender).
    """
    demo_email = os.environ.get("DEMO_NOTIFICATION_EMAIL") or os.environ.get("DEFAULT_RECIPIENT_EMAIL")
    if demo_email and demo_email.strip():
        return demo_email.strip()

    if event_email and str(event_email).strip():
        return str(event_email).strip()

    table_name = os.environ.get("DOCUMENTS_TABLE")
    if table_name and user_id and document_id:
        try:
            dynamodb = boto3.resource("dynamodb", region_name=_AWS_REGION)
            table = dynamodb.Table(table_name)
            resp = table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"DOC#{document_id}"})
            item = resp.get("Item")
            if item and item.get("user_email"):
                return str(item["user_email"]).strip()
        except Exception as e:
            print(f"[WARN] Không thể đọc email từ DynamoDB: {e}")

    return None


def get_friendly_error_message(error_info: Any) -> str:
    """Chuyển đổi lỗi kỹ thuật sang thông điệp người dùng thân thiện, giấu hoàn toàn lỗi nội bộ."""
    if not error_info:
        return "Quá trình xử lý tài liệu gặp lỗi không xác định."

    err_type = ""
    if isinstance(error_info, dict):
        err_type = str(error_info.get("error_type") or error_info.get("Error") or "")
    elif isinstance(error_info, str):
        err_type = error_info

    return USER_FRIENDLY_ERRORS.get(err_type, "Đã xảy ra sự cố kỹ thuật trong quá trình xử lý tài liệu.")


def render_email_content(event: Dict[str, Any]) -> Dict[str, str]:
    """Tạo Subject, Body HTML và Plain Text an toàn, hỗ trợ cả nested ocr_result và flat payload."""
    raw_doc_id = str(event.get("document_id") or "N/A")
    raw_doc_type = event.get("document_type")
    doc_type_display = DOC_TYPE_MAP.get(raw_doc_type, "Không xác định")

    # Tên file cho tiêu đề (cắt ngắn 60 ký tự, bỏ thẻ HTML) vs thân email (giữ nguyên độ dài, chỉ bỏ ký tự điều khiển)
    file_name_original = str(event.get("file_name") or "Tài liệu")
    subject_file_name = sanitize_header_value(file_name_original, max_length=60)
    body_file_name = re.sub(r"[\r\n\t]+", " ", file_name_original).strip()

    # Đọc linh hoạt từ nested ocr_result hoặc flat fields
    ocr = event.get("ocr_result") if isinstance(event.get("ocr_result"), dict) else {}
    status = ocr.get("status") or event.get("status") or "UNKNOWN"

    raw_conf = ocr.get("confidence") if "confidence" in ocr else event.get("confidence")
    confidence_str = f"{raw_conf}%" if raw_conf is not None and str(raw_conf) != "N/A" else "Không có"

    # Trích xuất summary: Hỗ trợ cả dict và chuỗi JSON (json.loads)
    raw_summary = ocr.get("extracted") or event.get("summary") or {}
    if isinstance(raw_summary, str):
        try:
            summary: Dict[str, Any] = json.loads(raw_summary)
        except Exception as e:
            print(f"[WARN] Không thể parse chuỗi JSON extracted: {e}")
            summary = {}
    elif isinstance(raw_summary, dict):
        summary = raw_summary
    else:
        print(f"[WARN] Dữ liệu extracted không đúng định dạng (kiểu {type(raw_summary)}), bỏ qua.")
        summary = {}

    warnings: List[str] = ocr.get("warnings") or event.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = [str(warnings)]

    error_info = event.get("error_info") or ocr.get("error_info") or {}

    # Xác định màu sắc & tiêu đề
    if status == "SUCCEEDED":
        badge_color = "#28a745"
        status_text = "Thành công (SUCCEEDED)"
        subject = f"[IDP] Xử lý thành công tài liệu: {subject_file_name}"
    elif status == "NEEDS_REVIEW":
        badge_color = "#fd7e14"
        status_text = "Cần kiểm tra lại (NEEDS_REVIEW)"
        subject = f"[IDP] Cảnh báo chất lượng tài liệu: {subject_file_name}"
    else:
        badge_color = "#dc3545"
        status_text = "Thất bại (FAILED)"
        subject = f"[IDP] Xử lý thất bại tài liệu: {subject_file_name}"

    extracted_rows_html = ""
    plain_extracted_lines = []

    if status in ("SUCCEEDED", "NEEDS_REVIEW") and summary:
        if raw_doc_type == "INVOICE":
            if "vendor" in summary:
                vendor_esc = html.escape(str(summary["vendor"]))
                extracted_rows_html += f"""
                <tr>
                    <td style="padding: 10px; border-bottom: 1px solid #e9ecef; font-weight: bold;">Đơn vị phát hành:</td>
                    <td style="padding: 10px; border-bottom: 1px solid #e9ecef;">{vendor_esc}</td>
                </tr>"""
                plain_extracted_lines.append(f"Đơn vị phát hành: {summary['vendor']}")
            if "total_amount" in summary:
                total_esc = html.escape(str(summary["total_amount"]))
                extracted_rows_html += f"""
                <tr>
                    <td style="padding: 10px; border-bottom: 1px solid #e9ecef; font-weight: bold;">Tổng tiền thanh toán:</td>
                    <td style="padding: 10px; border-bottom: 1px solid #e9ecef; font-weight: bold; color: #1a73e8;">{total_esc}</td>
                </tr>"""
                plain_extracted_lines.append(f"Tổng tiền thanh toán: {summary['total_amount']}")
        elif raw_doc_type == "TRANSCRIPT":
            if "student_name" in summary:
                name_esc = html.escape(str(summary["student_name"]))
                extracted_rows_html += f"""
                <tr>
                    <td style="padding: 10px; border-bottom: 1px solid #e9ecef; font-weight: bold;">Họ và tên:</td>
                    <td style="padding: 10px; border-bottom: 1px solid #e9ecef;">{name_esc}</td>
                </tr>"""
                plain_extracted_lines.append(f"Họ và tên: {summary['student_name']}")
            gpa = summary.get("average_score") or summary.get("gpa")
            if gpa is not None:
                gpa_esc = html.escape(str(gpa))
                extracted_rows_html += f"""
                <tr>
                    <td style="padding: 10px; border-bottom: 1px solid #e9ecef; font-weight: bold;">Điểm trung bình (GPA):</td>
                    <td style="padding: 10px; border-bottom: 1px solid #e9ecef; font-weight: bold; color: #1a73e8;">{gpa_esc}</td>
                </tr>"""
                plain_extracted_lines.append(f"Điểm trung bình (GPA): {gpa}")

        if not extracted_rows_html:
            raw_summary_esc = html.escape(json.dumps(summary, ensure_ascii=False))
            extracted_rows_html = f"""
            <tr>
                <td style="padding: 10px; border-bottom: 1px solid #e9ecef; font-weight: bold;">Dữ liệu bóc tách:</td>
                <td style="padding: 10px; border-bottom: 1px solid #e9ecef;"><code>{raw_summary_esc}</code></td>
            </tr>"""
            plain_extracted_lines.append(f"Dữ liệu bóc tách: {json.dumps(summary, ensure_ascii=False)}")

    doc_id_esc = html.escape(raw_doc_id)
    file_name_esc = html.escape(body_file_name)
    doc_type_esc = html.escape(doc_type_display)

    rows_html = f"""
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #e9ecef; font-weight: bold; width: 35%;">Mã tài liệu:</td>
            <td style="padding: 10px; border-bottom: 1px solid #e9ecef;"><code>{doc_id_esc}</code></td>
        </tr>
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #e9ecef; font-weight: bold;">Tên file:</td>
            <td style="padding: 10px; border-bottom: 1px solid #e9ecef;">{file_name_esc}</td>
        </tr>
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #e9ecef; font-weight: bold;">Loại tài liệu:</td>
            <td style="padding: 10px; border-bottom: 1px solid #e9ecef;">{doc_type_esc}</td>
        </tr>
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #e9ecef; font-weight: bold;">Trạng thái:</td>
            <td style="padding: 10px; border-bottom: 1px solid #e9ecef;">
                <span style="display: inline-block; padding: 4px 10px; border-radius: 4px; color: #fff; background-color: {badge_color}; font-weight: bold;">
                    {status_text}
                </span>
            </td>
        </tr>
    """

    if status in ("SUCCEEDED", "NEEDS_REVIEW"):
        rows_html += f"""
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #e9ecef; font-weight: bold;">Độ tin cậy OCR:</td>
            <td style="padding: 10px; border-bottom: 1px solid #e9ecef;">{confidence_str}</td>
        </tr>
        """
        rows_html += extracted_rows_html
        if warnings:
            warn_items = "".join([f"<li>{html.escape(str(w))}</li>" for w in warnings])
            rows_html += f"""
            <tr>
                <td style="padding: 10px; border-bottom: 1px solid #e9ecef; font-weight: bold; color: #fd7e14;">Cảnh báo:</td>
                <td style="padding: 10px; border-bottom: 1px solid #e9ecef; color: #fd7e14;"><ul>{warn_items}</ul></td>
            </tr>
            """
    else:
        friendly_err = get_friendly_error_message(error_info)
        rows_html += f"""
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #e9ecef; font-weight: bold; color: #dc3545;">Lý do thất bại:</td>
            <td style="padding: 10px; border-bottom: 1px solid #e9ecef; color: #dc3545;">{html.escape(friendly_err)}</td>
        </tr>
        """

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"><title>{html.escape(subject)}</title></head>
    <body style="font-family: Arial, Helvetica, sans-serif; background-color: #f8f9fa; margin: 0; padding: 20px; color: #212529;">
        <table align="center" border="0" cellpadding="0" cellspacing="0" width="600" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border: 1px solid #dee2e6;">
            <tr>
                <td style="background-color: #1a73e8; padding: 20px; text-align: center; color: #ffffff;">
                    <h2 style="margin: 0; font-size: 20px;">HỆ THỐNG XỬ LÝ HÓA ĐƠN & BẢNG ĐIỂM (IDP PIPELINE)</h2>
                </td>
            </tr>
            <tr>
                <td style="padding: 30px 25px;">
                    <p style="font-size: 15px; margin-top: 0;">Xin chào,</p>
                    <p style="font-size: 14px; color: #495057;">Tài liệu của bạn đã được xử lý tự động trên AWS. Dưới đây là thông tin chi tiết:</p>
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 20px 0; border: 1px solid #e9ecef; border-collapse: collapse; font-size: 14px;">
                        {rows_html}
                    </table>
                    <p style="font-size: 13px; color: #6c757d; margin-top: 25px; line-height: 1.5;">* Đây là email thông báo tự động từ hệ thống IDP Pipeline. Vui lòng không trả lời trực tiếp email này.</p>
                </td>
            </tr>
            <tr>
                <td style="background-color: #f1f3f5; padding: 15px; text-align: center; font-size: 12px; color: #868e96;">
                    Đồ án môn Điện toán đám mây — AWS Serverless IDP Pipeline
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    plain_text_lines = [
        "HỆ THỐNG XỬ LÝ HÓA ĐƠN & BẢNG ĐIỂM (IDP PIPELINE)",
        "--------------------------------------------------",
        f"Mã tài liệu: {raw_doc_id}",
        f"Tên file: {body_file_name}",
        f"Loại tài liệu: {doc_type_display}",
        f"Trạng thái: {status_text}",
    ]

    if status in ("SUCCEEDED", "NEEDS_REVIEW"):
        plain_text_lines.append(f"Độ tin cậy OCR: {confidence_str}")
        if plain_extracted_lines:
            plain_text_lines.extend(plain_extracted_lines)
        if warnings:
            plain_text_lines.append(f"Cảnh báo: {', '.join([str(w) for w in warnings])}")
    else:
        plain_text_lines.append(f"Lý do thất bại: {get_friendly_error_message(error_info)}")

    plain_text_lines.extend([
        "--------------------------------------------------",
        "Vui lòng kiểm tra trên giao diện web để xem kết quả chi tiết."
    ])

    return {"subject": subject, "html": html_body, "text": "\n".join(plain_text_lines)}


def lambda_handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    """
    Handler gửi email qua Amazon SES.
    Toàn bộ logic được bọc trong try/except để không bao giờ làm crash pipeline.
    """
    try:
        user_id = str(event.get("user_id") or "")
        document_id = str(event.get("document_id") or "")
        print(f"[INFO] Bắt đầu gửi email thông báo: doc_id={document_id}, user_id={user_id}")

        recipient = get_recipient_email(user_id, document_id, event.get("recipient_email"))
        if not recipient:
            print(f"[INFO] Không tìm thấy email người nhận cho doc_id={document_id}. Bỏ qua gửi email.")
            return {
                "status": "SKIPPED_NO_RECIPIENT",
                "message": "Không tìm thấy địa chỉ email người nhận",
                "document_id": document_id
            }

        sender = os.environ.get("SENDER_EMAIL", "noreply@idp-pipeline.aws")
        content = render_email_content(event)

        response = ses_client.send_email(
            Source=sender,
            Destination={"ToAddresses": [recipient]},
            Message={
                "Subject": {"Data": content["subject"], "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": content["html"], "Charset": "UTF-8"},
                    "Text": {"Data": content["text"], "Charset": "UTF-8"}
                }
            }
        )
        msg_id = response.get("MessageId", "mock-message-id")
        print(f"[INFO] Gửi email thành công tới {recipient}, MessageId: {msg_id}")
        return {
            "status": "SENT",
            "message_id": msg_id,
            "recipient": recipient
        }
    except ClientError as err:
        err_code = err.response["Error"]["Code"]
        err_msg = err.response["Error"]["Message"]
        print(f"[WARN] Lỗi khi gọi Amazon SES ({err_code}): {err_msg}. Nuốt lỗi bảo vệ pipeline.")
        return {
            "status": "FAILED_TO_SEND",
            "error_code": err_code,
            "error_message": err_msg
        }
    except Exception as err:
        print(f"[WARN] Ngoại lệ bất ngờ khi xử lý gửi thông báo: {err}. Nuốt lỗi bảo vệ pipeline.")
        return {
            "status": "ERROR",
            "error": str(err)
        }
