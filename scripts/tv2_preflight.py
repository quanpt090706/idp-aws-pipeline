"""Read-only AWS Academy checks. Never print or save AWS credentials."""
import argparse
import json
from pathlib import Path
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError

REQUIRED = (
    "region", "expected_account_id", "upload_bucket", "documents_table",
    "processing_queue_url", "processing_dlq_url", "validate_failures_queue_url",
    "state_machine_arn", "validate_function_name", "starter_function_name",
)
DEMO_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


def load_config(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if "tv2_config" in data:  # also accept terraform output -json
        data = data["tv2_config"]["value"]
    missing = [key for key in REQUIRED if not isinstance(data.get(key), str) or not data[key].strip()]
    if missing:
        raise ValueError("Missing non-secret environment details: " + ", ".join(missing))
    if not (len(data["expected_account_id"]) == 12 and data["expected_account_id"].isdigit()):
        raise ValueError("expected_account_id must contain 12 digits")
    return data


def checked_session(config, profile):
    session = boto3.Session(profile_name=profile, region_name=config["region"])
    account = session.client("sts").get_caller_identity()["Account"]
    if account != config["expected_account_id"]:
        raise ValueError("AWS account does not match expected_account_id; stopped before resource access")
    return session


def check_environment(config, session):
    """Read service configuration; no create, update, invoke or queue polling."""
    results = []

    def check(name, passed):
        results.append({"check": name, "passed": bool(passed)})

    region = config["region"]
    s3 = session.client("s3")
    location = s3.get_bucket_location(Bucket=config["upload_bucket"]).get("LocationConstraint") or "us-east-1"
    location = "eu-west-1" if location == "EU" else location
    check("upload_bucket_region", location == region)
    ddb = session.client("dynamodb").describe_table(TableName=config["documents_table"])["Table"]
    check("documents_keys", {key["KeyType"]: key["AttributeName"] for key in ddb["KeySchema"]}
          == {"HASH": "PK", "RANGE": "SK"})
    key_types = {attr["AttributeName"]: attr["AttributeType"] for attr in ddb["AttributeDefinitions"]}
    check("documents_key_types", all(key_types.get(key) == "S" for key in ("PK", "SK")))
    machine = session.client("stepfunctions").describe_state_machine(stateMachineArn=config["state_machine_arn"])
    check("standard_workflow", machine["type"] == "STANDARD")
    arn = config["state_machine_arn"].split(":")
    check("workflow_account_region", arn[3] == region and arn[4] == config["expected_account_id"])
    sqs = session.client("sqs")
    queues = {}
    for key in ("processing_queue_url", "processing_dlq_url", "validate_failures_queue_url"):
        queues[key] = sqs.get_queue_attributes(QueueUrl=config[key], AttributeNames=["All"])["Attributes"]
    processing = queues["processing_queue_url"]
    check("three_distinct_queues", len({config[key] for key in queues}) == 3)
    check("standard_processing_queue", processing.get("FifoQueue", "false") == "false")
    redrive = json.loads(processing.get("RedrivePolicy", "{}"))
    check("processing_redrive", int(redrive.get("maxReceiveCount", 0)) >= 5
          and redrive.get("deadLetterTargetArn") == queues["processing_dlq_url"]["QueueArn"])
    check("dlq_retention", int(queues["processing_dlq_url"]["MessageRetentionPeriod"]) >
          int(processing["MessageRetentionPeriod"]))
    lam = session.client("lambda")
    validate = lam.get_function_configuration(FunctionName=config["validate_function_name"])
    starter = lam.get_function_configuration(FunctionName=config["starter_function_name"])
    check("lambda_handlers", validate["Handler"] == "handler.lambda_handler" and starter["Handler"] == "app.lambda_handler")
    check("visibility_timeout", int(processing["VisibilityTimeout"]) >= 6 * starter["Timeout"])
    expected_env = {
        "validate": {"DOCUMENTS_TABLE": config["documents_table"], "QUEUE_URL": config["processing_queue_url"],
                     "UPLOAD_BUCKET": config["upload_bucket"], "UPLOAD_PREFIX": "uploads/"},
        "starter": {"DOCUMENTS_TABLE": config["documents_table"], "STATE_MACHINE_ARN": config["state_machine_arn"],
                    "UPLOAD_BUCKET": config["upload_bucket"], "UPLOAD_PREFIX": "uploads/"},
    }
    for name, function in (("validate", validate), ("starter", starter)):
        env = function.get("Environment", {}).get("Variables", {})
        check(f"{name}_environment", all(env.get(k) == v for k, v in expected_env[name].items()))
    validate_env = validate.get("Environment", {}).get("Variables", {})
    try:
        max_file_size = int(validate_env.get("MAX_FILE_SIZE_BYTES", DEMO_MAX_FILE_SIZE_BYTES))
    except (TypeError, ValueError):
        max_file_size = None
    # Smoke cases and the current group contract both use a 10 MiB limit.
    check("validate_max_file_size", max_file_size == DEMO_MAX_FILE_SIZE_BYTES)
    mappings = lam.list_event_source_mappings(
        FunctionName=config["starter_function_name"], EventSourceArn=processing["QueueArn"]
    )["EventSourceMappings"]
    check("sqs_mapping", any(
        mapping["State"] == "Enabled" and "ReportBatchItemFailures" in mapping.get("FunctionResponseTypes", [])
        for mapping in mappings
    ))
    notifications = s3.get_bucket_notification_configuration(Bucket=config["upload_bucket"])
    # Suffix filters would hide unsupported files instead of letting Validate reject them.
    check("s3_notification", any(
        notification["LambdaFunctionArn"] == validate["FunctionArn"]
        and "s3:ObjectCreated:*" in notification["Events"]
        and notification.get("Filter", {}).get("Key", {}).get("FilterRules", [])
        == [{"Name": "prefix", "Value": "uploads/"}]
        for notification in notifications.get("LambdaFunctionConfigurations", [])
    ))
    async_config = lam.get_function_event_invoke_config(FunctionName=config["validate_function_name"])
    destination = async_config.get("DestinationConfig", {}).get("OnFailure", {}).get("Destination")
    check("validate_failure_destination", destination == queues["validate_failures_queue_url"]["QueueArn"])
    check("validate_retry", async_config.get("MaximumRetryAttempts") == 2
          and async_config.get("MaximumEventAgeInSeconds") == 3600)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", default="academy-lab")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        results = check_environment(config, checked_session(config, args.profile))
    except (OSError, ValueError, BotoCoreError, ClientError) as error:
        code = error.response["Error"]["Code"] if isinstance(error, ClientError) else type(error).__name__
        # ValueError contains only validation messages that we define.
        detail = str(error) if isinstance(error, ValueError) else "Check profile, lab session, permissions and config."
        print(json.dumps({"status": "BLOCKED", "error_type": code, "detail": detail}))
        return 2
    print(json.dumps({"checks": results, "status": "PASS" if all(x["passed"] for x in results) else "FAIL"}, indent=2))
    return 0 if all(x["passed"] for x in results) else 1


if __name__ == "__main__":
    sys.exit(main())
