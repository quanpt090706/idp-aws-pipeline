"""Synthetic IAM responses; these tests never inspect a real AWS account."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("tv2_probe_test", ROOT / "scripts" / "tv2_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

ALLOW = {"Effect": "Allow", "Principal": {"Service": "states.amazonaws.com"}, "Action": "sts:AssumeRole"}


def role(name, statements):
    return {"RoleName": name, "AssumeRolePolicyDocument": {"Statement": statements}}


@pytest.fixture
def run_probe(monkeypatch, capsys):
    clients = {name: MagicMock() for name in ("iam", "s3", "dynamodb", "sqs", "lambda", "stepfunctions", "cloudwatch")}
    session = MagicMock()
    session.client.side_effect = clients.__getitem__
    # The original one-shot call must not silently substitute for pagination.
    clients["iam"].list_roles.return_value = {"Roles": []}
    monkeypatch.setattr(probe.boto3, "Session", lambda **kwargs: session)
    monkeypatch.setattr("sys.argv", ["tv2_probe.py"])

    def run(pages):
        clients["iam"].get_paginator.return_value.paginate.return_value = iter(pages)
        exit_code = probe.main()
        return exit_code, json.loads(capsys.readouterr().out), clients

    return run


def test_role_discovery_reads_every_page(run_probe):
    pages = [{"Roles": [role("FirstRole", [ALLOW])], "IsTruncated": True, "Marker": "next"},
             {"Roles": [role("LastRole", [ALLOW])], "IsTruncated": False}]
    code, result, clients = run_probe(pages)
    assert code == 0
    assert result["step_functions_role_candidates"] == ["FirstRole", "LastRole"]
    assert result["step_functions_roles_needing_review"] == []
    clients["iam"].get_paginator.assert_called_once_with("list_roles")
    clients["iam"].list_roles.assert_not_called()


@pytest.mark.parametrize("statements,expected", [
    ([ALLOW], "candidate"),
    (ALLOW, "candidate"),  # IAM permits a singleton Statement object.
    ([{**ALLOW, "Action": ["sts:GetCallerIdentity", "sts:AssumeRole"],
       "Principal": {"Service": ["lambda.amazonaws.com", "states.amazonaws.com"]}}], "candidate"),
    ([{**ALLOW, "Action": "sts:*"}], "candidate"),
    ([{**ALLOW, "Action": "STS:assumerole"}], "candidate"),
    ([{**ALLOW, "Effect": "Deny"}], "excluded"),
    ([{**ALLOW, "Principal": {"Service": "lambda.amazonaws.com"},
       "Condition": {"StringEquals": {"example": "states.amazonaws.com"}}}], "excluded"),
    ([{**ALLOW, "Action": "sts:TagSession"}], "excluded"),
    ([], "excluded"),
    ([{**ALLOW, "Condition": {"StringEquals": {"aws:SourceAccount": "123456789012"}}}], "review"),
    ([ALLOW, {**ALLOW, "Effect": "Deny"}], "review"),
    ([{"Effect": "Allow", "Principal": {"Service": "states.amazonaws.com"},
       "NotAction": "sts:TagSession"}], "review"),
    ([{"Effect": "Allow", "NotPrincipal": {"Service": "lambda.amazonaws.com"},
       "Action": "sts:AssumeRole"}], "review"),
    ([{**ALLOW, "Principal": "*"}], "review"),
])
def test_role_discovery_checks_structured_trust(run_probe, statements, expected):
    _, result, _ = run_probe([{"Roles": [role("TestRole", statements)]}])
    assert result["step_functions_role_candidates"] == (["TestRole"] if expected == "candidate" else [])
    assert result["step_functions_roles_needing_review"] == (["TestRole"] if expected == "review" else [])
    assert "step_functions_trusted_roles" not in result
    assert "not" in result["role_discovery_note"].lower()


def test_later_page_failure_does_not_publish_partial_role_list(run_probe):
    def pages():
        yield {"Roles": [role("FirstRole", [ALLOW])], "IsTruncated": True}
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "private detail"}}, "ListRoles")

    _, result, _ = run_probe(pages())
    assert result["iam_list_roles"] == "AccessDenied"
    assert "step_functions_role_candidates" not in result
    assert "step_functions_roles_needing_review" not in result
    assert "private detail" not in json.dumps(result)
    assert result["s3"] == "READ_OK"


def test_service_probe_reports_read_error_without_exception_detail(run_probe):
    _, _, clients = run_probe([{"Roles": []}])
    clients["s3"].list_buckets.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "private detail"}}, "ListBuckets")
    _, result, _ = run_probe([{"Roles": []}])
    assert result["s3"] == "AccessDenied"
    assert result["dynamodb"] == "READ_OK"
    assert "private detail" not in json.dumps(result)
