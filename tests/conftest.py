"""Cấu hình pytest dùng chung: thêm thư mục Lambda vào sys.path và đặt AWS credential giả."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lambdas" / "validate"))
sys.path.insert(0, str(ROOT / "lambdas" / "workflow-starter"))
sys.path.insert(0, str(ROOT / "lambdas" / "mock-worker"))
sys.path.insert(0, str(ROOT))

# Credential giả cho test; các test gọi SDK còn phải dùng mock_aws()
os.environ.update(
    AWS_ACCESS_KEY_ID="testing",
    AWS_SECRET_ACCESS_KEY="testing",
    AWS_SESSION_TOKEN="testing",
    AWS_DEFAULT_REGION="ap-southeast-1",
    AWS_EC2_METADATA_DISABLED="true",
)
