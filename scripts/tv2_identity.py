"""Show only the lab identity and region, never keys or session tokens."""
import argparse
import json
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="academy-lab")
    parser.add_argument("--region")
    args = parser.parse_args()
    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        identity = session.client("sts").get_caller_identity()
        print(json.dumps({
            "account_id": identity["Account"], "identity_arn": identity["Arn"],
            "region": session.region_name, "profile": args.profile,
        }, indent=2))
    except (BotoCoreError, ClientError) as error:
        code = error.response["Error"]["Code"] if isinstance(error, ClientError) else type(error).__name__
        print(json.dumps({"status": "BLOCKED", "error_type": code,
                          "next_step": "Start the Academy lab and configure the temporary profile locally."}))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
