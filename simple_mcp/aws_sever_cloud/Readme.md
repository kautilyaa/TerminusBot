# AWS MCP Server

An MCP (Model Context Protocol) server that provides access to AWS CloudWatch logs and EC2 instance details using FastMCP framework with IAM role authentication.

## Features

- Fetch EC2 instance details with optional filters
- Retrieve CloudWatch logs with time range and pattern filtering
- List available CloudWatch log groups
- Server-Sent Events (SSE) for real-time AWS status updates
- IAM role-based authentication (no hardcoded credentials)
- Comprehensive logging
- Health check endpoint

## Prerequisites

- Python 3.12 or higher
- AWS EC2 instance with appropriate IAM role attached
- Required IAM permissions (see IAM Configuration section)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd aws-mcp-server
Create a virtual environment:
python3.12 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
Install dependencies:
pip install -r requirements.txt
IAM Role Configuration
Create an IAM role with the following policy and attach it to your EC2 instance:

{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeInstances",
                "ec2:DescribeInstanceStatus",
                "ec2:DescribeTags"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:DescribeLogGroups",
                "logs:DescribeLogStreams",
                "logs:FilterLogEvents",
                "logs:GetLogEvents"
            ],
            "Resource": "*"
        }
    ]
}
Attaching IAM Role to EC2 Instance
Go to AWS Console > IAM > Roles
Create a new role with the above policy
Go to EC2 > Instances > Select your instance
Actions > Security > Modify IAM Role
Select the created role and save
Configuration
Set environment variables as needed:

export AWS_REGION=us-east-1  # Default region
export SERVER_PORT=8080      # Server port
export LOG_LEVEL=INFO        # Logging level
Running the Server
Development Mode
python server.py
Production Mode
Using systemd service (recommended):

Create service file /etc/systemd/system/aws-mcp-server.service:
[Unit]
Description=AWS MCP Server
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/aws-mcp-server
Environment="PATH=/home/ubuntu/aws-mcp-server/venv/bin"
ExecStart=/home/ubuntu/aws-mcp-server/venv/bin/python server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
Start and enable the service:
sudo systemctl daemon-reload
sudo systemctl start aws-mcp-server
sudo systemctl enable aws-mcp-server
sudo systemctl status aws-mcp-server
API Endpoints
Health Check
GET http://localhost:8080/health
Server-Sent Events
GET http://localhost:8080/sse
MCP Tools (via MCP protocol)
get_ec2_instances: Fetch EC2 instance details

Optional filters parameter
get_cloudwatch_logs: Retrieve CloudWatch logs

Parameters: log_group_name, start_time_hours_ago, filter_pattern, limit
list_log_groups: List available log groups

Optional prefix parameter
Usage Examples
Using MCP Client
import httpx
from mcp import ClientSession

async def example():
    async with ClientSession("http://localhost:8080/mcp") as session:
        # Get EC2 instances
        result = await session.call_tool(
            "get_ec2_instances",
            arguments={}
        )
        print(result)
        
        # Get CloudWatch logs
        result = await session.call_tool(
            "get_cloudwatch_logs",
            arguments={
                "log_group_name": "/aws/lambda/my-function",
                "start_time_hours_ago": 2,
                "limit": 50
            }
        )
        print(result)
Using SSE
const eventSource = new EventSource('http://localhost:8080/sse');

eventSource.onmessage = function(event) {
    const data = JSON.parse(event.data);
    console.log('AWS Status Update:', data);
};

eventSource.onerror = function(error) {
    console.error('SSE Error:', error);
};
Monitoring
Logs
Logs are written to:

Console (stdout)
File: mcp-server.log
Log Levels
INFO: General information
WARNING: Warning messages
ERROR: Error messages
DEBUG: Detailed debug information
Viewing Logs
# Real-time logs
tail -f mcp-server.log

# Service logs (if using systemd)
sudo journalctl -u aws-mcp-server -f
Security Considerations
IAM Roles: Always use IAM roles instead of hardcoded credentials
Network Security: Ensure proper security groups are configured
HTTPS: Use a reverse proxy (nginx/Apache) with SSL in production
Access Control: Implement authentication/authorization as needed
Troubleshooting
Common Issues
Permission Denied Errors

Check IAM role permissions
Verify role is attached to EC2 instance
Connection Errors

Check security group allows port 8080
Verify server is running: sudo systemctl status aws-mcp-server
No Logs Returned

Verify log group name is correct
Check time range parameters
Ensure IAM role has logs:FilterLogEvents permission
Debug Mode
Enable debug logging:

export LOG_LEVEL=DEBUG
python server.py
Performance Optimization
Caching: Consider implementing caching for frequently accessed data
Pagination: Use pagination for large result sets
Connection Pooling: The server uses connection pooling by default
Rate Limiting: Implement rate limiting for production use
Contributing
Fork the repository
Create a feature branch
Make your changes
Add tests if applicable
Submit a pull request
License
[Your License Here]

Support
For issues and questions:

Check the logs first
Review IAM permissions
Ensure all dependencies are installed
Create an issue in the repository

## Deployment Steps

1. **Launch EC2 Instance**:
   - Use Amazon Linux 2 or Ubuntu 20.04+
   - Instance type: t3.micro or larger
   - Security group: Allow inbound traffic on port 8080

2. **Install Python 3.12**:
```bash
# Ubuntu
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.12 python3.12-venv python3.12-dev

# Amazon Linux 2
sudo yum install -y python3.12
Deploy the code and follow the installation instructions in the README.

Configure IAM role as described in the README.

Start the service using systemd as shown in the README.

This implementation provides a complete AWS MCP server with proper logging, error handling, and deployment instructions. The server uses IAM roles for authentication, making it secure and suitable for EC2 deployment.