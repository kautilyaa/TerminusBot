# DynamoDB Infrastructure for Terminal MCP

This folder contains the AWS DynamoDB infrastructure and related components for the Terminal MCP chat system.

## Overview

The DynamoDB setup consists of two main tables:
- **oncall-instances**: Stores chat instance metadata and configuration
- **oncall-messages**: Stores individual chat messages with conversation history

## Table Structure

### oncall-instances Table

**Primary Key**: `instance_id` (String)

**Attributes**:
- `instance_id` (String, Hash Key): Unique identifier for each chat instance
- `system_prompt` (String): System prompt for the conversation
- `created_at` (String): ISO timestamp when instance was created
- `updated_at` (String): ISO timestamp when instance was last updated
- `message_count` (Number): Total number of messages in the conversation
- `status` (String): Instance status ('active', 'inactive', 'archived')
- `ttl` (Number): Time-to-live timestamp for automatic cleanup
- `metadata` (Map): Additional metadata including model_id and platform

**Global Secondary Indexes**:
- `StatusIndex`: Query instances by status and updated_at
  - Hash Key: `status`
  - Range Key: `updated_at`

### oncall-messages Table

**Primary Key**: 
- `instance_id` (String, Hash Key): References the instance
- `message_id` (String, Range Key): Unique identifier for each message

**Attributes**:
- `instance_id` (String, Hash Key): Reference to the chat instance
- `message_id` (String, Range Key): Unique identifier for the message
- `role` (String): Message role ('user' or 'assistant')
- `content` (String): Message content
- `timestamp` (String): ISO timestamp when message was created
- `message_order` (Number): Sequential order of messages in conversation
- `model` (String, optional): Model ID used for assistant messages
- `ttl` (Number): Time-to-live timestamp for automatic cleanup

**Global Secondary Indexes**:
- `MessageOrderIndex`: Query messages by instance and order
  - Hash Key: `instance_id`
  - Range Key: `message_order`
- `TimestampIndex`: Query messages by instance and timestamp
  - Hash Key: `instance_id`
  - Range Key: `timestamp`

## Deployment

### Prerequisites

1. AWS CLI configured with appropriate credentials
2. AWS SAM CLI installed
3. Python 3.12+ environment

### Deploy Infrastructure

1. **Deploy DynamoDB Tables**:
   ```bash
   cd DynamoDB
   aws cloudformation deploy \
     --template-file template.yaml \
     --stack-name terminal-mcp-dynamodb \
     --capabilities CAPABILITY_IAM \
     --region us-east-1
   ```

2. **Verify Deployment**:
   ```bash
   aws cloudformation describe-stacks \
     --stack-name terminal-mcp-dynamodb \
     --region us-east-1
   ```

### Environment Variables

The Lambda function expects these environment variables:
- `INSTANCES_TABLE`: Name of the instances table (auto-set by CloudFormation)
- `MESSAGES_TABLE`: Name of the messages table (auto-set by CloudFormation)

## Usage

### Using the DynamoDB Client

The `client/dynamodb_client.py` provides a Python interface for interacting with the tables:

```python
from dynamodb_client import DynamoDBClient

# Initialize client
client = DynamoDBClient(region_name='us-east-1')

# Create a new instance
result = client.create_instance(
    instance_id='my-chat-123',
    system_prompt='You are a helpful assistant'
)

# Add a user message
result = client.add_message(
    instance_id='my-chat-123',
    role='user',
    content='Hello, how are you?'
)

# Get conversation history
messages = client.get_conversation_history('my-chat-123')

# Get instance statistics
stats = client.get_instance_stats('my-chat-123')
```

### Using the CLI Tool

The `client/dynamodb_cli.py` provides a command-line interface:

```bash
# Create a new instance
python dynamodb_cli.py create-instance my-chat-123 --system-prompt "You are a helpful assistant"

# List all active instances
python dynamodb_cli.py list-instances

# Add a user message
python dynamodb_cli.py add-message my-chat-123 user "Hello, how are you?"

# Get conversation history
python dynamodb_cli.py get-history my-chat-123

# Get instance statistics
python dynamodb_cli.py get-stats my-chat-123

# Delete an instance
python dynamodb_cli.py delete-instance my-chat-123
```

## Data Lifecycle

### TTL (Time-to-Live)

Both tables have TTL enabled with a 30-day expiration:
- Instances and messages are automatically deleted after 30 days
- TTL is refreshed on each update operation
- This helps manage storage costs and data retention

### Status Management

Instances can have the following statuses:
- `active`: Currently in use
- `inactive`: Temporarily disabled
- `archived`: Permanently archived

## Security

### IAM Permissions

The Lambda function requires these permissions:
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:DeleteItem`
- `dynamodb:Query`, `dynamodb:Scan`
- `bedrock:InvokeModel`

### Encryption

- Tables use AWS managed encryption at rest
- All data is encrypted in transit using TLS

## Monitoring and Logging

### CloudWatch Metrics

Key metrics to monitor:
- `ConsumedReadCapacityUnits`
- `ConsumedWriteCapacityUnits`
- `ThrottledRequests`
- `UserErrors`

### CloudWatch Logs

Lambda function logs include:
- Instance creation/deletion events
- Message processing events
- Error handling and debugging information

## Cost Optimization

### Billing Mode

Tables use **PAY_PER_REQUEST** billing mode:
- Pay only for actual read/write operations
- No provisioned capacity management required
- Suitable for variable workloads

### Cost Monitoring

Monitor costs through:
- AWS Cost Explorer
- CloudWatch Billing metrics
- DynamoDB CloudWatch metrics

## Backup and Recovery

### Point-in-Time Recovery

Consider enabling point-in-time recovery for production tables:
```bash
aws dynamodb update-continuous-backups \
  --table-name oncall-instances \
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true
```

### Cross-Region Replication

For disaster recovery, consider setting up cross-region replication:
```bash
aws dynamodb create-global-table \
  --global-table-name oncall-instances \
  --replication-group RegionName=us-east-1
```

## Troubleshooting

### Common Issues

1. **Table Not Found**: Ensure tables are deployed in the correct region
2. **Permission Denied**: Check IAM roles and policies
3. **TTL Not Working**: Verify TTL attribute is properly set
4. **High Latency**: Monitor CloudWatch metrics for throttling

### Debug Commands

```bash
# Check table status
aws dynamodb describe-table --table-name oncall-instances

# Check table metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/DynamoDB \
  --metric-name ConsumedReadCapacityUnits \
  --dimensions Name=TableName,Value=oncall-instances \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Sum
```

## Development

### Local Development

For local development, consider using DynamoDB Local:
```bash
docker run -p 8000:8000 amazon/dynamodb-local
```

Update the client to use local endpoint:
```python
client = DynamoDBClient(endpoint_url='http://localhost:8000')
```

### Testing

Run tests with the provided test scripts:
```bash
python -m pytest tests/ -v
```

## Support

For issues and questions:
1. Check CloudWatch logs for error details
2. Review AWS DynamoDB documentation
3. Monitor CloudWatch metrics for performance issues
4. Contact the development team for complex issues 