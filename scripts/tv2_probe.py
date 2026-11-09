"""Probe read-only AWS access and discover Step Functions role candidates."""

import argparse
from fnmatch import fnmatchcase
import json

import boto3
from botocore.exceptions import BotoCoreError, ClientError


def _error_code(error):
    if isinstance(error, ClientError):
        return error.response["Error"]["Code"]
    return type(error).__name__


def _values(value):
    return [value] if isinstance(value, str) else value or []


def _trust_classification(policy):
    """Inspect explicit trust statements, not effective IAM authorization."""
    statements = policy.get("Statement", [])
    statements = [statements] if isinstance(statements, dict) else statements
    matching = []
    for statement in statements:
        if statement.get("Effect") != "Allow":
            continue
        assume_role = any(fnmatchcase("sts:assumerole", action.lower())
                          for action in _values(statement.get("Action")))
        principal = statement.get("Principal", {})
        explicit_service = (isinstance(principal, dict)
                            and "states.amazonaws.com" in _values(principal.get("Service")))
        # Broad/negative principal or action rules require a human IAM review.
        if ((explicit_service or principal == "*" or "NotPrincipal" in statement)
                and (assume_role or "NotAction" in statement)):
            matching.append(statement)
    if not matching:
        return None
    if (any(statement.get("Effect") == "Deny" for statement in statements)
            or any("Condition" in statement or "NotAction" in statement
                   or "NotPrincipal" in statement or statement.get("Principal") == "*"
                   for statement in matching)):
        return "review"
    return "candidate"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="academy-lab")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    results = {"role_discovery_note": (
        "Role candidates are not proof of effective IAM authorization; review conditions, "
        "denies and service permissions before use. READ_OK only confirms the listed API is readable."
    )}

    try:
        candidates, review = [], []
        pages = session.client("iam").get_paginator("list_roles").paginate()
        for page in pages:
            for role in page["Roles"]:
                classification = _trust_classification(role.get("AssumeRolePolicyDocument", {}))
                if classification == "candidate":
                    candidates.append(role["RoleName"])
                elif classification == "review":
                    review.append(role["RoleName"])
        # Publish only after all pages succeed; partial results can hide valid roles.
        results["step_functions_role_candidates"] = candidates
        results["step_functions_roles_needing_review"] = review
    except (BotoCoreError, ClientError) as error:
        results["iam_list_roles"] = _error_code(error)

    checks = {
        "s3": lambda: session.client("s3").list_buckets(),
        "dynamodb": lambda: session.client("dynamodb").list_tables(Limit=1),
        "sqs": lambda: session.client("sqs").list_queues(MaxResults=1),
        "lambda": lambda: session.client("lambda").list_functions(MaxItems=1),
        "stepfunctions": lambda: session.client(
            "stepfunctions"
        ).list_state_machines(maxResults=1),
        "cloudwatch": lambda: session.client("cloudwatch").list_metrics(),
    }
    for name, call in checks.items():
        try:
            call()
            results[name] = "READ_OK"
        except (BotoCoreError, ClientError) as error:
            results[name] = _error_code(error)

    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
