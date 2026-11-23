# TV1 document API contract

The `feature/tv1-document-api` branch adds an API Gateway HTTP API, a Cognito
user pool and public OAuth client, a Python Lambda, and private S3 + CloudFront
frontend hosting. Terraform resources are in `infra/tv1.tf`. No AWS resources
are created merely by checking out this branch.

## Authentication

The browser uses Cognito authorization code with PKCE. Send the **ID token** in
`Authorization: Bearer <token>` to every document endpoint. API Gateway checks
issuer, audience, signature and expiry; the Lambda uses the verified `sub` claim
as `user_id`. The Lambda returns 401 if called without that claim. The API has
no public document route.

## Create document and obtain upload URL

`POST /documents`

```json
{"file_name":"hoa-don.pdf","document_type":"INVOICE","content_type":"application/pdf"}
```

`document_type` is `INVOICE` or `TRANSCRIPT`. Extensions PDF, JPG, JPEG and PNG
are accepted with matching `Content-Type` (`application/pdf`, `image/jpeg`,
`image/png`). A file name is at most 255 characters and cannot contain a slash,
backslash or control character. Each call creates a new UUID document ID and a
conditional DynamoDB record with `status=UPLOAD_PENDING`, `PK=USER#<sub>`,
`SK=DOC#<document_id>`, and key
`uploads/<sub>/<document_id>/<file_name>`. The record is written before the URL
is returned. TV2 validates actual content and the 10 MiB maximum after upload.
The browser should check file size (1 to 10 MiB) before this request.

Response `201`:

```json
{
  "document": {"document_id":"...","document_type":"INVOICE","file_name":"hoa-don.pdf","status":"UPLOAD_PENDING","created_at":"...","updated_at":"..."},
  "upload_url":"https://...",
  "upload_method":"PUT",
  "upload_headers":{"Content-Type":"application/pdf","If-None-Match":"*"},
  "expires_in":900
}
```

Send the exact returned headers with the `PUT` body directly to S3. The signed
`If-None-Match: *` prevents replacing an existing object at the key. Do not log
or persist `upload_url`; it is a short-lived credential. If the PUT fails, the
client may request a new document/URL. Pending records from abandoned uploads
remain until a separately agreed cleanup policy is implemented.

## Read documents

- `GET /documents?limit=20&cursor=...` returns `{documents:[],next_cursor:null}`.
  Limit is 1–100. The opaque cursor is scoped to the authenticated user.
- `GET /documents/{document_id}` returns `{document:{...}}` or 404, including
  for another user's document.

Both operations query `PK=USER#<sub>`; there is no table scan or client-supplied
`user_id`. List rows contain `document_id`, `document_type`, `file_name`,
`status`, `created_at`, `updated_at` and optional `reject_reason`. Detail also
contains `confidence`, `warnings` and `extracted` when present. TV4 currently
stores `warnings` and `extracted` as JSON strings; this API decodes them into an
array and object. The API does not expose S3 keys, raw Textract data, or
`reject_detail`. Terminal statuses are `SUCCEEDED`, `NEEDS_REVIEW`, `FAILED`,
`REJECTED`. The UI maps TV2's `reject_reason` to a friendly message.

## Integration and deployment

1. Review the TV2 key/record contract in `docs/tv2/CONTRACT.md` and agree with
   TV4 on the final detail response shape. Parser fixtures use `vendor_name`,
   while `docs/data-model.md` has an older `vendor` example.
2. Create the ignored `infra/build/` directory for Lambda ZIP artifacts, then
   run `terraform -chdir=infra init`, `terraform -chdir=infra validate`, and
   inspect `terraform -chdir=infra plan` with the correct AWS account and lab
   role configuration. Do not commit `terraform.tfvars` or state files.
3. Apply the reviewed plan in the intended account. Terraform outputs provide
   the API URL, Cognito domain/client ID, frontend bucket and CloudFront URL.
4. Build the frontend with these outputs, sync `frontend/dist/` to the private
   frontend bucket and invalidate CloudFront. See `frontend/README.md` in the
   frontend PR.
5. Verify login, upload, TV2 validation, TV4 status updates and ownership with
   real AWS resources. Local Moto tests do not establish deployed behavior.

The standalone Lambda role has only DynamoDB Put/Get/Query, S3 PutObject on
`uploads/*`, and basic logging when `use_lab_role=false`. In an AWS Academy lab,
`use_lab_role=true` uses the supplied LabRole ARN; its permissions must be
checked in that account. S3 Upload CORS allows PUT from the CloudFront origin
and localhost:5173, and the API allows GET/POST from those origins.
