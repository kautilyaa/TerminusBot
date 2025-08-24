# AWS MCP Lambda - Slack Operations Bot

## 🌟 Overview

AWS MCP Lambda is a comprehensive, AI-powered Slack bot that provides intelligent AWS operations management through natural language interactions. Built on AWS Lambda and powered by Claude 3.5 Sonnet, it enables DevOps teams to manage AWS infrastructure, monitor systems, handle alerts, and maintain patch compliance directly from Slack.

## 📋 Table of Contents

- [Key Features](#-key-features)
- [Architecture](#-architecture)
- [Prerequisites](#-prerequisites)
- [Installation & Setup](#-installation--setup)
- [Configuration](#-configuration)
- [Usage Guide](#-usage-guide)
- [Available Commands](#-available-commands)
- [Tool Capabilities](#-tool-capabilities)
- [Alert Processing](#-alert-processing)
- [Patch Management](#-patch-management)
- [Context Management](#-context-management)
- [Troubleshooting](#-troubleshooting)
- [Security Considerations](#-security-considerations)
- [Contributing](#-contributing)
- [License](#-license)

## 🚀 Key Features

### Core Capabilities

- **🤖 AI-Powered Operations**: Natural language processing for AWS management tasks
- **💬 Slack Integration**: Seamless interaction through mentions, slash commands, and automated alerts
- **🔄 Context Awareness**: Maintains conversation history and context across interactions
- **⚡ Async Processing**: Handles long-running operations without timing out
- **🎯 Multi-Service Support**: EC2, RDS, S3, CloudWatch, SSM, and more
- **📊 Intelligent Monitoring**: Proactive alerts and comprehensive health checks
- **🔧 Patch Management**: Automated patch compliance tracking and remediation
- **📈 Performance Analytics**: Real-time metrics and trend analysis

### Unique Features

- **Smart Alert Correlation**: Links related alerts and maintains investigation context
- **Auto-Remediation**: Suggests and executes fixes for common issues
- **Environment-Aware**: Groups resources by environment (prod/staging/dev)
- **Compliance Reporting**: Automated weekly patch and security compliance audits
- **Visual Formatting**: Rich Slack formatting with emojis and structured reports

## 🏗 Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│                 │────▶│              │────▶│                 │
│   Slack Users   │     │  API Gateway │     │  Lambda Function│
│                 │◀────│              │◀────│                 │
└─────────────────┘     └──────────────┘     └────────┬────────┘
                                                       │
                            ┌──────────────────────────┼──────────────────────────┐
                            │                          │                          │
                      ┌─────▼──────┐         ┌────────▼────────┐          ┌──────▼──────┐
                      │            │         │                 │          │             │
                      │  DynamoDB  │         │ Bedrock Claude  │          │   AWS APIs  │
                      │  (Context) │         │   3.5 Sonnet    │          │  (EC2, SSM) │
                      │            │         │                 │          │             │
                      └────────────┘         └─────────────────┘          └─────────────┘
                                                       │
                            ┌──────────────────────────┼──────────────────────────┐
                            │                          │                          │
                      ┌─────▼──────┐         ┌────────▼────────┐          ┌──────▼──────┐
                      │            │         │                 │          │             │
                      │EventBridge │         │     SNS         │          │ CloudWatch  │
                      │  (Events)  │         │   (Alerts)      │          │   (Logs)    │
                      │            │         │                 │          │             │
                      └────────────┘         └─────────────────┘          └─────────────┘
```

### Components

- **Lambda Function**: Core processing engine with async invocation support
- **API Gateway**: Handles Slack webhook requests
- **DynamoDB**: Stores conversation history and context
- **Bedrock**: Provides Claude 3.5 Sonnet AI model
- **EventBridge**: Triggers scheduled tasks and processes AWS events
- **CloudWatch**: Logging and monitoring
- **SNS**: Alert distribution

## 📦 Prerequisites

### AWS Requirements

- AWS Account with appropriate permissions
- AWS CLI configured
- Lambda execution role with required policies
- Bedrock access enabled in us-east-1

### Slack Requirements

- Slack workspace with admin access
- Slack App with:
  - Bot Token Scopes: `app_mentions:read`, `chat:write`, `commands`
  - Event Subscriptions enabled
  - Slash commands configured

### Required Python Packages

```python
boto3>=1.26.0
botocore>=1.29.0
requests>=2.28.0
urllib3>=1.26.0
langchain-core>=0.1.0
langchain-community>=0.1.0
```

## 🛠 Installation & Setup

### 1. Clone Repository

```bash
git clone https://github.com/your-org/aws-mcp-lambda.git
cd aws-mcp-lambda
```

### 2. Create Lambda Function

```bash
# Create deployment package
zip -r lambda-deployment.zip *.py requirements.txt

# Create Lambda function
aws lambda create-function \
  --function-name aws-mcp-slack-bot \
  --runtime python3.11 \
  --role arn:aws:iam::YOUR_ACCOUNT:role/lambda-execution-role \
  --handler lambda_function.lambda_handler \
  --timeout 900 \
  --memory-size 1024 \
  --environment Variables={
    SLACK_BOT_TOKEN=xoxb-your-token,
    SLACK_SIGNING_SECRET=your-secret,
    DYNAMODB_TABLE_NAME=oncalltable,
    SLACK_ALERT_CHANNEL=#alerts,
    SLACK_PATCH_CHANNEL=#patches
  } \
  --zip-file fileb://lambda-deployment.zip
```

### 3. Configure API Gateway

```bash
# Create REST API
aws apigateway create-rest-api \
  --name aws-mcp-slack-bot-api \
  --endpoint-configuration types=REGIONAL

# Configure resources and methods for Slack endpoints
# (Detailed commands depend on your specific setup)
```

### 4. Setup DynamoDB Tables

```python
# Tables are auto-created by the Lambda, but you can pre-create them:

# Conversation history table
aws dynamodb create-table \
  --table-name oncalltable \
  --attribute-definitions AttributeName=SessionId,AttributeType=S \
  --key-schema AttributeName=SessionId,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

# Context table
aws dynamodb create-table \
  --table-name oncalltable_context \
  --attribute-definitions AttributeName=SessionId,AttributeType=S \
  --key-schema AttributeName=SessionId,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

### 5. Configure Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Create new app or select existing
3. Configure OAuth & Permissions:
   - Bot Token Scopes: `app_mentions:read`, `chat:write`, `commands`, `chat:write.public`
4. Enable Event Subscriptions:
   - Request URL: `https://your-api-gateway-url/slack/events`
   - Subscribe to bot events: `app_mention`
5. Create Slash Commands:
   - `/aws` - Main AWS query command
   - `/aws_help` - Show help
   - `/bot_status` - Check bot status
6. Install app to workspace

### 6. Setup IAM Role

Create an IAM role with the following policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "ec2:Describe*",
        "ec2:Start*",
        "ec2:Stop*",
        "ec2:RebootInstances",
        "ssm:*",
        "s3:List*",
        "s3:Get*",
        "s3:CreateBucket",
        "rds:Describe*",
        "cloudwatch:*",
        "logs:*",
        "dynamodb:*",
        "lambda:InvokeFunction",
        "sns:Publish",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `SLACK_BOT_TOKEN` | Slack bot OAuth token | Yes | - |
| `SLACK_SIGNING_SECRET` | Slack app signing secret | Yes | - |
| `DYNAMODB_TABLE_NAME` | Main conversation history table | No | `oncalltable` |
| `DYNAMODB_TABLE_NAME_CONTEXT` | Context storage table | No | `{table_name}_context` |
| `SLACK_ALERT_CHANNEL` | Default channel for alerts | No | `#alerts` |
| `SLACK_PATCH_CHANNEL` | Channel for patch reports | No | `#patches` |
| `SLACK_CRITICAL_CHANNEL` | Channel for critical alerts | No | Same as alert channel |
| `AWS_DEFAULT_REGION` | Default AWS region | No | `us-east-1` |
| `NOTIFY_ALL_PATCHES` | Notify on all patch operations | No | `false` |

### EventBridge Rules

Create EventBridge rules for automated tasks:

```bash
# Weekly patch compliance check
aws events put-rule \
  --name weekly-patch-check \
  --schedule-expression "cron(0 9 ? * MON *)" \
  --description "Weekly patch compliance audit"

# Maintenance window monitoring
aws events put-rule \
  --name maintenance-window-monitor \
  --event-pattern '{
    "source": ["aws.ssm"],
    "detail-type": ["Maintenance Window Execution State-change Notification"]
  }'
```

## 📚 Usage Guide

### Basic Interaction

#### 1. Mention the Bot

```
@bot check the status of instance i-1234567890abcdef0
@bot list all running EC2 instances in us-west-2
@bot show me CPU metrics for the last 24 hours
```

#### 2. Slash Commands

```
/aws list all EC2 instances
/aws check health of instance i-1234567890abcdef0
/aws_help
/bot_status
```

#### 3. Context-Aware Conversations

The bot maintains context throughout conversations:

```
User: @bot check instance i-1234567890abcdef0
Bot: [Shows instance details]
User: @bot show me its CPU metrics
Bot: [Shows metrics for i-1234567890abcdef0 - remembers context]
```

### Advanced Operations

#### Investigating Issues

```
@bot investigate high CPU on instance i-1234567890abcdef0
@bot check recent errors in application logs
@bot diagnose network connectivity issues
```

#### Remote Command Execution

```
@bot run command "df -h" on instance i-1234567890abcdef0
@bot check disk usage on all production instances
@bot restart apache on web-server-1
```

## 🛠 Available Commands

### Help Commands

| Command | Description |
|---------|-------------|
| `/aws_help` | Display comprehensive help |
| `/bot_status` | Check bot and service status |
| `/test` | Quick connectivity test |

### Context Management

| Command | Description | Example |
|---------|-------------|---------|
| `/show_context` | Display current conversation context | `/show_context` |
| `/set_context` | Manually set context parameters | `/set_context instance_id=i-1234 issue_types=high_cpu` |
| `/clear_context` | Clear context (keep history) | `/clear_context` |
| `/clear_memory` | Clear entire conversation history | `/clear_memory` |

### Alert Management

| Command | Description | Example |
|---------|-------------|---------|
| `/last_alert` | Show the last alert in channel | `/last_alert` |
| `/show_alert` | Display specific alert details | `/show_alert alert_C1234_i-abc123` |
| `/list_alerts` | List recent alerts | `/list_alerts` |

## 🔧 Tool Capabilities

### EC2 Management

- List, start, stop instances
- Get detailed instance information
- Find instances by name tag
- Health checks and diagnostics
- Remote command execution via SSM

### CloudWatch Operations

- **Alarms**: List, monitor, set alarm states
- **Metrics**: Retrieve and analyze performance data
- **Logs**: Search, filter, and analyze log data
- **Dashboards**: Access dashboard configurations

### SSM Operations

- Execute remote commands
- Check patch compliance
- Manage maintenance windows
- System information gathering
- Multi-instance operations

### Patch Management

- Compliance monitoring
- Automated patch verification
- Remediation planning
- Failed patch diagnostics
- Maintenance window tracking

### S3 Operations

- List buckets and objects
- Create new buckets
- Regional configuration

### RDS Management

- List database instances
- Monitor database performance
- Configuration details

## 🚨 Alert Processing

### Automated Alert Handling

The bot automatically processes alerts from external monitoring systems:

1. **Alert Reception**: Receives alerts via EventBridge or direct invocation
2. **Context Extraction**: Identifies instance IDs, metrics, and issue types
3. **Investigation**: Automatically checks instance health, metrics, and logs
4. **Analysis**: Provides detailed analysis with recommendations
5. **Context Storage**: Stores alert context for follow-up investigations

### Alert Correlation

```
Alert received -> Extract instance ID -> Create alert session -> Store context
                                                                      ↓
User query with instance ID <- Reference previous alerts <- Retrieve context
```

### Example Alert Flow

```
System: 🔔 Automated Alert Received
        Alert ID: alert_C1234_i-abc123
        Instance: i-abc123
        Processing disk space alert...

System: [Detailed analysis with metrics and recommendations]

User: @bot check the alert alert_C1234_i-abc123
Bot: [Retrieves stored context and continues investigation]
```

## 🔐 Patch Management

### Automated Patch Compliance

#### Weekly Audits

Automatically generated reports include:
- Compliance percentages by environment
- Non-compliant instance lists
- Critical security patches missing
- Failed patch details with remediation
- Instances pending reboot

#### Maintenance Window Monitoring

```
Window Execution → Automatic Verification → Detailed Report → Slack Notification
                                                ↓
                                    Context Storage for Follow-up
```

### Patch Commands

```
# Check compliance
@bot check patch compliance for all production instances

# Apply patches
@bot apply critical security patches to non-compliant instances

# Generate remediation plan
@bot create patch remediation plan for failed instances

# Schedule maintenance
@bot schedule patch maintenance window for staging environment
```

## 🧠 Context Management

### How Context Works

1. **Automatic Extraction**: Identifies instance IDs, issue types, and metrics
2. **Session Management**: Maintains context per conversation thread
3. **Alert Correlation**: Links alerts to investigations
4. **Persistence**: Stores in DynamoDB for continuity

### Context Types

#### Conversation Context
```python
{
    'instance_id': 'i-1234567890abcdef0',
    'instance_type': 't2.micro',
    'issue_types': ['high_cpu', 'memory'],
    'last_updated': '2024-01-01T12:00:00'
}
```

#### Alert Context
```python
{
    'alert_id': 'alert_C1234_i-abc123',
    'instance_id': 'i-abc123',
    'alert_type': 'disk_space',
    'disk_usage': '95',
    'alert_time': '2024-01-01T12:00:00'
}
```

## 🐛 Troubleshooting

### Common Issues

#### Bot Not Responding

1. Check CloudWatch logs:
```bash
aws logs tail /aws/lambda/aws-mcp-slack-bot --follow
```

2. Verify Slack tokens:
```bash
aws lambda get-function-configuration --function-name aws-mcp-slack-bot
```

3. Test Lambda directly:
```bash
aws lambda invoke --function-name aws-mcp-slack-bot \
  --payload '{"query": "list EC2 instances"}' \
  response.json
```

#### Timeout Issues

- Increase Lambda timeout (max 900 seconds)
- Check async processing is working
- Verify self-invocation permissions

#### Permission Errors

- Review IAM role policies
- Check Bedrock access in us-east-1
- Verify DynamoDB table permissions

### Debug Mode

Enable detailed logging:
```python
logger.setLevel(logging.DEBUG)
```

### Performance Optimization

1. **Memory Allocation**: Increase Lambda memory for faster processing
2. **Concurrent Executions**: Set appropriate limits
3. **DynamoDB**: Use on-demand billing for variable workloads
4. **Caching**: Implement caching for frequently accessed data

## 🔒 Security Considerations

### Best Practices

1. **Secrets Management**: Use AWS Secrets Manager for tokens
2. **Least Privilege**: Limit IAM permissions to minimum required
3. **Network Security**: Use VPC endpoints for AWS services
4. **Audit Logging**: Enable CloudTrail for all API calls
5. **Encryption**: Enable encryption at rest for DynamoDB
6. **Request Validation**: Always verify Slack signatures

### Compliance

- **Data Retention**: Configure DynamoDB TTL for conversation history
- **Access Control**: Implement Slack user/channel restrictions
- **Sensitive Data**: Avoid logging sensitive information
- **Regional Compliance**: Ensure data residency requirements

## 🤝 Contributing

### Development Setup

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

### Code Style

- Follow PEP 8 guidelines
- Add docstrings to all functions
- Include type hints where applicable
- Write comprehensive error handling

### Testing

```bash
# Run unit tests
python -m pytest tests/

# Run integration tests
python -m pytest tests/integration/

# Check code coverage
python -m pytest --cov=lambda_function tests/
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 📞 Support

- **Documentation**: [Full API Documentation](docs/api.md)
- **Issues**: [GitHub Issues](https://github.com/your-org/aws-mcp-lambda/issues)
- **Slack Channel**: #aws-bot-support
- **Email**: devops-team@your-company.com

## 🙏 Acknowledgments

- Claude 3.5 Sonnet by Anthropic
- AWS SDK for Python (Boto3)
- LangChain for conversation management
- Slack API team

---

**Last Updated**: December 2024
**Version**: 1.0.0
**Maintainers**: DevOps Team