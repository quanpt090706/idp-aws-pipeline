# TV1: private frontend, Cognito login, authenticated document API and direct S3 upload.
resource "aws_s3_bucket" "frontend" {
  bucket = "${local.name_prefix}-frontend-${random_string.bucket_suffix.result}"
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${local.name_prefix}-frontend"
  description                       = "Private S3 frontend origin"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "frontend-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  default_cache_behavior {
    target_origin_id       = "frontend-s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }
    min_ttl     = 0
    default_ttl = 300
    max_ttl     = 3600
  }

  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }
  viewer_certificate { cloudfront_default_certificate = true }
}

data "aws_iam_policy_document" "frontend_read" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.frontend.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.frontend.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket     = aws_s3_bucket.frontend.id
  policy     = data.aws_iam_policy_document.frontend_read.json
  depends_on = [aws_s3_bucket_public_access_block.frontend]
}

locals {
  frontend_origin = "https://${aws_cloudfront_distribution.frontend.domain_name}"
  tv1_origins     = [local.frontend_origin, "http://localhost:5173"]
}

resource "aws_s3_bucket_cors_configuration" "upload" {
  bucket = aws_s3_bucket.upload.id
  cors_rule {
    allowed_methods = ["PUT"]
    allowed_origins = local.tv1_origins
    allowed_headers = ["Content-Type", "If-None-Match"]
    expose_headers  = ["ETag"]
    max_age_seconds = 300
  }
}

resource "aws_cognito_user_pool" "frontend" {
  name                     = "${local.name_prefix}-users"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }
}

resource "aws_cognito_user_pool_domain" "frontend" {
  domain       = "${local.name_prefix}-${random_string.bucket_suffix.result}"
  user_pool_id = aws_cognito_user_pool.frontend.id
}

resource "aws_cognito_user_pool_client" "frontend" {
  name                                 = "${local.name_prefix}-web"
  user_pool_id                         = aws_cognito_user_pool.frontend.id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = ["${local.frontend_origin}/", "http://localhost:5173/"]
  logout_urls                          = ["${local.frontend_origin}/", "http://localhost:5173/"]
  prevent_user_existence_errors        = "ENABLED"
}

data "archive_file" "document_api_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/document-api"
  output_path = "${path.module}/build/document_api.zip"
}

resource "aws_iam_role" "document_api" {
  count = var.use_lab_role ? 0 : 1
  name  = "${local.name_prefix}-document-api"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "document_api_logs" {
  count      = var.use_lab_role ? 0 : 1
  role       = aws_iam_role.document_api[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "document_api" {
  count = var.use_lab_role ? 0 : 1
  name  = "${local.name_prefix}-document-api-data"
  role  = aws_iam_role.document_api[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"]
        Resource = aws_dynamodb_table.documents.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.upload.arn}/uploads/*"
      }
    ]
  })
}

resource "aws_lambda_function" "document_api" {
  function_name    = "${local.name_prefix}-document-api"
  filename         = data.archive_file.document_api_zip.output_path
  source_code_hash = data.archive_file.document_api_zip.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  role             = var.use_lab_role ? local.lambda_role_arn : aws_iam_role.document_api[0].arn
  timeout          = 15
  environment {
    variables = {
      DOCUMENTS_TABLE = aws_dynamodb_table.documents.name
      UPLOAD_BUCKET   = aws_s3_bucket.upload.id
    }
  }
}

resource "aws_apigatewayv2_api" "document_api" {
  name          = "${local.name_prefix}-document-api"
  protocol_type = "HTTP"
  cors_configuration {
    allow_origins = local.tv1_origins
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 300
  }
}

resource "aws_apigatewayv2_authorizer" "document_api" {
  api_id           = aws_apigatewayv2_api.document_api.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "cognito"
  jwt_configuration {
    audience = [aws_cognito_user_pool_client.frontend.id]
    issuer   = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.frontend.id}"
  }
}

resource "aws_apigatewayv2_integration" "document_api" {
  api_id                 = aws_apigatewayv2_api.document_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.document_api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "document_api" {
  for_each           = toset(["POST /documents", "GET /documents", "GET /documents/{document_id}"])
  api_id             = aws_apigatewayv2_api.document_api.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.document_api.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.document_api.id
}

resource "aws_apigatewayv2_stage" "document_api" {
  api_id      = aws_apigatewayv2_api.document_api.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "document_api_gateway" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.document_api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.document_api.execution_arn}/*/*"
}

output "tv1_frontend_url" { value = local.frontend_origin }
output "tv1_frontend_bucket_name" { value = aws_s3_bucket.frontend.id }
output "tv1_cloudfront_distribution_id" { value = aws_cloudfront_distribution.frontend.id }
output "tv1_api_url" { value = aws_apigatewayv2_api.document_api.api_endpoint }
output "tv1_cognito_domain" {
  value = "https://${aws_cognito_user_pool_domain.frontend.domain}.auth.${var.aws_region}.amazoncognito.com"
}
output "tv1_cognito_client_id" { value = aws_cognito_user_pool_client.frontend.id }
