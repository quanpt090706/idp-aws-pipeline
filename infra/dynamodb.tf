################################################################################
# DATA LAYER (DYNAMODB TABLES)
#
# Quản lý 2 bảng DynamoDB:
# 1. documents: Bảng chính lưu trữ trạng thái tài liệu và dữ liệu đã bóc tách
# 2. job-callbacks: Bảng lưu thông tin callback token khi gọi Textract Async
################################################################################

# 1. Bảng lưu trữ thông tin tài liệu chính
resource "aws_dynamodb_table" "documents" {
  name         = "${local.name_prefix}-documents"
  billing_mode = "PAY_PER_REQUEST" # On-Demand để tự động co giãn và tiết kiệm chi phí

  hash_key  = "PK"
  range_key = "SK"

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

  # GSI-status: lọc danh sách tài liệu theo trạng thái (TV1/TV4).
  global_secondary_index {
    name            = "GSI-status"
    hash_key        = "status"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  # GSI-type: lọc danh sách tài liệu theo loại INVOICE/TRANSCRIPT.
  global_secondary_index {
    name            = "GSI-type"
    hash_key        = "document_type"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  # PITR: khôi phục bảng về thời điểm trước khi bị ghi/xóa nhầm.
  point_in_time_recovery {
    enabled = true
  }
}

# 2. Bảng quản lý Job Callbacks cho Step Functions và Textract Async
resource "aws_dynamodb_table" "job_callbacks" {
  name         = "${local.name_prefix}-job-callbacks"
  billing_mode = "PAY_PER_REQUEST"

  hash_key = "job_id"

  attribute {
    name = "job_id"
    type = "S"
  }

  # Tính năng TTL tự động xóa bản ghi callback sau khi hết hạn để giữ bảng sạch
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}
