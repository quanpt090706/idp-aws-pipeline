# OCR local tạm thời khi chưa có quyền Amazon Textract

## OCR là gì?

OCR là viết tắt của **Optical Character Recognition**, nghĩa là nhận dạng chữ
từ hình ảnh. Ví dụ, máy tính nhìn vào ảnh hóa đơn và biến vùng ảnh chứa
`Invoice Number: US-001` thành văn bản để chương trình tiếp tục xử lý.

Amazon Textract cũng có OCR, nhưng mạnh hơn Tesseract ở phần hiểu cấu trúc:

| Công cụ               | Làm được gì?                                                                             |
| ----------------------- | --------------------------------------------------------------------------------------------- |
| Tesseract local         | Đọc chữ từ ảnh và trả về các dòng văn bản.                                        |
| Parser local của nhóm | Tìm số hóa đơn, ngày, tổng tiền và dòng hàng từ các dòng chữ đó.             |
| Amazon Textract         | Đọc chữ, đồng thời nhận diện biểu mẫu, bảng, cặp nhãn–giá trị và hóa đơn. |

Vì vậy Tesseract có thể thay tạm **bước đọc chữ** của Textract để nhóm phát
triển giao diện và parser. Nó không tương đương hoàn toàn với Textract; ảnh mờ,
bảng phức tạp hoặc bố cục lạ có thể cho kết quả thiếu và được gắn
`NEEDS_REVIEW`.

Trong dự án này, OCR không phải thư viện Python:

1. `tools/local_ocr/extractor.py` dùng `subprocess` để gọi chương trình
   `pdftotext`, `pdftoppm` hoặc `tesseract` đã cài trên máy.
2. Tesseract nhìn ảnh và trả về chữ thô cùng confidence.
3. `tools/local_ocr/invoice_text.py` dùng Python để tìm các trường hóa đơn từ
   phần chữ thô.
4. `tools/local_ocr/server.py` trả JSON cho frontend bằng API local.

Không cần cài `pytesseract`; đây chỉ là một thư viện Python bọc bên ngoài
Tesseract và bản hiện tại gọi trực tiếp chương trình Tesseract.

## Mục đích của chế độ tạm thời

Chế độ này giúp nhóm tải **hóa đơn tiếng Anh thật** lên website local và xem dữ
liệu được đọc từ chính file đó. Nó dùng `pdftotext` cho PDF có sẵn lớp chữ và
Tesseract cho JPG, PNG hoặc PDF scan.

Đây là phương án phát triển tạm thời, **không phải Amazon Textract** và không
được dùng làm bằng chứng hoàn thành các mục kiểm thử AWS ở Giai đoạn 4. Mã
Textract trong `lambdas/start-job/` và `lambdas/parse/handler.py` vẫn được giữ
nguyên. Hai nhánh xử lý cùng trả [output contract](OUTPUT_CONTRACT.md), nên khi
có tài khoản AWS, frontend không cần viết lại màn hình kết quả.

```text
Chế độ local: File thật → pdftotext/Tesseract → local parser → JSON chuẩn → Web
Chế độ AWS:   File thật → S3 → Textract → Textract parser → JSON chuẩn → Web
```

## Cài công cụ

### Ubuntu, Debian hoặc Windows đang dùng WSL Ubuntu

```bash
sudo apt update
sudo apt install poppler-utils tesseract-ocr tesseract-ocr-eng
```

Máy hiện tại đang mở dự án dưới đường dẫn `/home/khoa/...`, nên nhiều khả năng
đang dùng Linux hoặc WSL và áp dụng đúng phần này.

### Windows chưa có WSL

**Không bắt buộc phải có WSL.** Code có thể chạy native trên Windows nếu ba
lệnh `pdftotext.exe`, `pdftoppm.exe` và `tesseract.exe` đã được cài và có trong
biến môi trường `PATH`. Kiểm tra trong PowerShell:

```powershell
Get-Command pdftotext
Get-Command pdftoppm
Get-Command tesseract
```

Tuy nhiên Tesseract không cung cấp bộ cài Windows chính thức cho các bản mới;
trang dự án chỉ dẫn tới một số bộ cài bên thứ ba. Poppler native cũng cần tự
cài và thêm thư mục `bin` vào `PATH`. Do đó nhóm khuyến nghị WSL để mọi người
chạy cùng lệnh và tránh lỗi cấu hình khác nhau.

Nếu chọn WSL, mở PowerShell bằng quyền Administrator:

```powershell
wsl --install -d Ubuntu
```

Khởi động lại nếu Windows yêu cầu, mở ứng dụng Ubuntu, rồi chạy ba lệnh `apt`
ở phần trên. Hướng dẫn chính thức: [Install WSL](https://learn.microsoft.com/windows/wsl/install).

### macOS

Cài [Homebrew](https://brew.sh/) trước, sau đó:

```bash
brew install poppler tesseract
```

Homebrew Tesseract có sẵn dữ liệu tiếng Anh `eng`. Nếu sau này cần thêm ngôn
ngữ, cài thêm `tesseract-lang`.

### Kiểm tra sau khi cài

```bash
pdftotext -v
pdftoppm -v
tesseract --version
tesseract --list-langs
```

Danh sách ngôn ngữ phải có `eng`. Nếu chỉ dùng PDF có sẵn lớp chữ thì
`pdftotext` là đủ; ảnh và PDF scan bắt buộc có Tesseract.

## Giới hạn hiện tại

- Bản đầu hỗ trợ hóa đơn tiếng Anh (`INVOICE`).
- PDF có lớp chữ cho kết quả ổn định hơn ảnh scan.
- Parser local dùng quy tắc tìm nhãn nên bảng phức tạp có thể thiếu dòng hàng.
- Bảng điểm (`TRANSCRIPT`) chưa có parser OCR local và sẽ trả `FAILED` rõ ràng.
- Dữ liệu nằm trong `.local-ocr/`, chỉ phục vụ phát triển và không được commit.
- Chế độ local bỏ qua Cognito; tuyệt đối không public API này lên Internet.

## Chạy thử end-to-end trên local

Mở terminal thứ nhất tại thư mục gốc:

```bash
python3 -m tools.local_ocr.server
```

Mở terminal thứ hai:

```bash
cd frontend
TV1_LOCAL_API_URL=http://127.0.0.1:8000 npm run dev
```

Nếu chạy native Windows, dùng hai cửa sổ PowerShell:

```powershell
py -m tools.local_ocr.server
```

```powershell
cd frontend
$env:TV1_LOCAL_API_URL = "http://127.0.0.1:8000"
npm run dev
```

Mở `http://127.0.0.1:5173`, đăng nhập local, chọn `Hóa đơn`, tải file lên và
chờ trạng thái cuối. Góc trên phải hiện **OCR local**, không phải **Bản demo**.

Có thể thử trước với các PDF trong `tests/samples/invoices/` trên máy của TV3.

## Cách chuyển lại AWS sau này

Không đặt `TV1_LOCAL_API_URL`. Build frontend bằng ba output AWS như hướng dẫn
trong `frontend/README.md`: `TV1_API_URL`, `TV1_COGNITO_DOMAIN` và
`TV1_COGNITO_CLIENT_ID`. Khi đó frontend dùng document API/Cognito và pipeline
Textract thật; không cần sửa cấu trúc màn hình kết quả.
