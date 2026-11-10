# TV1 frontend

Static, dependency-free browser application for the TV1 user journey:
login → upload → processing → invoice/transcript result. It can run in mock mode
from the repo fixtures or against the companion `feature/tv1-document-api` PR.

## Local mock demo

Requires Node.js 20 or newer.

```powershell
cd frontend
npm test
npm run build
npm run dev
```

Open <http://localhost:5173/> and choose **Đăng nhập**. Mock documents live in
the browser session and finish processing after a short delay. The result
fixtures are copied from `tests/fixtures/expected/` during build. A mock build
must not be deployed as the real application.

## Local OCR with a real English invoice

When AWS Academy has not granted Textract, the temporary local adapter can read
the actual uploaded invoice instead of returning a fixture. Follow
[`docs/tv3/OCR_LOCAL_TAM_THOI.md`](../docs/tv3/OCR_LOCAL_TAM_THOI.md). Start the local
API, then run the frontend with:

```bash
TV1_LOCAL_API_URL=http://127.0.0.1:8000 npm run dev
```

The badge must say `OCR local`. This mode bypasses Cognito and must never be
published as the production site or counted as an AWS Textract verification.

## Real AWS configuration

The companion API/IaC branch provides these Terraform outputs:

| Environment variable | Terraform output |
| --- | --- |
| `TV1_API_URL` | `tv1_api_url` |
| `TV1_COGNITO_DOMAIN` | `tv1_cognito_domain` |
| `TV1_COGNITO_CLIENT_ID` | `tv1_cognito_client_id` |

Set all three values for a live build. For deployment set `TV1_DEPLOY=1` so a
missing setting fails the build. These values are public endpoints/client ID,
not credentials. Never put AWS keys or user passwords in frontend files.

```powershell
$env:TV1_API_URL = 'https://your-api-id.execute-api.us-east-1.amazonaws.com'
$env:TV1_COGNITO_DOMAIN = 'https://your-domain.auth.us-east-1.amazoncognito.com'
$env:TV1_COGNITO_CLIENT_ID = 'your-public-client-id'
$env:TV1_DEPLOY = '1'
npm test
npm run build
```

The app uses Cognito authorization code with PKCE and keeps the ID token in
`sessionStorage`. It sends the token only to the document API. The browser PUTs
the file directly to the signed S3 URL with the API's returned headers, without
sending its token to S3. File size and extension are checked before API calls;
TV2 validates actual file content and size in the pipeline. Polling stops when
the document reaches `SUCCEEDED`, `NEEDS_REVIEW`, `FAILED` or `REJECTED`, or
after six minutes until the user refreshes.

## Deployment after reviewed Terraform apply

Use the `tv1_frontend_bucket_name` and `tv1_cloudfront_distribution_id` outputs
from the correct AWS account. Only deploy after the matching API resources have
been applied and verified. The S3 frontend bucket remains private; CloudFront
uses Origin Access Control.

```powershell
aws s3 sync dist/ s3://YOUR_FRONTEND_BUCKET/ --delete
aws cloudfront create-invalidation --distribution-id YOUR_DISTRIBUTION_ID --paths '/*'
```

`--delete` removes old build files in the frontend bucket, so inspect the bucket
name before running it. Verify Cognito login/logout, upload, both result types,
reject messages, expired URL and cross-user access in a real browser after
deployment. Local tests and the mock demo do not prove the AWS integration.
