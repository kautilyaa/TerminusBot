# Terminal MCP Client

This folder contains the client-side components for the Terminal MCP (Model Context Protocol) system, including DynamoDB integration for chat persistence and management.

## Overview

The client provides multiple interfaces for interacting with the Terminal MCP system:

- **Main MCP Client** (`client.py`): Interactive terminal client with MCP server integration
- **DynamoDB Client** (`dynamodb_client.py`): Python library for DynamoDB operations
- **DynamoDB CLI** (`dynamodb_cli.py`): Command-line interface for DynamoDB management
- **Test Suite** (`test_dynamodb.py`): Comprehensive testing for DynamoDB functionality
- **Batch Client** (`batch_client.py`): Batch processing capabilities
- **Chat Handler** (`chat_handler.py`): Lambda function for chat processing

## Prerequisites

### 1. Python Environment
```bash
# Python 3.12+ required
python --version

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. AWS Configuration
```bash
# Configure AWS CLI
aws configure

# Set your AWS credentials and region
# AWS Access Key ID: [your-access-key]
# AWS Secret Access Key: [your-secret-key]
# Default region name: us-east-1
# Default output format: json
```

### 4. DynamoDB Infrastructure
```bash
# Deploy DynamoDB tables (if not already deployed)
cd ../DynamoDB
./deploy.sh
cd ../client
```

## Quick Start

### 1. Start the MCP Server
First, start the Terminal MCP server in a separate terminal:

```bash
# From the project root
cd src/terminal_mcp
python server.py
```

The server will start on `http://localhost:8080` by default.

### 2. Run the Main Client
```bash
# Connect to the MCP server
python client.py http://localhost:8080/sse
```

## Detailed Usage

### Main MCP Client (`client.py`)

The main client provides an interactive terminal interface with AI-powered assistance.

#### Features:
- Execute terminal commands through AI
- File reading and writing
- System information retrieval
- Directory navigation
- Context-aware assistance

#### Usage:
```bash
# Basic usage
python client.py <server-url>

# Examples
python client.py http://localhost:8080/sse
python client.py http://192.168.1.100:8080/sse
```

#### Interactive Commands:
```
Query: list files in current directory
Query: create a new file called test.txt
Query: show me the system information
Query: navigate to /tmp directory
Query: quit
```

### DynamoDB Client (`dynamodb_client.py`)

Python library for managing chat instances and messages in DynamoDB.

#### Basic Usage:
```python
from dynamodb_client import DynamoDBClient

# Initialize client
client = DynamoDBClient(region_name='us-east-1')

# Create a new chat instance
result = client.create_instance(
    instance_id='my-chat-123',
    system_prompt='You are a helpful assistant'
)

# Add messages
client.add_message('my-chat-123', 'user', 'Hello!')
client.add_message('my-chat-123', 'assistant', 'Hi there!', model_id='claude-opus')

# Get conversation history
messages = client.get_conversation_history('my-chat-123')

# Get statistics
stats = client.get_instance_stats('my-chat-123')
```

### DynamoDB CLI (`dynamodb_cli.py`)

Command-line interface for DynamoDB operations.

#### Available Commands:

```bash
# Create a new instance
python dynamodb_cli.py create-instance my-chat-123 --system-prompt "You are helpful"

# List all active instances
python dynamodb_cli.py list-instances

# Add a user message
python dynamodb_cli.py add-message my-chat-123 user "Hello, how are you?"

# Add an assistant message
python dynamodb_cli.py add-message my-chat-123 assistant "I'm doing well, thank you!" --model-id claude-opus

# Get conversation history
python dynamodb_cli.py get-history my-chat-123

# Get instance statistics
python dynamodb_cli.py get-stats my-chat-123

# Update instance status
python dynamodb_cli.py update-status my-chat-123 inactive

# Delete an instance
python dynamodb_cli.py delete-instance my-chat-123

# Get help
python dynamodb_cli.py --help
```

#### CLI Options:
```bash
--region REGION     AWS region (default: us-east-1)
--pretty           Pretty print JSON output
```

### Test Suite (`test_dynamodb.py`)

Comprehensive test suite for DynamoDB functionality.

#### Run Tests:
```bash
# Run full test suite
python test_dynamodb.py
```

#### What it Tests:
- Instance creation and management
- Message addition and retrieval
- Conversation history
- Statistics calculation
- Status updates
- Cleanup operations

### Batch Client (`batch_client.py`)

For processing multiple operations in batch.

#### Usage:
```python
from batch_client import BatchClient

# Initialize batch client
batch = BatchClient()

# Process multiple operations
operations = [
    {'type': 'create_instance', 'instance_id': 'batch-1', 'system_prompt': 'Assistant 1'},
    {'type': 'create_instance', 'instance_id': 'batch-2', 'system_prompt': 'Assistant 2'},
    {'type': 'add_message', 'instance_id': 'batch-1', 'role': 'user', 'content': 'Hello'},
]

results = batch.process_operations(operations)
```

### Chat Handler (`chat_handler.py`)

Lambda function for processing chat interactions.

#### Local Testing:
```bash
# Test the chat handler locally
python chat_handler.py
```

#### Lambda Deployment:
```bash
# Deploy to AWS Lambda
cd ../lambda
./deploy.sh
```

## Integration Examples

### 1. MCP + DynamoDB Integration

Create a chat session that persists to DynamoDB:

```python
import asyncio
from client import TerminalMCPClient
from dynamodb_client import DynamoDBClient

async def integrated_chat():
    # Initialize clients
    mcp_client = TerminalMCPClient()
    db_client = DynamoDBClient()
    
    # Create chat instance
    instance_id = f"mcp-session-{int(time.time())}"
    db_client.create_instance(instance_id, "You are a helpful terminal assistant")
    
    # Connect to MCP server
    await mcp_client.connect_to_server("http://localhost:8080/sse")
    
    # Start chat loop with persistence
    while True:
        query = input("Query: ")
        if query.lower() == 'quit':
            break
            
        # Store user message
        db_client.add_message(instance_id, 'user', query)
        
        # Get AI response
        response = await mcp_client.process_query(query)
        
        # Store assistant response
        db_client.add_message(instance_id, 'assistant', response)
        
        print(f"Assistant: {response}")
    
    await mcp_client.cleanup()

# Run the integrated chat
asyncio.run(integrated_chat())
```

### 2. Automated Testing with MCP

```python
import asyncio
from client import TerminalMCPClient
from test_dynamodb import test_dynamodb_client

async def test_mcp_integration():
    # Test DynamoDB functionality
    test_dynamodb_client()
    
    # Test MCP client
    mcp_client = TerminalMCPClient()
    await mcp_client.connect_to_server("http://localhost:8080/sse")
    
    # Test basic query
    response = await mcp_client.process_query("echo 'Hello MCP'")
    print(f"MCP Response: {response}")
    
    await mcp_client.cleanup()

asyncio.run(test_mcp_integration())
```

## Configuration

### Environment Variables

Create a `.env` file in the client directory:

```env
# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key

# MCP Server Configuration
MCP_SERVER_URL=http://localhost:8080/sse

# DynamoDB Configuration
DYNAMODB_INSTANCES_TABLE=oncall-instances
DYNAMODB_MESSAGES_TABLE=oncall-messages

# Bedrock Configuration
BEDROCK_MODEL_ID=us.anthropic.claude-opus-4-20250514-v1:0
```

### AWS Permissions

Ensure your AWS credentials have these permissions:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "dynamodb:GetItem",
                "dynamodb:PutItem",
                "dynamodb:UpdateItem",
                "dynamodb:DeleteItem",
                "dynamodb:Query",
                "dynamodb:Scan"
            ],
            "Resource": [
                "arn:aws:dynamodb:*:*:table/oncall-instances",
                "arn:aws:dynamodb:*:*:table/oncall-messages"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel"
            ],
            "Resource": "*"
        }
    ]
}
```

## Troubleshooting

### Common Issues

1. **Connection Refused**
   ```
   Error: Connection refused to MCP server
   Solution: Ensure the MCP server is running on the correct port
   ```

2. **AWS Credentials Not Found**
   ```
   Error: No credentials found
   Solution: Run 'aws configure' or set environment variables
   ```

3. **DynamoDB Table Not Found**
   ```
   Error: Table does not exist
   Solution: Deploy the DynamoDB infrastructure first
   ```

4. **Permission Denied**
   ```
   Error: Access denied
   Solution: Check AWS IAM permissions
   ```

### Debug Mode

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Health Checks

```bash
# Check MCP server
curl http://localhost:8080/health

# Check DynamoDB tables
python dynamodb_cli.py list-instances

# Check AWS credentials
aws sts get-caller-identity
```

## Performance Tips

1. **Connection Pooling**: Reuse MCP client connections when possible
2. **Batch Operations**: Use batch client for multiple operations
3. **TTL Management**: Monitor and adjust TTL settings for cost optimization
4. **Caching**: Implement local caching for frequently accessed data

## Security Considerations

1. **Credentials**: Never commit AWS credentials to version control
2. **Network**: Use HTTPS for production MCP server connections
3. **Permissions**: Follow principle of least privilege for AWS IAM
4. **Data**: Encrypt sensitive data before storing in DynamoDB

## Development

### Adding New Features

1. **New MCP Tools**: Add to `src/terminal_mcp/server.py`
2. **New DynamoDB Operations**: Add to `dynamodb_client.py`
3. **New CLI Commands**: Add to `dynamodb_cli.py`

### Testing

```bash
# Run all tests
python test_dynamodb.py

# Run specific test
python -m pytest tests/test_specific.py -v

# Run with coverage
python -m pytest --cov=. tests/
```

### Code Style

Follow PEP 8 guidelines and use type hints:

```python
from typing import Dict, List, Optional

def example_function(param: str) -> Dict[str, str]:
    """Example function with type hints."""
    return {"result": param}
```

## Support

For issues and questions:

1. Check the troubleshooting section above
2. Review AWS CloudWatch logs
3. Check DynamoDB CloudWatch metrics
4. Contact the development team

## License

This project is licensed under the MIT License - see the LICENSE file for details. 