import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import boto3
from botocore.exceptions import ClientError
from fastmcp import FastMCP, Context
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('mcp-server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize AWS clients using IAM roles
def get_aws_clients():
    """Initialize AWS clients with IAM role credentials"""
    try:
        # Get region from environment variable or default to us-east-1
        region = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')

        session = boto3.Session(region_name=region)
        ec2_client = session.client('ec2', region_name=region)
        logs_client = session.client('logs', region_name=region)
        logger.info(f"Successfully initialized AWS clients with IAM role in region: {region}")
        return ec2_client, logs_client
    except Exception as e:
        logger.error(f"Failed to initialize AWS clients: {str(e)}")
        raise

ec2_client, logs_client = get_aws_clients()

# Initialize FastMCP
mcp = FastMCP(name="aws-mcp-server", version="1.0.0")

@mcp.tool()
async def get_ec2_instances(context: Context, filters: Optional[Dict] = None) -> str:
    """
    Get details of EC2 instances

    Args:
        filters: Optional filters for EC2 instances (e.g., {"Name": "instance-state-name", "Values": ["running"]})
    """
    logger.info(f"Fetching EC2 instances with filters: {filters}")
    try:
        if filters:
            response = ec2_client.describe_instances(Filters=[filters])
        else:
            response = ec2_client.describe_instances()

        instances = []
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                instance_info = {
                    'InstanceId': instance['InstanceId'],
                    'InstanceType': instance['InstanceType'],
                    'State': instance['State']['Name'],
                    'LaunchTime': str(instance.get('LaunchTime', '')),
                    'PrivateIpAddress': instance.get('PrivateIpAddress', ''),
                    'PublicIpAddress': instance.get('PublicIpAddress', ''),
                    'Tags': {tag['Key']: tag['Value'] for tag in instance.get('Tags', [])}
                }
                instances.append(instance_info)

        logger.info(f"Successfully fetched {len(instances)} EC2 instances")
        return json.dumps(instances, indent=2)
    except ClientError as e:
        logger.error(f"AWS API error while fetching EC2 instances: {str(e)}")
        return f"Error fetching EC2 instances: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error while fetching EC2 instances: {str(e)}")
        return f"Unexpected error: {str(e)}"

@mcp.tool()
async def get_cloudwatch_logs(
    context: Context,
    log_group_name: str,
    start_time_hours_ago: int = 1,
    filter_pattern: Optional[str] = None,
    limit: int = 100
) -> str:
    """
    Get CloudWatch logs from a specific log group

    Args:
        log_group_name: Name of the CloudWatch log group
        start_time_hours_ago: Number of hours ago to start fetching logs (default: 1)
        filter_pattern: Optional filter pattern for logs
        limit: Maximum number of log events to return (default: 100)
    """
    logger.info(f"Fetching CloudWatch logs from group: {log_group_name}")
    try:
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=start_time_hours_ago)

        params = {
            'logGroupName': log_group_name,
            'startTime': int(start_time.timestamp() * 1000),
            'endTime': int(end_time.timestamp() * 1000),
            'limit': limit
        }

        if filter_pattern:
            params['filterPattern'] = filter_pattern

        response = logs_client.filter_log_events(**params)

        log_events = []
        for event in response.get('events', []):
            log_events.append({
                'timestamp': datetime.fromtimestamp(event['timestamp'] / 1000).isoformat(),
                'message': event['message']
            })

        logger.info(f"Successfully fetched {len(log_events)} log events")
        return json.dumps(log_events, indent=2)
    except ClientError as e:
        logger.error(f"AWS API error while fetching CloudWatch logs: {str(e)}")
        return f"Error fetching CloudWatch logs: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error while fetching CloudWatch logs: {str(e)}")
        return f"Unexpected error: {str(e)}"

@mcp.tool()
async def list_log_groups(context: Context, prefix: Optional[str] = None) -> str:
    """
    List available CloudWatch log groups

    Args:
        prefix: Optional prefix to filter log groups
    """
    logger.info(f"Listing CloudWatch log groups with prefix: {prefix}")
    try:
        params = {}
        if prefix:
            params['logGroupNamePrefix'] = prefix

        response = logs_client.describe_log_groups(**params)

        log_groups = []
        for group in response.get('logGroups', []):
            log_groups.append({
                'logGroupName': group['logGroupName'],
                'creationTime': datetime.fromtimestamp(group['creationTime'] / 1000).isoformat(),
                'storedBytes': group.get('storedBytes', 0)
            })

        logger.info(f"Successfully listed {len(log_groups)} log groups")
        return json.dumps(log_groups, indent=2)
    except ClientError as e:
        logger.error(f"AWS API error while listing log groups: {str(e)}")
        return f"Error listing log groups: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error while listing log groups: {str(e)}")
        return f"Unexpected error: {str(e)}"

# Create FastAPI app for SSE endpoint
app = FastAPI(title="AWS MCP Server - SSE Endpoint")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "aws-mcp-server-sse"}

async def event_generator():
    """Generate SSE events for AWS resource updates"""
    while True:
        try:
            # Check EC2 instances
            response = ec2_client.describe_instances()
            instance_count = sum(len(r['Instances']) for r in response['Reservations'])

            event_data = {
                "timestamp": datetime.utcnow().isoformat(),
                "type": "aws_status",
                "data": {
                    "ec2_instance_count": instance_count,
                    "status": "operational"
                }
            }

            yield f"data: {json.dumps(event_data)}\\n\\n"
            await asyncio.sleep(30)  # Send updates every 30 seconds

        except Exception as e:
            logger.error(f"Error in SSE event generator: {str(e)}")
            yield f"data: {json.dumps({'error': str(e)})}\\n\\n"
            await asyncio.sleep(60)

@app.get("/sse")
async def sse_endpoint():
    """Server-Sent Events endpoint for real-time AWS updates"""
    logger.info("SSE connection established")
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan manager for FastAPI app"""
    logger.info("Starting AWS MCP Server SSE endpoint")
    yield
    logger.info("Shutting down AWS MCP Server SSE endpoint")

app.router.lifespan_context = lifespan

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "sse":
        # Run SSE server
        logger.info("Starting AWS MCP Server SSE endpoint on port 8080")
        uvicorn.run(app, host="0.0.0.0", port=8002, log_level="info")
    else:
        # Run MCP server
        logger.info("Starting AWS MCP Server on stdio")
        mcp.run()
