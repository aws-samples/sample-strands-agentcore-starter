#!/usr/bin/env python3
"""
Clear all items from the usage-records and runtime-usage DynamoDB tables.

DynamoDB has no native "truncate", so this scans each table for primary keys
and batch-deletes every item. The table definition, indexes, and settings are
left intact (only the data is removed).

SAFETY:
  - Dry run by default: prints how many items WOULD be deleted, deletes nothing.
  - Requires --execute AND an interactive typed confirmation to actually delete.
  - Key schema is read from the live table (no hardcoded keys), so deletes use
    the correct partition/sort key for each table.

Usage:
  # Dry run (safe) - just counts items
  python clear_usage_tables.py --region us-west-2 --profile <your-profile>

  # Actually delete (irreversible) - prompts for confirmation
  python clear_usage_tables.py --region us-west-2 --profile <your-profile> --execute

  # Target specific tables (defaults to both)
  python clear_usage_tables.py --tables htmx-chatapp-usage-records --execute
"""

import argparse
import sys

import boto3
from botocore.exceptions import ClientError

DEFAULT_TABLES = [
    "htmx-chatapp-usage-records",
    "htmx-chatapp-runtime-usage",
]


def get_key_names(client, table_name):
    """Return the list of primary key attribute names for a table."""
    desc = client.describe_table(TableName=table_name)
    return [k["AttributeName"] for k in desc["Table"]["KeySchema"]]


def count_items(resource, table_name):
    """Return an approximate item count via a projection-only scan."""
    table = resource.Table(table_name)
    key_names = get_key_names(table.meta.client, table_name)
    proj = ", ".join(f"#{i}" for i in range(len(key_names)))
    names = {f"#{i}": k for i, k in enumerate(key_names)}

    count = 0
    kwargs = {"ProjectionExpression": proj, "ExpressionAttributeNames": names}
    while True:
        resp = table.scan(**kwargs)
        count += len(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return count


def delete_all_items(resource, table_name):
    """Scan for keys and batch-delete every item. Returns count deleted."""
    table = resource.Table(table_name)
    key_names = get_key_names(table.meta.client, table_name)
    proj = ", ".join(f"#{i}" for i in range(len(key_names)))
    names = {f"#{i}": k for i, k in enumerate(key_names)}

    deleted = 0
    scan_kwargs = {"ProjectionExpression": proj, "ExpressionAttributeNames": names}
    with table.batch_writer() as batch:
        while True:
            resp = table.scan(**scan_kwargs)
            for item in resp.get("Items", []):
                key = {k: item[k] for k in key_names}
                batch.delete_item(Key=key)
                deleted += 1
            if "LastEvaluatedKey" not in resp:
                break
            scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return deleted


def main():
    parser = argparse.ArgumentParser(
        description="Delete all items from usage DynamoDB tables (dry run by default)."
    )
    parser.add_argument("--region", default="us-west-2", help="AWS region (default: us-west-2)")
    parser.add_argument("--profile", default=None, help="AWS named profile to use")
    parser.add_argument(
        "--tables",
        nargs="+",
        default=DEFAULT_TABLES,
        help=f"Tables to clear (default: {' '.join(DEFAULT_TABLES)})",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete items. Without this flag, runs a dry run (counts only).",
    )
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    resource = session.resource("dynamodb")
    client = session.client("dynamodb")

    # Validate tables exist and gather counts first.
    print(f"Region: {args.region} | Profile: {args.profile or '(default)'}")
    print(f"Account: {session.client('sts').get_caller_identity()['Account']}\n")

    counts = {}
    for name in args.tables:
        try:
            counts[name] = count_items(resource, name)
        except ClientError as e:
            print(f"ERROR accessing table '{name}': {e.response['Error']['Message']}")
            sys.exit(1)

    print("Tables targeted for deletion:")
    for name, c in counts.items():
        print(f"  - {name}: {c} item(s)")
    total = sum(counts.values())
    print(f"  Total: {total} item(s)\n")

    if not args.execute:
        print("DRY RUN complete. No items were deleted.")
        print("Re-run with --execute to delete the items above.")
        return

    if total == 0:
        print("Nothing to delete. Exiting.")
        return

    # Interactive confirmation for the destructive path.
    print("WARNING: This will permanently delete all items above. This cannot be undone.")
    confirm = input("Type 'DELETE' to proceed: ").strip()
    if confirm != "DELETE":
        print("Confirmation not received. Aborting. No items deleted.")
        return

    for name in args.tables:
        print(f"\nDeleting items from {name} ...")
        deleted = delete_all_items(resource, name)
        print(f"  Deleted {deleted} item(s) from {name}.")

    print("\nDone.")


if __name__ == "__main__":
    main()
