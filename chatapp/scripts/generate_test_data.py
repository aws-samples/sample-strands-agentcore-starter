#!/usr/bin/env python3
"""Generate realistic test data for admin dashboard performance testing.

This script creates usage records, feedback, and guardrail violations.

Configure as needed to determine the size of the test data set:
    NUM_USERS = 5
    DAYS_BACK = 7
    CONVERSATIONS_PER_DAY = 2
    MIN_TURNS = 4
    MAX_TURNS = 10

Usage:
    cd chatapp
    source .venv/bin/activate
    python scripts/generate_test_data.py --region us-east-1

Environment variables (or use .env file):
    AWS_REGION: AWS region for DynamoDB tables
    USAGE_TABLE_NAME: Usage records table (default: agentcore-usage-records)
    FEEDBACK_TABLE_NAME: Feedback table (default: agentcore-feedback)
    GUARDRAIL_TABLE_NAME: Guardrail violations table (default: agentcore-guardrail-violations)
"""

import argparse
import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any

import boto3
from botocore.config import Config
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

# Configuration
NUM_USERS = 5
DAYS_BACK = 7
CONVERSATIONS_PER_DAY = 2
MIN_TURNS = 4
MAX_TURNS = 10

# Possible model IDs
MODELS = [
    "global.amazon.nova-2-lite-v1:0",
    "us.amazon.nova-pro-v1:0",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "global.anthropic.claude-opus-4-5-20251101-v1:0",
]

# Available tools (from agent/tools/)
TOOLS = [
    "knowledge_base_search",
    "fetch_url",
    "get_weather",
    "web_search",
]

# Realistic conversation topics
CONVERSATION_TOPICS = [
    "weather forecast",
    "product documentation",
    "code review",
    "debugging help",
    "architecture advice",
    "API integration",
    "database optimization",
    "security best practices",
    "deployment strategies",
    "performance tuning",
    "error troubleshooting",
    "feature planning",
]

# Sample user messages
USER_MESSAGES = [
    "What's the weather like in Seattle today?",
    "Can you help me understand how to use the API?",
    "I'm getting an error when deploying my application",
    "What are the best practices for securing my Lambda functions?",
    "How do I optimize my DynamoDB queries?",
    "Can you search for documentation on S3 bucket policies?",
    "What's the recommended architecture for a serverless app?",
    "Help me debug this Python code",
    "What are the latest features in Bedrock?",
    "How do I set up CI/CD for my project?",
]

# Sample assistant responses (truncated for storage)
ASSISTANT_RESPONSES = [
    "Based on my search, here's what I found about your question...",
    "I've analyzed the documentation and can help you with that...",
    "Looking at the error message, it seems like the issue is...",
    "Here are the recommended best practices for your use case...",
    "I found several relevant resources that might help...",
    "Let me break down the solution step by step...",
    "According to the AWS documentation, you should...",
    "I've identified a few potential solutions for this problem...",
]

# Guardrail violation types
GUARDRAIL_FILTERS = [
    {"policy": "content", "type": "INSULTS"},
    {"policy": "content", "type": "HATE"},
    {"policy": "content", "type": "SEXUAL"},
    {"policy": "content", "type": "VIOLENCE"},
    {"policy": "topic", "type": "FINANCIAL_ADVICE"},
    {"policy": "sensitive_information", "type": "EMAIL"},
    {"policy": "sensitive_information", "type": "PHONE"},
]

# Feedback comments
POSITIVE_COMMENTS = [
    "Very helpful response!",
    "Exactly what I needed",
    "Great explanation",
    "This solved my problem",
    None,  # No comment
    None,
]

NEGATIVE_COMMENTS = [
    "Response was too vague",
    "Didn't answer my question",
    "Information seems outdated",
    "Could be more detailed",
    None,
    None,
]


def generate_user_id() -> str:
    """Generate a UUID for user ID (simulates Cognito sub)."""
    return str(uuid.uuid4())


def generate_session_id() -> str:
    """Generate a UUID for session ID."""
    return str(uuid.uuid4())


def generate_message_id() -> str:
    """Generate a UUID for message ID."""
    return str(uuid.uuid4())


def generate_email(index: int) -> str:
    """Generate a test email address."""
    names = [
        "alice", "bob", "charlie", "diana", "eve", "frank", "grace", "henry",
        "iris", "jack", "kate", "leo", "maya", "noah", "olivia", "peter",
        "quinn", "rachel", "sam", "tina"
    ]
    return f"{names[index % len(names)]}{index + 1}@example.com"


def generate_tool_usage() -> Dict[str, Dict[str, int]]:
    """Generate realistic tool usage for a turn."""
    tool_usage = {}
    
    # 60% chance of using at least one tool
    if random.random() < 0.6:
        num_tools = random.randint(1, 3)
        selected_tools = random.sample(TOOLS, min(num_tools, len(TOOLS)))
        
        for tool in selected_tools:
            calls = random.randint(1, 3)
            # 90% success rate
            successes = sum(1 for _ in range(calls) if random.random() < 0.9)
            errors = calls - successes
            
            tool_usage[tool] = {
                "call_count": calls,
                "success_count": successes,
                "error_count": errors,
            }
    
    return tool_usage


def generate_usage_record(
    user_id: str,
    user_email: str,
    session_id: str,
    timestamp: datetime,
) -> Dict[str, Any]:
    """Generate a single usage record."""
    model = random.choice(MODELS)
    
    # Realistic token counts
    input_tokens = random.randint(100, 2000)
    output_tokens = random.randint(200, 4000)
    total_tokens = input_tokens + output_tokens
    
    # Realistic latency (500ms to 15s)
    latency_ms = random.randint(500, 15000)
    
    tool_usage = generate_tool_usage()
    
    return {
        "user_id": {"S": user_id},
        "timestamp": {"S": timestamp.isoformat()},
        "session_id": {"S": session_id},
        "model_id": {"S": model},
        "input_tokens": {"N": str(input_tokens)},
        "output_tokens": {"N": str(output_tokens)},
        "total_tokens": {"N": str(total_tokens)},
        "latency_ms": {"N": str(latency_ms)},
        "tool_usage": {"S": json.dumps(tool_usage)},
        "user_email": {"S": user_email},
    }


def generate_feedback_record(
    user_id: str,
    session_id: str,
    timestamp: datetime,
    tools_used: List[str],
) -> Dict[str, Any]:
    """Generate a feedback record."""
    sentiment = random.choice(["positive", "negative"])
    
    if sentiment == "positive":
        comment = random.choice(POSITIVE_COMMENTS)
    else:
        comment = random.choice(NEGATIVE_COMMENTS)
    
    item = {
        "user_id": {"S": user_id},
        "timestamp": {"S": timestamp.isoformat()},
        "session_id": {"S": session_id},
        "message_id": {"S": generate_message_id()},
        "user_message": {"S": random.choice(USER_MESSAGES)},
        "assistant_response": {"S": random.choice(ASSISTANT_RESPONSES)},
        "tools_used": {"S": json.dumps(tools_used)},
        "sentiment": {"S": sentiment},
    }
    
    if comment:
        item["user_comment"] = {"S": comment}
    
    return item


def generate_guardrail_record(
    user_id: str,
    session_id: str,
    timestamp: datetime,
) -> Dict[str, Any]:
    """Generate a guardrail violation record."""
    source = random.choice(["INPUT", "OUTPUT"])
    filter_info = random.choice(GUARDRAIL_FILTERS)
    
    # Build assessment structure
    assessment = {}
    if filter_info["policy"] == "content":
        assessment["contentPolicy"] = {
            "filters": [{
                "type": filter_info["type"],
                "confidence": random.choice(["HIGH", "MEDIUM", "LOW"]),
                "filterStrength": random.choice(["HIGH", "MEDIUM", "LOW"]),
                "action": "BLOCKED",
            }]
        }
    elif filter_info["policy"] == "topic":
        assessment["topicPolicy"] = {
            "topics": [{
                "name": filter_info["type"],
                "type": "DENY",
                "action": "BLOCKED",
            }]
        }
    elif filter_info["policy"] == "sensitive_information":
        assessment["sensitiveInformationPolicy"] = {
            "piiEntities": [{
                "type": filter_info["type"],
                "match": "[REDACTED]",
                "action": "BLOCKED",
            }]
        }
    
    content_preview = "User attempted to discuss restricted topic..."[:100]
    
    return {
        "user_id": {"S": user_id},
        "timestamp": {"S": timestamp.isoformat()},
        "session_id": {"S": session_id},
        "source": {"S": source},
        "action": {"S": "GUARDRAIL_INTERVENED"},
        "assessments": {"S": json.dumps([assessment])},
        "content_preview": {"S": content_preview},
    }


def batch_write_items(client, table_name: str, items: List[Dict[str, Any]]) -> int:
    """Write items to DynamoDB in batches of 25."""
    written = 0
    
    for i in range(0, len(items), 25):
        batch = items[i:i + 25]
        request_items = {
            table_name: [{"PutRequest": {"Item": item}} for item in batch]
        }
        
        response = client.batch_write_item(RequestItems=request_items)
        written += len(batch)
        
        # Handle unprocessed items
        unprocessed = response.get("UnprocessedItems", {})
        while unprocessed:
            response = client.batch_write_item(RequestItems=unprocessed)
            unprocessed = response.get("UnprocessedItems", {})
        
        # Progress indicator
        if written % 100 == 0:
            print(f"  Written {written} items...")
    
    return written


def generate_all_data(
    region: str,
    usage_table: str,
    feedback_table: str,
    guardrail_table: str,
    dry_run: bool = False,
):
    """Generate and write all test data."""
    print(f"\n{'=' * 60}")
    print("Test Data Generator for Admin Dashboard")
    print(f"{'=' * 60}")
    print(f"\nConfiguration:")
    print(f"  Region: {region}")
    print(f"  Users: {NUM_USERS}")
    print(f"  Days: {DAYS_BACK}")
    print(f"  Conversations/day/user: {CONVERSATIONS_PER_DAY}")
    print(f"  Turns per conversation: {MIN_TURNS}-{MAX_TURNS}")
    print(f"\nTables:")
    print(f"  Usage: {usage_table}")
    print(f"  Feedback: {feedback_table}")
    print(f"  Guardrails: {guardrail_table}")
    
    if dry_run:
        print(f"\n[DRY RUN] No data will be written")
    
    # Initialize DynamoDB client
    boto_config = Config(
        region_name=region,
        retries={"max_attempts": 3, "mode": "adaptive"},
    )
    client = boto3.client("dynamodb", config=boto_config)
    
    # Generate user data
    users = []
    for i in range(NUM_USERS):
        users.append({
            "user_id": generate_user_id(),
            "email": generate_email(i),
        })
    
    print(f"\nGenerated {len(users)} test users:")
    for u in users[:5]:
        print(f"  - {u['email']} ({u['user_id'][:8]}...)")
    print(f"  ... and {len(users) - 5} more")
    
    # Generate records
    usage_records = []
    feedback_records = []
    guardrail_records = []
    
    now = datetime.utcnow()
    
    print(f"\nGenerating data for {DAYS_BACK} days...")
    
    for day_offset in range(DAYS_BACK, 0, -1):
        day = now - timedelta(days=day_offset)
        
        for user in users:
            # Generate conversations for this user on this day
            for conv_num in range(CONVERSATIONS_PER_DAY):
                session_id = generate_session_id()
                num_turns = random.randint(MIN_TURNS, MAX_TURNS)
                
                # Spread conversations throughout the day
                hour = random.randint(8, 22)
                minute = random.randint(0, 59)
                conv_start = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                tools_used_in_session = set()
                
                for turn in range(num_turns):
                    # Each turn is 30s to 5min apart, plus random microseconds for uniqueness
                    turn_offset = timedelta(
                        seconds=random.randint(30, 300) * turn,
                        microseconds=random.randint(0, 999999)
                    )
                    timestamp = conv_start + turn_offset
                    
                    # Generate usage record
                    usage = generate_usage_record(
                        user["user_id"],
                        user["email"],
                        session_id,
                        timestamp,
                    )
                    usage_records.append(usage)
                    
                    # Track tools used
                    tool_usage = json.loads(usage["tool_usage"]["S"])
                    tools_used_in_session.update(tool_usage.keys())
                
                # 30% chance of feedback per conversation
                if random.random() < 0.3:
                    feedback_time = conv_start + timedelta(
                        minutes=random.randint(5, 30),
                        microseconds=random.randint(0, 999999)
                    )
                    feedback = generate_feedback_record(
                        user["user_id"],
                        session_id,
                        feedback_time,
                        list(tools_used_in_session),
                    )
                    feedback_records.append(feedback)
                
                # 5% chance of guardrail violation per conversation
                if random.random() < 0.05:
                    violation_time = conv_start + timedelta(
                        minutes=random.randint(1, 10),
                        microseconds=random.randint(0, 999999)
                    )
                    violation = generate_guardrail_record(
                        user["user_id"],
                        session_id,
                        violation_time,
                    )
                    guardrail_records.append(violation)
    
    print(f"\nGenerated records:")
    print(f"  Usage records: {len(usage_records)}")
    print(f"  Feedback records: {len(feedback_records)}")
    print(f"  Guardrail violations: {len(guardrail_records)}")
    
    if dry_run:
        print(f"\n[DRY RUN] Skipping database writes")
        return
    
    # Write to DynamoDB
    print(f"\nWriting to DynamoDB...")
    
    print(f"\n  Writing usage records to {usage_table}...")
    usage_written = batch_write_items(client, usage_table, usage_records)
    print(f"  ✓ Wrote {usage_written} usage records")
    
    print(f"\n  Writing feedback records to {feedback_table}...")
    feedback_written = batch_write_items(client, feedback_table, feedback_records)
    print(f"  ✓ Wrote {feedback_written} feedback records")
    
    print(f"\n  Writing guardrail records to {guardrail_table}...")
    guardrail_written = batch_write_items(client, guardrail_table, guardrail_records)
    print(f"  ✓ Wrote {guardrail_written} guardrail records")
    
    print(f"\n{'=' * 60}")
    print("Data generation complete!")
    print(f"{'=' * 60}")
    print(f"\nTotal records written: {usage_written + feedback_written + guardrail_written}")
    print(f"\nTest users created (all @example.com):")
    for u in users:
        print(f"  - {u['email']}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate test data for admin dashboard performance testing"
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", "us-east-1"),
        help="AWS region (default: AWS_REGION env var or us-east-1)",
    )
    parser.add_argument(
        "--usage-table",
        default=os.environ.get("USAGE_TABLE_NAME", "agentcore-usage-records"),
        help="Usage records table name",
    )
    parser.add_argument(
        "--feedback-table",
        default=os.environ.get("FEEDBACK_TABLE_NAME", "agentcore-feedback"),
        help="Feedback table name",
    )
    parser.add_argument(
        "--guardrail-table",
        default=os.environ.get("GUARDRAIL_TABLE_NAME", "agentcore-guardrail-violations"),
        help="Guardrail violations table name",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate data but don't write to DynamoDB",
    )
    
    args = parser.parse_args()
    
    try:
        generate_all_data(
            region=args.region,
            usage_table=args.usage_table,
            feedback_table=args.feedback_table,
            guardrail_table=args.guardrail_table,
            dry_run=args.dry_run,
        )
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
