terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Ghi chú: Khi làm nhóm chung, có thể cấu hình S3 remote backend ở đây.
  # Hiện tại làm local nên Terraform sẽ tự tạo file terraform.tfstate cục bộ.
}

provider "aws" {
  region = var.aws_region

  # Tự động gắn tag cho TẤT CẢ các tài nguyên AWS do Terraform tạo ra:
  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
