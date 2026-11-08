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

  # Lưu ý: Các chỉ mục phụ (GSI) như GSI-status và GSI-type sẽ được TV4 và TV5
  # bổ sung khi TV4 chốt đầy đủ các mẫu truy vấn (query patterns).
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
    attribute_name = "ttl_expiry"
    enabled        = true
  }
}
