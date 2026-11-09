# Bảng chính lưu trữ thông tin tài liệu và kết quả bóc tách (Single-table design)
resource "aws_dynamodb_table" "documents" {
  count        = var.create_dynamodb_tables ? 1 : 0
  name         = "${var.name_prefix}-documents"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  attribute {
    name = "document_type"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "GSI-status"
    hash_key        = "status"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "GSI-type"
    hash_key        = "document_type"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = var.tags
}

# Bảng phụ lưu ánh xạ Textract job_id với Step Functions TaskToken
resource "aws_dynamodb_table" "job_callbacks" {
  count        = var.create_dynamodb_tables ? 1 : 0
  name         = "${var.name_prefix}-job-callbacks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "job_id"

  attribute {
    name = "job_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = var.tags
}
