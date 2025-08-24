# AWS Operations Assistant for Slack

## 📋 Table of Contents
- [Overview](#overview)
- [Problem Statement](#problem-statement)
- [Architecture](#architecture)
- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Tools and Capabilities](#tools-and-capabilities)
- [Troubleshooting](#troubleshooting)
- [Security](#security)
- [API Reference](#api-reference)

## 🎯 Overview

Claude 3.5 Sonnet-powered Slack bot that automates AWS patching verification and serves as an intelligent first responder for on-call engineers. Monitors SSM Maintenance Windows, analyzes failures, and provides actionable remediation steps directly in Slack.

## 📌 Problem Statement

### Problem 1: Manual Patching Verification
- **Current**: Engineers manually check SSM Maintenance Window results and post updates to Slack
- **Solution**: Automated detection and notification of patching completion/failure

### Problem 2: Reactive On-Call Support  
- **Current**: Manual investigation of connectivity issues and failures during off-hours
- **Solution**: AI-powered first responder that analyzes issues and provides remediation steps

## 🏗 Architecture

```mermaid
graph TB
    subgraph "Event Sources"
        A[SSM Maintenance Windows]
        B[Slack @mentions]
        C[EventBridge Rules]
        D[CloudWatch Alarms]
    end
    
    subgraph "Lambda Function"
        E[Event Router]
        F[Slack Verification]
        G[Context Manager]
        H[Claude 3.5 LLM]
        I[Tool Executor]
        J[AWS Service APIs]
    end
    
    subgraph "AWS Services"
        K[EC2]
        L[Systems Manager]
        M[CloudWatch]
        N[RDS]
        O[S3]
    end
    
    subgraph "Storage"
        P[DynamoDB - Conversations]
        Q[DynamoDB - Context]
    end
    
    subgraph "Output"
        R[Slack Streaming Handler]
        S[Slack Channels]
    end
    
    A --> E
    B --> E
    C --> E
    D --> E
    
    E --> F
    F --> G
    G --> H
    H --> I
    I --> J
    
    J --> K
    J --> L
    J --> M
    J --> N
    J --> O
    
    G --> P
    G --> Q
    
    I --> R
    R --> S
```

## ✨ Features

### Implemented Capabilities
- ✅ **Automated Patching Notifications** - SSM Maintenance Window monitoring
- ✅ **Intelligent Failure Analysis** - LLM-powered root cause analysis
- ✅ **Real-time Slack Streaming** - Rate-limited message updates
- ✅ **Context-Aware Conversations** - Maintains conversation state
- ✅ **AWS Multi-Service Integration** - EC2, SSM, CloudWatch, RDS, S3
- ✅ **Async Processing** - Handles long-running operations

## 🚀 Installation

### Step 1: Create Slack App

```
Bot Token Scopes:
- app_mentions:read
- channels:history
- chat:write
- commands
```

```
Event Subscriptions:
- app_mention
- message.channels
```

### Step 2: Deploy Lambda

```bash
Runtime: Python 3.12
Memory: 3008 MB
Timeout: 900 seconds
```

### Step 3: Environment Variables

```bash
SLACK_BOT_TOKEN=xoxb-your-token
SLACK_SIGNING_SECRET=your-secret
SLACK_ALERT_CHANNEL=#alerts
SLACK_PATCH_CHANNEL=#patches
DYNAMODB_TABLE_NAME=oncalltable
AWS_DEFAULT_REGION=us-east-1
```

### Step 4: IAM Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "ec2:*",
        "ssm:*",
        "cloudwatch:*",
        "logs:*",
        "rds:Describe*",
        "s3:List*",
        "dynamodb:*",
        "lambda:InvokeFunction"
      ],
      "Resource": "*"
    }
  ]
}
```

### Step 5: EventBridge Rule (For Automated Patching)

```json
{
  "source": "aws.ssm",
  "detail-type": "Maintenance Window Execution State-change Notification"
}
```

## ⚙️ Configuration

### DynamoDB Tables (Auto-created)
- `oncalltable` - Conversation history
- `oncalltable_context` - Context storage

### Slack Channels
- `#patches` - Patching notifications
- `#alerts` - Critical alerts
- `#oncall-support` - General queries

## 📖 Usage

### Automated Patching Notifications
```
Bot: ✅ SAS Prod patching completed
     Instances: 12/12 successful
     Duration: 45 minutes
```

### Natural Language Queries
```
@AWSBot check patch status for prod
@AWSBot why did patching fail on i-1234567890
@AWSBot show high CPU instances
@AWSBot run yum update on staging servers
@AWSBot investigate connectivity issues on i-abc123
```

### Context-Aware Conversations
```
User: @AWSBot check i-1234567890abcdef0
Bot: [Instance details]

User: what's its CPU usage?
Bot: [Shows CPU metrics for same instance]
```

## 🛠 Tools and Capabilities

### Patch Management
- `check_patch_status` - Compliance checking
- `apply_patches` - Apply missing patches
- `diagnose_patch_failures` - Failure analysis
- `get_patch_history` - Historical data

### EC2 Operations
- `list_ec2_instances` - List instances
- `health_check_ec2_instance` - Health checks
- `start/stop_ec2_instance` - Instance control

### SSM Operations  
- `run_ssm_command` - Remote execution
- `check_ssm_connectivity` - Agent status
- `get_instance_system_info` - System details

### Monitoring
- `get_alarms_in_alarm_state` - Active alarms
- `get_ec2_cpu_metrics` - Performance metrics
- `search_cloudwatch_logs` - Log analysis

## 🔍 Troubleshooting

### Bot Not Responding
```bash
aws logs tail /aws/lambda/your-function --follow
```

### SSM Commands Failing
```bash
aws ssm describe-instance-information --filters "Key=InstanceIds,Values=i-123"
```

### Debug Mode
```python
logger.setLevel(logging.DEBUG)
```

## 🔒 Security

- Slack signature verification
- IAM least-privilege permissions  
- DynamoDB encryption
- No sensitive data in logs

## 📚 API Reference

### Slack Event
```json
{
  "type": "event_callback",
  "event": {
    "type": "app_mention",
    "text": "<@BOT_ID> check instance i-123"
  }
}
```

### EventBridge Patch Event
```json
{
  "source": "aws.ssm",
  "detail-type": "Maintenance Window Execution State-change",
  "detail": {
    "window-id": "mw-123",
    "status": "SUCCESS"
  }
}
```

---

**Built with:** Python 3.12, Claude 3.5 Sonnet, AWS SDK, Slack API