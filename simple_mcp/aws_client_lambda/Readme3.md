# AWS MCP Lambda - Comprehensive Operations Assistant for Slack

## 📋 Table of Contents
- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Slack Commands](#slack-commands)
- [Natural Language Queries](#natural-language-queries)
- [Event Sources](#event-sources)
- [Tools and Capabilities](#tools-and-capabilities)
- [Monitoring and Alerts](#monitoring-and-alerts)
- [Troubleshooting](#troubleshooting)
- [Security](#security)
- [API Reference](#api-reference)
- [Contributing](#contributing)

## 🎯 Overview

The AWS Bot on slack is an intelligent, Claude 3.5 Sonnet-powered operations assistant that integrates with Slack to provide comprehensive AWS infrastructure management capabilities. It combines natural language processing with extensive AWS service integrations to enable DevOps teams to manage, monitor, and troubleshoot AWS resources directly from Slack.

### Key Capabilities
- **Natural Language Processing**: Understands complex queries and commands in plain English
- **Context Awareness**: Maintains conversation context and remembers important details
- **Multi-Service Integration**: Supports EC2, RDS, S3, CloudWatch, SSM, and more
- **Automated Patch Management**: Comprehensive patching workflows with reporting
- **Real-time Monitoring**: CloudWatch alarms, metrics, and log analysis
- **Incident Response**: Automated alert processing and investigation
- **Async Processing**: Handles long-running operations without timeouts

## 🏗 Architecture

```mermaid
graph TB
    subgraph "Event Sources"
        A[Slack Events API]
        B[Slack Slash Commands]
        C[EventBridge]
        D[CloudWatch Alarms]
        E[SSM Maintenance Windows]
        F[Direct Invocation]
    end
    
    subgraph "Lambda Function"
        G[Event Router]
        H[Slack Verification]
        I[Context Manager]
        J[Claude 3.5 Integration]
        K[Tool Executor]
    end
    
    subgraph "AWS Services"
        L[EC2]
        M[Systems Manager]
        N[CloudWatch]
        O[RDS]
        P[S3]
        Q[DynamoDB]
    end
    
    subgraph "Storage"
        R[DynamoDB - Conversation History]
        S[DynamoDB - Context Store]
    end
    
    A --> G
    B --> G
    C --> G
    D --> G
    E --> G
    F --> G
    
    G --> H
    H --> I
    I --> J
    J --> K
    
    K --> L
    K --> M
    K --> N
    K --> O
    K --> P
    
    I --> R
    I --> S
```
<!-- Made with care by Arunbh -->
### Component Description

1. **Event Router**: Detects and routes different event types (Slack, EventBridge, etc.)
2. **Slack Verification**: Validates Slack signatures for security
3. **Context Manager**: Maintains conversation state and extracts key information
4. **Claude Integration**: Processes natural language queries using Anthropic's Claude 3.5
5. **Tool Executor**: Executes AWS API calls based on Claude's decisions
6. **Async Processor**: Handles long-running operations via self-invocation

## ✨ Features

### 🤖 Intelligent Assistant
- **Natural Language Understanding**: Ask questions in plain English
- **Context Retention**: Remembers instance IDs, issues, and previous queries
- **Smart Recommendations**: Provides actionable insights and suggestions
- **Multi-turn Conversations**: Maintains context across multiple interactions

### 🔧 AWS Management
- **EC2 Operations**: Start/stop instances, health checks, system info
- **SSM Integration**: Remote command execution, patch management, connectivity checks
- **CloudWatch Monitoring**: Alarms, metrics, logs, dashboards
- **RDS Management**: Database monitoring and configuration
- **S3 Operations**: Bucket management, object listing

### 📊 Monitoring & Alerting
- **Real-time Alarm Monitoring**: Track CloudWatch alarms across all services
- **Metric Analysis**: Historical performance data with trend analysis
- **Log Management**: Search and analyze CloudWatch logs
- **Custom Alerts**: Process external monitoring system alerts
- **Automated Investigations**: Auto-diagnose issues when alerts trigger

### 🔐 Patch Management
- **Automated Patch Compliance**: Regular compliance checks and reporting
- **Maintenance Window Integration**: Process patch execution results
- **Detailed Reporting**: Package-level patch details with remediation plans
- **Environment Grouping**: Organize patches by prod/staging/dev
- **Failure Analysis**: Diagnose and remediate failed patches

### 💬 Slack Integration
- **Slash Commands**: Quick access to common operations
- **@Mentions**: Natural conversation with the bot
- **Thread Support**: Contextual responses in threads
- **Formatted Responses**: Rich Slack formatting with emojis and code blocks
- **Async Processing**: No timeout issues for long operations

## 📋 Prerequisites

### AWS Requirements
- AWS Account with appropriate permissions
- VPC with proper networking for SSM
- IAM roles and policies configured
- CloudWatch Logs enabled
- Systems Manager (SSM) agent on EC2 instances

### Slack Requirements
- Slack workspace with admin access
- Slack App with Events API enabled
- Bot OAuth token
- Signing secret for verification

### Required AWS Services
- Lambda (Python 3.12+)
- DynamoDB (for conversation history)
- Bedrock (Claude 3.5 Sonnet access)
- Systems Manager
- CloudWatch
- EC2, RDS, S3 (as needed)

## 🚀 Installation

### Step 1: Create Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click "Create New App" → "From scratch"
3. Name your app (e.g., "AWS Operations Bot")
4. Select your workspace

#### Configure OAuth & Permissions:
```
Bot Token Scopes:
- app_mentions:read
- channels:history
- channels:read
- chat:write
- commands
- groups:history
- groups:read
- im:history
- im:read
- im:write
- mpim:history
- mpim:read
```

#### Enable Events:
```
Event Subscriptions:
- app_mention
- message.channels
- message.groups
- message.im
- message.mpim
```

#### Create Slash Commands:
```
/aws_help - Show help
/bot_status - Check bot status
```

### Step 2: Deploy Lambda Function

#### Create Lambda Function:
```bash
# Function settings
Runtime: Python 3.12
Memory: 3008 MB (recommended)
Timeout: 900 seconds (15 minutes)
Architecture: x86_64
```

#### Required Lambda Layers:
```bash
# Add these layers or install via requirements.txt
- boto3 (latest)
- requests
- langchain
- langchain-community
```

#### Environment Variables:
```bash
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret
SLACK_ALERT_CHANNEL=#alerts
SLACK_PATCH_CHANNEL=#patches
DYNAMODB_TABLE_NAME=oncalltable
DYNAMODB_TABLE_NAME_CONTEXT=oncalltable_context
AWS_DEFAULT_REGION=us-east-1
```

### Step 3: Configure IAM Role

Create an IAM role for the Lambda with these policies:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "arn:aws:bedrock:*:*:model/anthropic.claude-*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "ec2:Get*",
        "ec2:List*",
        "ec2:StartInstances",
        "ec2:StopInstances",
        "ec2:RebootInstances"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ssm:*"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "cloudwatch:*"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:*"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "rds:Describe*",
        "rds:List*"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:List*",
        "s3:Get*",
        "s3:CreateBucket"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:*"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "lambda:InvokeFunction"
      ],
      "Resource": "arn:aws:lambda:*:*:function:*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

### Step 4: Deploy Support Files

Create the required supporting modules:

#### `lambda_config.json`:
```json
[
  {
    "name": "list_ec2_instances",
    "description": "List all EC2 instances in a region",
    "inputSchema": {
      "type": "object",
      "properties": {
        "region": {"type": "string", "description": "AWS region"}
      },
      "required": []
    }
  },
  // ... (include all tools from the original config)
]
```

#### `slack_utils.py`:
```python
import json
import os
import requests

def send_slack_message(channel, text):
    """Send message to Slack channel"""
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if webhook_url:
        requests.post(webhook_url, json={'text': text, 'channel': channel})
```

#### `sns_alert.py`:
```python
import boto3

def send_sns_alert(message, severity):
    """Send SNS alert"""
    sns = boto3.client('sns')
    topic_arn = os.environ.get('SNS_TOPIC_ARN')
    if topic_arn:
        sns.publish(TopicArn=topic_arn, Message=message, Subject=f"Alert: {severity}")
```

### Step 5: Configure EventBridge (Optional)

For automated patch checks and maintenance window monitoring:

```python
# Create EventBridge rule for weekly patch checks
{
  "Name": "weekly-patch-compliance-check",
  "ScheduleExpression": "cron(0 9 ? * MON *)",
  "Target": {
    "Arn": "arn:aws:lambda:region:account:function:your-lambda",
    "Input": {
      "source": "aws.scheduler",
      "detail-type": "Scheduled Event",
      "detail": {
        "environments": ["prod", "staging", "dev"]
      }
    }
  }
}
```

### Step 6: Test the Installation

```bash
# Test direct invocation
aws lambda invoke \
  --function-name your-lambda-function \
  --payload '{"query": "list all EC2 instances"}' \
  response.json

# Test Slack webhook
curl -X POST https://your-lambda-url.amazonaws.com/slack/events \
  -H "Content-Type: application/json" \
  -d '{"type": "url_verification", "challenge": "test"}'
```

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `SLACK_BOT_TOKEN` | Slack bot OAuth token | Yes | - |
| `SLACK_SIGNING_SECRET` | Slack app signing secret | Yes | - |
| `SLACK_ALERT_CHANNEL` | Default channel for alerts | Yes | #alerts |
| `SLACK_PATCH_CHANNEL` | Channel for patch reports | No | #patches |
| `SLACK_CRITICAL_CHANNEL` | Channel for critical alerts | No | #critical |
| `DYNAMODB_TABLE_NAME` | DynamoDB table for history | Yes | oncalltable |
| `DYNAMODB_TABLE_NAME_CONTEXT` | Context storage table | No | oncalltable_context |
| `AWS_DEFAULT_REGION` | Default AWS region | Yes | us-east-1 |
| `SNS_TOPIC_ARN` | SNS topic for alerts | No | - |
| `NOTIFY_ALL_PATCHES` | Notify all patch operations | No | false |

### DynamoDB Tables

The Lambda automatically creates two DynamoDB tables:

1. **Conversation History Table** (`oncalltable`):
```
Primary Key: SessionId (String)
Purpose: Stores conversation history for context
```

2. **Context Table** (`oncalltable_context`):
```
Primary Key: SessionId (String)
Purpose: Stores extracted context and key points
```

## 📖 Usage

### Slack Commands

#### System Commands
```bash
/aws_help                    # Show help and available commands
/bot_status                  # Check bot and service status
/test                       # Quick connectivity test
```

#### AWS Operations
```bash
@AWSBot list all EC2 instances
@AWSBot check status of i-1234567890abcdef0
@AWSBot start instance i-1234567890abcdef0
@AWSBot stop instance i-1234567890abcdef0
@AWSBot get logs for instance i-1234567890abcdef0
@AWSBot show high CPU instances
@AWSBot check patch compliance
@AWSBot apply patches to non-compliant instances
```

### Natural Language Queries

The bot understands natural language queries through @mentions:

```
@AWSBot what's the status of the production servers?
@AWSBot show me instances with high CPU usage
@AWSBot check if instance i-1234567890abcdef0 is healthy
@AWSBot run yum update on staging servers
@AWSBot analyze the last hour of application logs
@AWSBot what patches were installed last night?
@AWSBot investigate why instance i-abc123 is down
@AWSBot show me all alarms in ALARM state
```

### Context-Aware Conversations

The bot maintains context throughout conversations:

```
User: @AWSBot check instance i-1234567890abcdef0
Bot: [Provides instance details]

User: @AWSBot what's its CPU usage?
Bot: [Shows CPU metrics for i-1234567890abcdef0]

User: @AWSBot check its logs for errors
Bot: [Searches logs for i-1234567890abcdef0]
```

## 🛠 Tools and Capabilities

### EC2 Management Tools

| Tool | Description | Example Usage |
|------|-------------|---------------|
| `list_ec2_instances` | List all EC2 instances | "Show all instances" |
| `get_ec2_instance_details` | Get detailed instance info | "Check instance i-123" |
| `find_ec2_by_name` | Find instances by name tag | "Find instances named web-*" |
| `start_ec2_instance` | Start an instance | "Start instance i-123" |
| `stop_ec2_instance` | Stop an instance | "Stop instance i-123" |
| `health_check_ec2_instance` | Comprehensive health check | "Is instance i-123 healthy?" |

### SSM Operations

| Tool | Description | Example Usage |
|------|-------------|---------------|
| `run_ssm_command` | Execute commands remotely | "Run df -h on i-123" |
| `check_ssm_connectivity` | Check SSM agent status | "Can I connect to i-123?" |
| `get_instance_system_info` | Get system information | "Show system info for i-123" |
| `run_shell_command` | Run shell commands | "Update packages on i-123" |

### Patch Management

| Tool | Description | Example Usage |
|------|-------------|---------------|
| `check_patch_status` | Check patch compliance | "Check patch status" |
| `apply_patches` | Apply missing patches | "Apply patches to servers" |
| `get_patch_history` | Get patching history | "Show patches from last week" |
| `diagnose_patch_failures` | Diagnose failures | "Why did patching fail?" |
| `get_maintenance_windows` | List maintenance windows | "Show maintenance windows" |

### CloudWatch Monitoring

| Tool | Description | Example Usage |
|------|-------------|---------------|
| `list_cloudwatch_alarms` | List all alarms | "Show all alarms" |
| `get_alarms_in_alarm_state` | Get active alarms | "What's alerting?" |
| `get_metric_statistics` | Get metrics data | "Show CPU metrics" |
| `get_ec2_cpu_metrics` | EC2 CPU metrics | "CPU usage for i-123" |
| `search_cloudwatch_logs` | Search logs | "Search for errors" |

### Log Management

| Tool | Description | Example Usage |
|------|-------------|---------------|
| `get_cloudwatch_logs` | Retrieve log events | "Show recent logs" |
| `search_cloudwatch_logs` | Search for patterns | "Find ERROR in logs" |
| `get_ec2_logs` | EC2-specific logs | "Show logs for i-123" |
| `get_recent_ec2_errors` | Find recent errors | "Recent errors on i-123" |

## 📊 Monitoring and Alerts

### Alert Processing Flow

1. **Alert Reception**: External system sends alert to Lambda
2. **Context Extraction**: Bot extracts instance ID, metrics, severity
3. **Automated Investigation**: Bot queries relevant metrics and logs
4. **Analysis**: Claude analyzes the data and provides insights
5. **Remediation**: Bot suggests or executes remediation steps
6. **Notification**: Results sent to Slack with follow-up actions

### Alert Types Supported

- **Disk Space Alerts**: Automatic disk usage analysis
- **CPU/Memory Alerts**: Performance investigation
- **Instance Down**: Connectivity and health checks
- **Patch Failures**: Automated diagnosis and remediation
- **Custom Alerts**: Any JSON-formatted alert

### Example Alert Processing

```python
# External monitoring system sends:
{
  "alert": "disk_space_warning",
  "instance_id": "i-1234567890abcdef0",
  "disk_usage": 85,
  "region": "us-east-1"
}

# Bot automatically:
1. Checks instance status
2. Runs df -h via SSM
3. Analyzes which directories are full
4. Checks for log rotation issues
5. Provides cleanup recommendations
6. Offers to execute cleanup commands
```

## 🔍 Troubleshooting

### Common Issues and Solutions

#### 1. Bot Not Responding
```bash
# Check Lambda logs
aws logs tail /aws/lambda/your-function --follow

# Verify environment variables
aws lambda get-function-configuration --function-name your-function

# Test direct invocation
aws lambda invoke --function-name your-function --payload '{"test": true}' response.json
```

#### 2. Slack Verification Failures
- Verify `SLACK_SIGNING_SECRET` is correct
- Check timestamp tolerance (5 minutes)
- Ensure Lambda clock is synchronized

#### 3. SSM Commands Failing
```bash
# Check SSM agent status
aws ssm describe-instance-information --filters "Key=InstanceIds,Values=i-123"

# Verify IAM role has SSM permissions
aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::account:role/role-name
```

<!-- Developed by Arunbh
08/21/26 -->

#### 4. DynamoDB Errors
- Check table exists and is active
- Verify Lambda has DynamoDB permissions
- Monitor throttling metrics

#### 5. Timeout Issues
- Lambda configured for async processing
- Check self-invocation permissions
- Monitor Lambda concurrent executions

### Debug Mode

Enable debug logging by setting:
```python
logger.setLevel(logging.DEBUG)
```

### Performance Monitoring

```bash
# Check Lambda metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=your-function \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Average,Maximum
```

## 🔒 Security

### Security Best Practices

1. **Slack Verification**: All requests verified using signing secret
2. **IAM Least Privilege**: Minimal required permissions
3. **Secrets Management**: Use AWS Secrets Manager for sensitive data
4. **VPC Configuration**: Deploy Lambda in VPC for network isolation
5. **Audit Logging**: All actions logged to CloudWatch
6. **Rate Limiting**: Built-in rate limiting for API calls

### Data Encryption

- **At Rest**: DynamoDB encryption enabled
- **In Transit**: TLS for all API calls
- **Conversation History**: Encrypted in DynamoDB

### Compliance Considerations

- PII handling in conversation history
- Log retention policies
- Access control for sensitive operations
- Audit trail requirements

## 📚 API Reference

### Event Formats

#### Slack App Mention
```json
{
  "type": "event_callback",
  "event": {
    "type": "app_mention",
    "text": "<@BOT_ID> check instance i-123",
    "channel": "C1234567890",
    "user": "U1234567890",
    "ts": "1234567890.123456"
  }
}
```

#### EventBridge Patch Event
```json
{
  "source": "aws.ssm",
  "detail-type": "Maintenance Window Execution State-change Notification",
  "detail": {
    "window-id": "mw-1234567890abcdef0",
    "status": "SUCCESS"
  }
}
```

### Response Formats

#### Successful Query Response
```json
{
  "response": "Formatted Slack message",
  "tool_calls": [
    {
      "tool_name": "list_ec2_instances",
      "inputs": {"region": "us-east-1"},
      "result": "..."
    }
  ],
  "processing_time_seconds": 2.5,
  "iterations": 3,
  "context": {
    "instance_id": "i-1234567890abcdef0",
    "issue_types": ["high_cpu"]
  }
}
```

## 🤝 Contributing

### Development Setup

1. Clone the repository
2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up local environment:
```bash
export SLACK_BOT_TOKEN=xoxb-test-token
export AWS_PROFILE=development
```

4. Run tests:
```bash
python -m pytest tests/
```

### Code Style

- Follow PEP 8
- Use type hints
- Add docstrings to all functions
- Maximum line length: 120 characters





<!-- ## 🔄 Version History -->
