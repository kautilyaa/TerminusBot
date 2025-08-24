#!/usr/bin/env python3
"""
AWS MCP Server - A Model Context Protocol server for AWS operations using FastMCP
"""

import asyncio
import json
import logging
import argparse
import sys
from typing import Any, Dict, List, Optional

import boto3
from datetime import datetime, timedelta

# Import FastMCP
try:
    from fastmcp import FastMCP
except ImportError:
    print("FastMCP not found. Please install with: pip install fastmcp", file=sys.stderr)
    sys.exit(1)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the FastMCP server
mcp = FastMCP("AWS MCP Server")

@mcp.tool()
async def list_ec2_instances(region: str = "us-east-1") -> str:
    """List EC2 instances in the specified region
    
    Args:
        region: AWS region to list instances from (default: us-east-1)
    """
    try:
        ec2 = boto3.client('ec2', region_name=region)
        response = ec2.describe_instances()
        
        instances = []
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                # Get instance name from tags
                name = "N/A"
                if 'Tags' in instance:
                    for tag in instance['Tags']:
                        if tag['Key'] == 'Name':
                            name = tag['Value']
                            break
                
                instances.append({
                    'InstanceId': instance['InstanceId'],
                    'Name': name,
                    'InstanceType': instance['InstanceType'],
                    'State': instance['State']['Name'],
                    'LaunchTime': instance['LaunchTime'].isoformat(),
                    'PrivateIpAddress': instance.get('PrivateIpAddress', 'N/A'),
                    'PublicIpAddress': instance.get('PublicIpAddress', 'N/A'),
                })
        
        return f"EC2 Instances in {region}:\n\n" + json.dumps(instances, indent=2)
    except Exception as e:
        logger.error(f"Error listing EC2 instances: {e}")
        return f"Error listing EC2 instances: {str(e)}"

@mcp.tool()
async def start_ec2_instance(instance_id: str, region: str = "us-east-1") -> str:
    """Start an EC2 instance
    
    Args:
        instance_id: The EC2 instance ID to start
        region: AWS region where the instance is located (default: us-east-1)
    """
    try:
        ec2 = boto3.client('ec2', region_name=region)
        response = ec2.start_instances(InstanceIds=[instance_id])
        
        result = {
            "success": True,
            "message": f"Starting instance {instance_id} in {region}",
            "current_state": response['StartingInstances'][0]['CurrentState']['Name'],
            "previous_state": response['StartingInstances'][0]['PreviousState']['Name']
        }
        
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error starting EC2 instance {instance_id}: {e}")
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool()
async def stop_ec2_instance(instance_id: str, region: str = "us-east-1") -> str:
    """Stop an EC2 instance
    
    Args:
        instance_id: The EC2 instance ID to stop
        region: AWS region where the instance is located (default: us-east-1)
    """
    try:
        ec2 = boto3.client('ec2', region_name=region)
        response = ec2.stop_instances(InstanceIds=[instance_id])
        
        result = {
            "success": True,
            "message": f"Stopping instance {instance_id} in {region}",
            "current_state": response['StoppingInstances'][0]['CurrentState']['Name'],
            "previous_state": response['StoppingInstances'][0]['PreviousState']['Name']
        }
        
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error stopping EC2 instance {instance_id}: {e}")
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool()
async def list_s3_buckets(region: Optional[str] = None) -> str:
    """List S3 buckets
    
    Args:
        region: Optional AWS region to filter buckets (if None, lists all buckets)
    """
    try:
        s3 = boto3.client('s3', region_name=region) if region else boto3.client('s3')
        response = s3.list_buckets()
        
        buckets = []
        for bucket in response['Buckets']:
            bucket_info = {
                'Name': bucket['Name'],
                'CreationDate': bucket['CreationDate'].isoformat()
            }
            
            # Get bucket region if not specified
            if not region:
                try:
                    bucket_region = s3.get_bucket_location(Bucket=bucket['Name'])
                    bucket_info['Region'] = bucket_region.get('LocationConstraint', 'us-east-1')
                except:
                    bucket_info['Region'] = 'unknown'
            
            buckets.append(bucket_info)
        
        return f"S3 Buckets:\n\n" + json.dumps(buckets, indent=2)
    except Exception as e:
        logger.error(f"Error listing S3 buckets: {e}")
        return f"Error listing S3 buckets: {str(e)}"

@mcp.tool()
async def create_s3_bucket(bucket_name: str, region: str = "us-east-1") -> str:
    """Create a new S3 bucket
    
    Args:
        bucket_name: Name of the S3 bucket to create
        region: AWS region for the bucket (default: us-east-1)
    """
    try:
        s3 = boto3.client('s3', region_name=region)
        
        if region == 'us-east-1':
            response = s3.create_bucket(Bucket=bucket_name)
        else:
            response = s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': region}
            )
        
        result = {
            "success": True,
            "message": f"Created bucket {bucket_name} in region {region}",
            "location": response['Location']
        }
        
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error creating S3 bucket {bucket_name}: {e}")
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool()
async def list_s3_objects(bucket_name: str, prefix: str = "", max_keys: int = 100) -> str:
    """List objects in an S3 bucket
    
    Args:
        bucket_name: Name of the S3 bucket
        prefix: Object prefix to filter by (default: empty string)
        max_keys: Maximum number of objects to return (default: 100)
    """
    try:
        s3 = boto3.client('s3')
        kwargs = {
            'Bucket': bucket_name,
            'MaxKeys': max_keys
        }
        if prefix:
            kwargs['Prefix'] = prefix
            
        response = s3.list_objects_v2(**kwargs)
        
        objects = []
        for obj in response.get('Contents', []):
            objects.append({
                'Key': obj['Key'],
                'Size': obj['Size'],
                'LastModified': obj['LastModified'].isoformat(),
                'StorageClass': obj.get('StorageClass', 'STANDARD')
            })
        
        result = {
            "bucket": bucket_name,
            "prefix": prefix,
            "objects": objects,
            "count": len(objects),
            "is_truncated": response.get('IsTruncated', False)
        }
        
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error listing S3 objects in {bucket_name}: {e}")
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool()
async def list_rds_instances(region: str = "us-east-1") -> str:
    """List RDS instances in the specified region
    
    Args:
        region: AWS region to list RDS instances from (default: us-east-1)
    """
    try:
        rds = boto3.client('rds', region_name=region)
        response = rds.describe_db_instances()
        
        instances = []
        for instance in response['DBInstances']:
            instances.append({
                'DBInstanceIdentifier': instance['DBInstanceIdentifier'],
                'DBInstanceClass': instance['DBInstanceClass'],
                'Engine': instance['Engine'],
                'EngineVersion': instance['EngineVersion'],
                'DBInstanceStatus': instance['DBInstanceStatus'],
                'Endpoint': instance.get('Endpoint', {}).get('Address', 'N/A'),
                'Port': instance.get('Endpoint', {}).get('Port', 'N/A'),
                'AllocatedStorage': instance['AllocatedStorage'],
                'StorageType': instance['StorageType'],
                'MultiAZ': instance['MultiAZ'],
                'AvailabilityZone': instance.get('AvailabilityZone', 'N/A'),
            })
        
        return f"RDS Instances in {region}:\n\n" + json.dumps(instances, indent=2)
    except Exception as e:
        logger.error(f"Error listing RDS instances: {e}")
        return f"Error listing RDS instances: {str(e)}"

@mcp.tool()
async def describe_rds_instance(instance_identifier: str, region: str = "us-east-1") -> str:
    """Get detailed information about an RDS instance
    
    Args:
        instance_identifier: RDS instance identifier
        region: AWS region where the instance is located (default: us-east-1)
    """
    try:
        rds = boto3.client('rds', region_name=region)
        response = rds.describe_db_instances(DBInstanceIdentifier=instance_identifier)
        
        if not response['DBInstances']:
            return json.dumps({"success": False, "error": "Instance not found"}, indent=2)
        
        instance = response['DBInstances'][0]
        
        detailed_info = {
            'DBInstanceIdentifier': instance['DBInstanceIdentifier'],
            'DBInstanceClass': instance['DBInstanceClass'],
            'Engine': instance['Engine'],
            'EngineVersion': instance['EngineVersion'],
            'DBInstanceStatus': instance['DBInstanceStatus'],
            'MasterUsername': instance['MasterUsername'],
            'DBName': instance.get('DBName', 'N/A'),
            'Endpoint': instance.get('Endpoint', {}).get('Address', 'N/A'),
            'Port': instance.get('Endpoint', {}).get('Port', 'N/A'),
            'AllocatedStorage': instance['AllocatedStorage'],
            'StorageType': instance['StorageType'],
            'StorageEncrypted': instance['StorageEncrypted'],
            'MultiAZ': instance['MultiAZ'],
            'AvailabilityZone': instance.get('AvailabilityZone', 'N/A'),
            'VpcId': instance.get('DbSubnetGroup', {}).get('VpcId', 'N/A'),
            'SubnetGroup': instance.get('DbSubnetGroup', {}).get('DBSubnetGroupName', 'N/A'),
            'SecurityGroups': [sg['VpcSecurityGroupId'] for sg in instance.get('VpcSecurityGroups', [])],
            'BackupRetentionPeriod': instance['BackupRetentionPeriod'],
            'PreferredBackupWindow': instance.get('PreferredBackupWindow', 'N/A'),
            'PreferredMaintenanceWindow': instance.get('PreferredMaintenanceWindow', 'N/A'),
        }
        
        return json.dumps(detailed_info, indent=2)
    except Exception as e:
        logger.error(f"Error describing RDS instance {instance_identifier}: {e}")
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool()
async def get_aws_regions() -> str:
    """Get list of available AWS regions"""
    try:
        ec2 = boto3.client('ec2', region_name='us-east-1')
        response = ec2.describe_regions()
        
        regions = []
        for region in response['Regions']:
            regions.append({
                'RegionName': region['RegionName'],
                'OptInStatus': region['OptInStatus']
            })
        
        return f"Available AWS Regions:\n\n" + json.dumps(regions, indent=2)
    except Exception as e:
        logger.error(f"Error getting AWS regions: {e}")
        return f"Error getting AWS regions: {str(e)}"

@mcp.tool()
async def get_aws_account_info() -> str:
    """Get AWS account information"""
    try:
        sts = boto3.client('sts')
        response = sts.get_caller_identity()
        
        account_info = {
            'Account': response.get('Account', 'N/A'),
            'UserId': response.get('UserId', 'N/A'),
            'Arn': response.get('Arn', 'N/A')
        }
        
        return f"AWS Account Information:\n\n" + json.dumps(account_info, indent=2)
    except Exception as e:
        logger.error(f"Error getting AWS account info: {e}")
        return f"Error getting AWS account info: {str(e)}"

@mcp.tool()
async def get_cloudwatch_logs(
    log_group_name: str,
    log_stream_name: Optional[str] = None,
    region: str = "us-east-1",
    hours_back: int = 10,
    max_events: int = 1000,
    filter_pattern: Optional[str] = None
) -> str:
    """Get CloudWatch logs from a log group and optionally specific log stream
    
    Args:
        log_group_name: Name of the CloudWatch log group
        log_stream_name: Optional specific log stream name (if None, gets from all streams)
        region: AWS region (default: us-east-1)
        hours_back: How many hours back to retrieve logs (default: 1)
        max_events: Maximum number of log events to return (default: 100)
        filter_pattern: Optional filter pattern to match log events
    """
    try:
        logs_client = boto3.client('logs', region_name=region)
        
        # Calculate time range
        end_time = datetime.now(datetime.UTC)
        start_time = end_time - timedelta(hours=hours_back)
        
        # Convert to milliseconds since epoch
        start_time_ms = int(start_time.timestamp() * 1000)
        end_time_ms = int(end_time.timestamp() * 1000)
        
        # Prepare filter_log_events parameters
        filter_params = {
            'logGroupName': log_group_name,
            'startTime': start_time_ms,
            'endTime': end_time_ms,
            'limit': max_events
        }
        
        # Add optional parameters
        if log_stream_name:
            filter_params['logStreamNames'] = [log_stream_name]
        
        if filter_pattern:
            filter_params['filterPattern'] = filter_pattern
        
        # Get log events
        response = logs_client.filter_log_events(**filter_params)
        
        # Format the events
        events = []
        for event in response.get('events', []):
            events.append({
                'timestamp': datetime.fromtimestamp(event['timestamp'] / 1000).isoformat(),
                'logStreamName': event['logStreamName'],
                'message': event['message'].strip()
            })
        
        result = {
            'logGroupName': log_group_name,
            'logStreamName': log_stream_name or 'all streams',
            'region': region,
            'timeRange': {
                'start': start_time.isoformat(),
                'end': end_time.isoformat()
            },
            'filterPattern': filter_pattern,
            'eventCount': len(events),
            'events': events,
            'nextToken': response.get('nextToken')
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        logger.error(f"Error getting CloudWatch logs: {e}")
        return json.dumps({
            "success": False, 
            "error": str(e),
            "logGroupName": log_group_name
        }, indent=2)

@mcp.tool()
async def list_cloudwatch_log_groups(region: str = "us-east-1", max_groups: int = 1000) -> str:
    """List CloudWatch log groups in the specified region
    
    Args:
        region: AWS region (default: us-east-1)
        max_groups: Maximum number of log groups to return (default: 50)
    """
    try:
        logs_client = boto3.client('logs', region_name=region)
        response = logs_client.describe_log_groups(limit=max_groups)
        
        log_groups = []
        for group in response.get('logGroups', []):
            log_groups.append({
                'logGroupName': group['logGroupName'],
                'creationTime': datetime.fromtimestamp(group['creationTime'] / 1000).isoformat(),
                'retentionInDays': group.get('retentionInDays', 'Never expire'),
                'storedBytes': group.get('storedBytes', 0),
                'metricFilterCount': group.get('metricFilterCount', 0)
            })
        
        result = {
            'region': region,
            'logGroupCount': len(log_groups),
            'logGroups': log_groups
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        logger.error(f"Error listing CloudWatch log groups: {e}")
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool()
async def list_cloudwatch_log_streams(
    log_group_name: str, 
    region: str = "us-east-1", 
    max_streams: int = 100
) -> str:
    """List log streams in a CloudWatch log group
    
    Args:
        log_group_name: Name of the CloudWatch log group
        region: AWS region (default: us-east-1)
        max_streams: Maximum number of log streams to return (default: 20)
    """
    try:
        logs_client = boto3.client('logs', region_name=region)
        response = logs_client.describe_log_streams(
            logGroupName=log_group_name,
            limit=max_streams,
            orderBy='LastEventTime',
            descending=True
        )
        
        log_streams = []
        for stream in response.get('logStreams', []):
            stream_info = {
                'logStreamName': stream['logStreamName'],
                'creationTime': datetime.fromtimestamp(stream['creationTime'] / 1000).isoformat(),
                'storedBytes': stream.get('storedBytes', 0)
            }
            
            if 'lastEventTime' in stream:
                stream_info['lastEventTime'] = datetime.fromtimestamp(stream['lastEventTime'] / 1000).isoformat()
            
            if 'lastIngestionTime' in stream:
                stream_info['lastIngestionTime'] = datetime.fromtimestamp(stream['lastIngestionTime'] / 1000).isoformat()
                
            log_streams.append(stream_info)
        
        result = {
            'logGroupName': log_group_name,
            'region': region,
            'logStreamCount': len(log_streams),
            'logStreams': log_streams
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        logger.error(f"Error listing CloudWatch log streams: {e}")
        return json.dumps({"success": False, "error": str(e)}, indent=2)
    
@mcp.tool()
async def search_ec2_logs(
    instance_id: str,
    log_stream_name: Optional[str] = None,
    search_term: str = "",
    region: str = "us-east-1",
    hours_back: int = 24,
    max_events: int = 1000
) -> str:
    """Search EC2 logs for a specific instance

    Args:
        instance_id: EC2 instance ID (e.g., i-1234567890abcdef0)
        log_stream_name: Optional log stream (auth, ssm, apt-history, cloudinit, syslog, kern, dmesg)
        search_term: Text to search for in log messages
        region: AWS region (default: us-east-1)
        hours_back: How many hours back to search (default: 24)
        max_events: Maximum number of log events to return (default: 1000)
    """
    try:
        logs_client = boto3.client('logs', region_name=region)
        log_group_name = f"/ec2/{instance_id}"

        # Calculate time range
        end_time = datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else datetime.timezone.utc)
        start_time = end_time - timedelta(hours=hours_back)

        start_time_ms = int(start_time.timestamp() * 1000)
        end_time_ms = int(end_time.timestamp() * 1000)

        # Prepare filter parameters
        filter_params = {
            'logGroupName': log_group_name,
            'startTime': start_time_ms,
            'endTime': end_time_ms,
            'limit': max_events
        }

        # Add specific log stream if provided
        if log_stream_name:
            filter_params['logStreamNames'] = [log_stream_name]

        # Add search filter if provided
        if search_term:
            filter_params['filterPattern'] = f'"{search_term}"'

        response = logs_client.filter_log_events(**filter_params)

        # Format events
        events = []
        for event in response.get('events', []):
            events.append({
                'timestamp': datetime.fromtimestamp(event['timestamp'] / 1000).isoformat(),
                'logStreamName': event['logStreamName'],
                'message': event['message'].strip()
            })

        result = {
            'instanceId': instance_id,
            'logGroupName': log_group_name,
            'logStreamName': log_stream_name or 'all streams',
            'searchTerm': search_term,
            'region': region,
            'timeRange': {
                'start': start_time.isoformat(),
                'end': end_time.isoformat()
            },
            'eventCount': len(events),
            'events': events
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Error searching EC2 logs: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "instanceId": instance_id
        }, indent=2)

@mcp.tool()
async def get_ec2_log_streams(instance_id: str, region: str = "us-east-1") -> str:
    """Get all log streams for a specific EC2 instance

    Args:
        instance_id: EC2 instance ID
        region: AWS region (default: us-east-1)
    """
    try:
        logs_client = boto3.client('logs', region_name=region)
        log_group_name = f"/ec2/{instance_id}"

        response = logs_client.describe_log_streams(
            logGroupName=log_group_name,
            orderBy='LastEventTime',
            descending=True
        )

        log_streams = []
        stream_types = {
            'auth': 'Authentication logs (/var/log/auth.log)',
            'ssm': 'SSM Agent logs (/var/log/amazon/ssm/amazon-ssm-agent.log)',
            'apt-history': 'APT package history (/var/log/apt/history.log)',
            'cloudinit': 'Cloud-init output (/var/log/cloud-init-output.log)',
            'syslog': 'System logs (/var/log/syslog)',
            'kern': 'Kernel logs (/var/log/kern.log)',
            'dmesg': 'Kernel ring buffer (/var/log/dmesg)'
        }

        for stream in response.get('logStreams', []):
            stream_name = stream['logStreamName']
            stream_info = {
                'logStreamName': stream_name,
                'description': stream_types.get(stream_name, 'Unknown log type'),
                'creationTime': datetime.fromtimestamp(stream['creationTime'] / 1000).isoformat(),
                'storedBytes': stream.get('storedBytes', 0)
            }

            if 'lastEventTime' in stream:
                stream_info['lastEventTime'] = datetime.fromtimestamp(stream['lastEventTime'] / 1000).isoformat()

            log_streams.append(stream_info)

        result = {
            'instanceId': instance_id,
            'logGroupName': log_group_name,
            'region': region,
            'availableStreams': log_streams,
            'streamCount': len(log_streams)
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Error getting EC2 log streams: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "instanceId": instance_id
        }, indent=2)

@mcp.tool()
async def get_recent_ec2_errors(
    instance_id: str,
    region: str = "us-east-1",
    hours_back: int = 24,
    max_events: int = 500
) -> str:
    """Get recent error messages from EC2 instance logs

    Args:
        instance_id: EC2 instance ID
        region: AWS region (default: us-east-1)
        hours_back: How many hours back to search (default: 24)
        max_events: Maximum number of events to return (default: 500)
    """
    try:
        logs_client = boto3.client('logs', region_name=region)
        log_group_name = f"/ec2/{instance_id}"

        # Calculate time range
        end_time = datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else datetime.timezone.utc)
        start_time = end_time - timedelta(hours=hours_back)

        start_time_ms = int(start_time.timestamp() * 1000)
        end_time_ms = int(end_time.timestamp() * 1000)

        # Search for common error patterns
        error_patterns = [
            'ERROR',
            'FAILED',
            'CRITICAL',
            'FATAL',
            'Exception',
            'Traceback',
            'panic:',
            'segfault',
            'Out of memory'
        ]

        all_errors = []

        for pattern in error_patterns:
            try:
                response = logs_client.filter_log_events(
                    logGroupName=log_group_name,
                    startTime=start_time_ms,
                    endTime=end_time_ms,
                    filterPattern=f'"{pattern}"',
                    limit=max_events // len(error_patterns)
                )

                for event in response.get('events', []):
                    all_errors.append({
                        'timestamp': datetime.fromtimestamp(event['timestamp'] / 1000).isoformat(),
                        'logStreamName': event['logStreamName'],
                        'message': event['message'].strip(),
                        'errorType': pattern
                    })
            except Exception as pattern_error:
                logger.warning(f"Error searching for pattern {pattern}: {pattern_error}")
                continue

        # Sort by timestamp (most recent first)
        all_errors.sort(key=lambda x: x['timestamp'], reverse=True)

        # Limit results
        all_errors = all_errors[:max_events]

        result = {
            'instanceId': instance_id,
            'logGroupName': log_group_name,
            'region': region,
            'timeRange': {
                'start': start_time.isoformat(),
                'end': end_time.isoformat()
            },
            'errorCount': len(all_errors),
            'errors': all_errors,
            'searchPatterns': error_patterns
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Error getting EC2 errors: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "instanceId": instance_id
        }, indent=2)

@mcp.tool()
async def get_ec2_auth_logs(
    instance_id: str,
    region: str = "us-east-1",
    hours_back: int = 24,
    max_events: int = 1000
) -> str:
    """Get authentication logs for an EC2 instance

    Args:
        instance_id: EC2 instance ID
        region: AWS region (default: us-east-1)
        hours_back: How many hours back to retrieve logs (default: 24)
        max_events: Maximum number of log events to return (default: 1000)
    """
    return await search_ec2_logs(
        instance_id=instance_id,
        log_stream_name="auth",
        region=region,
        hours_back=hours_back,
        max_events=max_events
    )

@mcp.tool()
async def get_ec2_system_logs(
    instance_id: str,
    region: str = "us-east-1",
    hours_back: int = 24,
    max_events: int = 1000
) -> str:
    """Get system logs (syslog) for an EC2 instance

    Args:
        instance_id: EC2 instance ID
        region: AWS region (default: us-east-1)
        hours_back: How many hours back to retrieve logs (default: 24)
        max_events: Maximum number of log events to return (default: 1000)
    """
    return await search_ec2_logs(
        instance_id=instance_id,
        log_stream_name="syslog",
        region=region,
        hours_back=hours_back,
        max_events=max_events
    )

@mcp.tool()
async def search_all_ec2_log_groups(
    search_term: str,
    region: str = "us-east-1",
    hours_back: int = 24,
    max_events: int = 500
) -> str:
    """Search across all EC2 log groups for a specific term

    Args:
        search_term: Text to search for in log messages
        region: AWS region (default: us-east-1)
        hours_back: How many hours back to search (default: 24)
        max_events: Maximum number of log events to return per log group (default: 500)
    """
    try:
        logs_client = boto3.client('logs', region_name=region)

        # First, get all log groups that match the EC2 pattern
        response = logs_client.describe_log_groups(
            logGroupNamePrefix="/ec2/"
        )

        all_results = []

        for log_group in response.get('logGroups', []):
            log_group_name = log_group['logGroupName']
            instance_id = log_group_name.replace('/ec2/', '')

            try:
                # Search in this log group
                end_time = datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else datetime.timezone.utc)
                start_time = end_time - timedelta(hours=hours_back)

                start_time_ms = int(start_time.timestamp() * 1000)
                end_time_ms = int(end_time.timestamp() * 1000)

                filter_response = logs_client.filter_log_events(
                    logGroupName=log_group_name,
                    startTime=start_time_ms,
                    endTime=end_time_ms,
                    filterPattern=f'"{search_term}"',
                    limit=max_events
                )

                events = []
                for event in filter_response.get('events', []):
                    events.append({
                        'timestamp': datetime.fromtimestamp(event['timestamp'] / 1000).isoformat(),
                        'logStreamName': event['logStreamName'],
                        'message': event['message'].strip()
                    })

                if events:  # Only include instances that have matching logs
                    all_results.append({
                        'instanceId': instance_id,
                        'logGroupName': log_group_name,
                        'eventCount': len(events),
                        'events': events
                    })

            except Exception as search_error:
                logger.warning(f"Error searching log group {log_group_name}: {search_error}")
                continue

        result = {
            'searchTerm': search_term,
            'region': region,
            'timeRange': {
                'hoursBack': hours_back
            },
            'instancesWithMatches': len(all_results),
            'totalEvents': sum(r['eventCount'] for r in all_results),
            'results': all_results
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Error searching all EC2 log groups: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "searchTerm": search_term
        }, indent=2)

@mcp.tool()
async def get_ec2_log_summary(instance_id: str, region: str = "us-east-1", hours_back: int = 24) -> str:
    """Get a summary of log activity for an EC2 instance

    Args:
        instance_id: EC2 instance ID
        region: AWS region (default: us-east-1)
        hours_back: How many hours back to analyze (default: 24)
    """
    try:
        logs_client = boto3.client('logs', region_name=region)
        log_group_name = f"/ec2/{instance_id}"

        # Get log streams first
        streams_response = logs_client.describe_log_streams(
            logGroupName=log_group_name,
            orderBy='LastEventTime',
            descending=True
        )

        summary = {
            'instanceId': instance_id,
            'logGroupName': log_group_name,
            'region': region,
            'analysisTimeRange': f"Last {hours_back} hours",
            'logStreams': []
        }

        # Calculate time range
        end_time = datetime.now(datetime.UTC if hasattr(datetime, 'UTC') else datetime.timezone.utc)
        start_time = end_time - timedelta(hours=hours_back)
        start_time_ms = int(start_time.timestamp() * 1000)
        end_time_ms = int(end_time.timestamp() * 1000)

        total_events = 0

        for stream in streams_response.get('logStreams', []):
            stream_name = stream['logStreamName']

            try:
                # Get event count for this stream
                events_response = logs_client.filter_log_events(
                    logGroupName=log_group_name,
                    logStreamNames=[stream_name],
                    startTime=start_time_ms,
                    endTime=end_time_ms,
                    limit=10000  # Just to count, won't return all
                )

                event_count = len(events_response.get('events', []))
                total_events += event_count

                stream_summary = {
                    'streamName': stream_name,
                    'eventCount': event_count,
                    'storedBytes': stream.get('storedBytes', 0)
                }

                if 'lastEventTime' in stream:
                    stream_summary['lastEventTime'] = datetime.fromtimestamp(stream['lastEventTime'] / 1000).isoformat()

                summary['logStreams'].append(stream_summary)

            except Exception as stream_error:
                logger.warning(f"Error analyzing stream {stream_name}: {stream_error}")
                continue

        summary['totalEvents'] = total_events
        summary['activeStreams'] = len([s for s in summary['logStreams'] if s['eventCount'] > 0])

        return json.dumps(summary, indent=2)

    except Exception as e:
        logger.error(f"Error getting EC2 log summary: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "instanceId": instance_id
        }, indent=2)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='AWS MCP Server with FastMCP')
    parser.add_argument('--transport', choices=['stdio', 'http', 'sse'], default='sse',
                       help='Transport type (stdio, http, or sse)')
    parser.add_argument('--host', default='localhost', help='Host for HTTP/SSE transport')
    parser.add_argument('--port', type=int, default=8002, help='Port for HTTP/SSE transport')
    
    args = parser.parse_args()
    
    try:
        if args.transport == 'http':
            # Run with HTTP transport
            print(f"Starting AWS MCP Server with HTTP transport on {args.host}:{args.port}", file=sys.stderr)
            asyncio.run(mcp.run_http_async(host=args.host, port=args.port))
        elif args.transport == 'sse':
            # Run with SSE transport
            print(f"Starting AWS MCP Server with SSE transport on {args.host}:{args.port}", file=sys.stderr)
            asyncio.run(mcp.run_sse_async(host=args.host, port=args.port))
        else:
            # Run with stdio transport (default)
            print("Starting AWS MCP Server with stdio transport", file=sys.stderr)
            mcp.run()
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()