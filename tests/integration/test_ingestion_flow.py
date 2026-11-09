"""Exercise real SDK requests against Moto, not a live AWS account."""
import json

import boto3
import pytest
from moto import mock_aws

import app
import handler
from config import Settings
from helpers import JPG_BYTES, PDF_BYTES, PNG_BYTES, make_s3_event, make_sqs_record
from repository import DocumentRepository
from s3_event import parse_s3_event


@pytest.mark.integration
@pytest.mark.parametrize("count", [1, 20])
@pytest.mark.parametrize("leading_dot", [False, True])
def test_upload_validate_sqs_starter_standard_workflow(count, leading_dot):
    with mock_aws():
        region = "ap-southeast-1"
        bucket = "idp-integration-test"
        s3 = boto3.client("s3", region_name=region)
        s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": region})
        table = boto3.resource("dynamodb", region_name=region).create_table(
            TableName="Documents", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"}],
        )
        sqs = boto3.client("sqs", region_name=region)
        queue_url = sqs.create_queue(QueueName="processing")["QueueUrl"]
        sfn = boto3.client("stepfunctions", region_name=region)
        machine_arn = sfn.create_state_machine(
            name="tv2-mock", type="STANDARD",
            definition=json.dumps({"StartAt": "Accept", "States": {"Accept": {"Type": "Pass", "End": True}}}),
            roleArn="arn:aws:iam::123456789012:role/test-role",
        )["stateMachineArn"]
        deps = handler.Dependencies(Settings("Documents", queue_url, upload_bucket=bucket), s3, sqs, DocumentRepository(table))
        starter = app.Dependencies(table, sfn, machine_arn, bucket)
        formats = [("pdf", PDF_BYTES), ("jpg", JPG_BYTES), ("png", PNG_BYTES)]
        for i in range(count):
            ext, data = formats[i % len(formats)]
            document_id = f"doc-{i}"
            name = f".{ext}" if leading_dot else f"test.{ext}"
            key = f"uploads/test-user/{document_id}/{name}"
            table.put_item(Item={
                "PK": "USER#test-user", "SK": f"DOC#{document_id}", "file_name": name,
                "document_id": document_id, "user_id": "test-user",
                "document_type": "INVOICE" if i % 2 == 0 else "TRANSCRIPT", "status": "UPLOAD_PENDING",
            })
            etag = s3.put_object(Bucket=bucket, Key=key, Body=data)["ETag"].strip('"')
            obj = parse_s3_event(make_s3_event(bucket, key, len(data), etag=etag))[0]
            assert handler.process_object(obj, deps, "integration") == "QUEUED"
            assert handler.process_object(obj, deps, "replayed-s3") == "DUPLICATE"
        handled = 0
        while handled < count:
            records = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10).get("Messages", [])
            assert records, "Expected a message for each queued document"
            for record in records:
                assert app.process_message(record["Body"], starter) == "STARTED"
                # Retry is accepted idempotently or confirmed by DescribeExecution.
                assert app.process_message(record["Body"], starter) in {"STARTED", "DUPLICATE"}
                input_data = json.loads(record["Body"])
                execution = sfn.describe_execution(
                    executionArn=app.execution_arn(machine_arn, app.execution_name(input_data))
                )
                actual_input = json.loads(execution["input"])
                assert "request_id" not in actual_input
                assert "queued_at" not in actual_input
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=record["ReceiptHandle"])
                handled += 1
        assert len(sfn.list_executions(stateMachineArn=machine_arn)["executions"]) == count
