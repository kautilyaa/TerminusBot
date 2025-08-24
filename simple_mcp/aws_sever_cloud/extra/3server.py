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
from datetime import datetime, timedelta, timezone

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

        return f"EC2 Instances in {region}:\\n\\n" + json.dumps(instances, indent=2)
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

        return f"S3 Buckets:\\n\\n" + json.dumps(buckets, indent=2)
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

        return f"RDS Instances in {region}:\\n\\n" + json.dumps(instances, indent=2)
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

        return f"Available AWS Regions:\\n\\n" + json.dumps(regions, indent=2)
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

        return f"AWS Account Information:\\n\\n" + json.dumps(account_info, indent=2)
    except Exception as e:
        logger.error(f"Error getting AWS account info: {e}")
        return f"Error getting AWS account info: {str(e)}"

@mcp.tool()
async def list_cloudwatch_log_groups(region: str = "us-east-1", max_groups: int = 1000) -> str:
    """List CloudWatch log groups in the specified region

    Args:
        region: AWS region (default: us-east-1)
        max_groups: Maximum number of log groups to return (default: 1000)
    """
    try:
        logs_client = boto3.client('logs', region_name=region)

        log_groups = []
        next_token = None

        while len(log_groups) < max_groups:
            params = {'limit': min(50, max_groups - len(log_groups))}
            if next_token:
                params['nextToken'] = next_token

            response = logs_client.describe_log_groups(**params)

            for group in response.get('logGroups', []):
                log_groups.append({
                    'logGroupName': group['logGroupName'],
                    'creationTime': datetime.fromtimestamp(group['creationTime'] / 1000, tz=timezone.utc).isoformat(),
                    'retentionInDays': group.get('retentionInDays', 'Never expire'),
                    'storedBytes': group.get('storedBytes', 0),
                    'metricFilterCount': group.get('metricFilterCount', 0),
                    'arn': group.get('arn', 'N/A')
                })

            next_token = response.get('nextToken')
            if not next_token:
                break

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
    max_streams: int = 50,
    order_by: str = "LastEventTime"
) -> str:
    """List log streams in a CloudWatch log group

    Args:
        log_group_name: Name of the CloudWatch log group
        region: AWS region (default: us-east-1)
        max_streams: Maximum number of log streams to return (default: 50)
        order_by: Order streams by 'LogStreamName' or 'LastEventTime' (default: LastEventTime)
    """
    try:
        logs_client = boto3.client('logs', region_name=region)

        # Validate order_by parameter
        if order_by not in ['LogStreamName', 'LastEventTime']:
            order_by = 'LastEventTime'

        log_streams = []
        next_token = None

        while len(log_streams) < max_streams:
            params = {
                'logGroupName': log_group_name,
                'limit': min(50, max_streams - len(log_streams)),
                'orderBy': order_by,
                'descending': True
            }

            if next_token:
                params['nextToken'] = next_token

            response = logs_client.describe_log_streams(**params)

            for stream in response.get('logStreams', []):
                stream_info = {
                    'logStreamName': stream['logStreamName'],
                    'creationTime': datetime.fromtimestamp(stream['creationTime'] / 1000, tz=timezone.utc).isoformat(),
                    'storedBytes': stream.get('storedBytes', 0),
                    'arn': stream.get('arn', 'N/A')
                }

                if 'firstEventTime' in stream:
                    stream_info['firstEventTime'] = datetime.fromtimestamp(stream['firstEventTime'] / 1000, tz=timezone.utc).isoformat()

                if 'lastEventTime' in stream:
                    stream_info['lastEventTime'] = datetime.fromtimestamp(stream['lastEventTime'] / 1000, tz=timezone.utc).isoformat()

                if 'lastIngestionTime' in stream:
                    stream_info['lastIngestionTime'] = datetime.fromtimestamp(stream['lastIngestionTime'] / 1000, tz=timezone.utc).isoformat()

                if 'uploadSequenceToken' in stream:
                    stream_info['uploadSequenceToken'] = stream['uploadSequenceToken']

                log_streams.append(stream_info)

            next_token = response.get('nextToken')
            if not next_token:
                break

        result = {
            'logGroupName': log_group_name,
            'region': region,
            'orderBy': order_by,
            'logStreamCount': len(log_streams),
            'logStreams': log_streams
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Error listing CloudWatch log streams for {log_group_name}: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "logGroupName": log_group_name
        }, indent=2)

@mcp.tool()
async def get_cloudwatch_logs(
    log_group_name: str,
    log_stream_name: Optional[str] = None,
    region: str = "us-east-1",
    hours_back: int = 1,
    max_events: int = 100,
    filter_pattern: Optional[str] = None,
    start_from_head: bool = False
) -> str:
    """Get CloudWatch logs from a log group and optionally specific log stream

    Args:
        log_group_name: Name of the CloudWatch log group
        log_stream_name: Optional specific log stream name (if None, gets from all streams)
        region: AWS region (default: us-east-1)
        hours_back: How many hours back to retrieve logs (default: 1)
        max_events: Maximum number of log events to return (default: 100)
        filter_pattern: Optional filter pattern to match log events
        start_from_head: Whether to start from the beginning of the time range
    """
    try:
        logs_client = boto3.client('logs', region_name=region)

        # Calculate time range
        end_time = datetime.now(timezone.utc)
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

        if start_from_head:
            filter_params['interleaved'] = True

        # Get log events
        events = []
        next_token = None

        while len(events) < max_events:
            if next_token:
                filter_params['nextToken'] = next_token
            elif 'nextToken' in filter_params:
                del filter_params['nextToken']

            # Adjust limit to not exceed max_events
            filter_params['limit'] = min(1000, max_events - len(events))

            response = logs_client.filter_log_events(**filter_params)

            batch_events = response.get('events', [])
            if not batch_events:
                break

            # Format the events
            for event in batch_events:
                events.append({
                    'timestamp': datetime.fromtimestamp(event['timestamp'] / 1000, tz=timezone.utc).isoformat(),
                    'logStreamName': event['logStreamName'],
                    'message': event['message'].strip(),
                    'eventId': event.get('eventId', 'N/A')
                })

            next_token = response.get('nextToken')
            if not next_token:
                break

        result = {
            'logGroupName': log_group_name,
            'logStreamName': log_stream_name or 'all streams',
            'region': region,
            'timeRange': {
                'start': start_time.isoformat(),
                'end': end_time.isoformat(),
                'hoursBack': hours_back
            },
            'filterPattern': filter_pattern,
            'eventCount': len(events),
            'events': events[:max_events],  # Ensure we don't exceed max_events
            'hasMoreEvents': next_token is not None
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Error getting CloudWatch logs from {log_group_name}: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "logGroupName": log_group_name,
            "logStreamName": log_stream_name
        }, indent=2)

@mcp.tool()
async def search_cloudwatch_logs(
    log_group_name: str,
    search_term: str,
    region: str = "us-east-1",
    hours_back: int = 24,
    max_events: int = 1000,
    log_stream_name: Optional[str] = None
) -> str:
    """Search CloudWatch logs for specific terms

    Args:
        log_group_name: Name of the CloudWatch log group
        search_term: Term to search for in log messages
        region: AWS region (default: us-east-1)
        hours_back: How many hours back to search (default: 24)
        max_events: Maximum number of log events to return (default: 1000)
        log_stream_name: Optional specific log stream to search
    """
    try:
        logs_client = boto3.client('logs', region_name=region)

        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours_back)

        start_time_ms = int(start_time.timestamp() * 1000)
        end_time_ms = int(end_time.timestamp() * 1000)

        # Prepare search parameters
        search_params = {
            'logGroupName': log_group_name,
            'startTime': start_time_ms,
            'endTime': end_time_ms,
            'filterPattern': f'"{search_term}"',
            'limit': max_events
        }

        if log_stream_name:
            search_params['logStreamNames'] = [log_stream_name]

        # Search log events
        events = []
        next_token = None

        while len(events) < max_events:
            if next_token:
                search_params['nextToken'] = next_token

            search_params['limit'] = min(1000, max_events - len(events))

            response = logs_client.filter_log_events(**search_params)

            batch_events = response.get('events', [])
            if not batch_events:
                break

            for event in batch_events:
                events.append({
                    'timestamp': datetime.fromtimestamp(event['timestamp'] / 1000, tz=timezone.utc).isoformat(),
                    'logStreamName': event['logStreamName'],
                    'message': event['message'].strip(),
                    'eventId': event.get('eventId', 'N/A')
                })

            next_token = response.get('nextToken')
            if not next_token:
                break

        result = {
            'logGroupName': log_group_name,
            'logStreamName': log_stream_name or 'all streams',
            'searchTerm': search_term,
            'region': region,
            'timeRange': {
                'start': start_time.isoformat(),
                'end': end_time.isoformat(),
                'hoursBack': hours_back
            },
            'eventCount': len(events),
            'events': events,
            'hasMoreEvents': next_token is not None
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Error searching CloudWatch logs: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "logGroupName": log_group_name,
            "searchTerm": search_term
        }, indent=2)

@mcp.tool()
async def get_cloudwatch_log_insights(
    log_group_name: str,
    query: str,
    region: str = "us-east-1",
    hours_back: int = 24,
    max_results: int = 1000
) -> str:
    """Run CloudWatch Logs Insights query

    Args:
        log_group_name: Name of the CloudWatch log group
        query: Logs Insights query string
        region: AWS region (default: us-east-1)
        hours_back: How many hours back to query (default: 24)
        max_results: Maximum number of results to return (default: 1000)
    """
    try:
        logs_client = boto3.client('logs', region_name=region)

        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours_back)

        start_time_timestamp = int(start_time.timestamp())
        end_time_timestamp = int(end_time.timestamp())

        # Start the query
        response = logs_client.start_query(
            logGroupName=log_group_name,
            startTime=start_time_timestamp,
            endTime=end_time_timestamp,
            queryString=query,
            limit=max_results
        )

        query_id = response['queryId']

        # Poll for results
        import time
        max_wait_time = 30  # Maximum wait time in seconds
        poll_interval = 1   # Poll every second
        waited = 0

        while waited < max_wait_time:
            result_response = logs_client.get_query_results(queryId=query_id)
            status = result_response['status']

            if status == 'Complete':
                results = []
                for result in result_response.get('results', []):
                    result_dict = {}
                    for field in result:
                        result_dict[field['field']] = field['value']
                    results.append(result_dict)

                query_result = {
                    'logGroupName': log_group_name,
                    'query': query,
                    'region': region,
                    'queryId': query_id,
                    'status': status,
                    'timeRange': {
                        'start': start_time.isoformat(),
                        'end': end_time.isoformat(),
                        'hoursBack': hours_back
                    },
                    'resultCount': len(results),
                    'results': results,
                    'statistics': result_response.get('statistics', {})
                }

                return json.dumps(query_result, indent=2)

            elif status in ['Failed', 'Cancelled']:
                return json.dumps({
                    "success": False,
                    "error": f"Query {status.lower()}",
                    "queryId": query_id,
                    "status": status
                }, indent=2)

            time.sleep(poll_interval)
            waited += poll_interval

        # If we get here, the query timed out
        return json.dumps({
            "success": False,
            "error": "Query timed out",
            "queryId": query_id,
            "status": "Timeout"
        }, indent=2)

    except Exception as e:
        logger.error(f"Error running CloudWatch Logs Insights query: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "logGroupName": log_group_name,
            "query": query
        }, indent=2)

# Keep the existing EC2-specific log functions as they are useful for EC2 instances
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
    log_group_name = f"/ec2/{instance_id}"

    if search_term:
        return await search_cloudwatch_logs(
            log_group_name=log_group_name,
            search_term=search_term,
            region=region,
            hours_back=hours_back,
            max_events=max_events,
            log_stream_name=log_stream_name
        )
    else:
        return await get_cloudwatch_logs(
            log_group_name=log_group_name,
            log_stream_name=log_stream_name,
            region=region,
            hours_back=hours_back,
            max_events=max_events
        )

@mcp.tool()
async def get_ec2_log_streams(instance_id: str, region: str = "us-east-1") -> str:
    """Get all log streams for a specific EC2 instance

    Args:
        instance_id: EC2 instance ID
        region: AWS region (default: us-east-1)
    """
    log_group_name = f"/ec2/{instance_id}"
    return await list_cloudwatch_log_streams(
        log_group_name=log_group_name,
        region=region,
        max_streams=100
    )

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
    log_group_name = f"/ec2/{instance_id}"

    # Search for common error patterns
    error_patterns = ['ERROR', 'FAILED', 'CRITICAL', 'FATAL', 'Exception']

    all_errors = []
    for pattern in error_patterns:
        try:
            # Get results as JSON string and parse it
            result_json = await search_cloudwatch_logs(
                log_group_name=log_group_name,
                search_term=pattern,
                region=region,
                hours_back=hours_back,
                max_events=max_events // len(error_patterns)
            )

            result_data = json.loads(result_json)
            if result_data.get('success', True) and 'events' in result_data:
                for event in result_data['events']:
                    event['errorType'] = pattern
                    all_errors.append(event)

        except Exception as e:
            logger.warning(f"Error searching for pattern {pattern}: {e}")
            continue

    # Sort by timestamp (most recent first)
    all_errors.sort(key=lambda x: x['timestamp'], reverse=True)
    all_errors = all_errors[:max_events]

    result = {
        'instanceId': instance_id,
        'logGroupName': log_group_name,
        'region': region,
        'timeRange': {
            'hoursBack': hours_back
        },
        'errorCount': len(all_errors),
        'errors': all_errors,
        'searchPatterns': error_patterns
    }

    return json.dumps(result, indent=2)

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

        # Get all log groups that match the EC2 pattern
        response = logs_client.describe_log_groups(
            logGroupNamePrefix="/ec2/"
        )

        all_results = []

        for log_group in response.get('logGroups', []):
            log_group_name = log_group['logGroupName']
            instance_id = log_group_name.replace('/ec2/', '')

            try:
                # Search in this log group
                result_json = await search_cloudwatch_logs(
                    log_group_name=log_group_name,
                    search_term=search_term,
                    region=region,
                    hours_back=hours_back,
                    max_events=max_events
                )

                result_data = json.loads(result_json)

                if result_data.get('success', True) and result_data.get('eventCount', 0) > 0:
                    all_results.append({
                        'instanceId': instance_id,
                        'logGroupName': log_group_name,
                        'eventCount': result_data['eventCount'],
                        'events': result_data['events']
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
    log_group_name = f"/ec2/{instance_id}"

    try:
        # Get log streams and basic info
        streams_result = await list_cloudwatch_log_streams(
            log_group_name=log_group_name,
            region=region,
            max_streams=100
        )

        streams_data = json.loads(streams_result)

        summary = {
            'instanceId': instance_id,
            'logGroupName': log_group_name,
            'region': region,
            'analysisTimeRange': f"Last {hours_back} hours",
            'logStreams': streams_data.get('logStreams', []),
            'streamCount': streams_data.get('logStreamCount', 0)
        }

        return json.dumps(summary, indent=2)

    except Exception as e:
        logger.error(f"Error getting EC2 log summary: {e}")
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
async def get_ec2_instance_details(instance_id: str, region: str = "us-east-1") -> str:
    """Get detailed information about an EC2 instance
    
    Args:
        instance_id: The EC2 instance ID
        region: AWS region (default: us-east-1)
    """
    try:
        ec2 = boto3.client('ec2', region_name=region)
        response = ec2.describe_instances(InstanceIds=[instance_id])
        
        if not response['Reservations']:
            return json.dumps({"success": False, "error": "Instance not found"}, indent=2)
        
        instance = response['Reservations'][0]['Instances'][0]
        
        # Get instance name from tags
        name = "N/A"
        env = "N/A"
        if 'Tags' in instance:
            for tag in instance['Tags']:
                if tag['Key'] == 'Name':
                    name = tag['Value']
                elif tag['Key'] == 'Env':
                    env = tag['Value']
        
        detailed_info = {
            'InstanceId': instance['InstanceId'],
            'Name': name,
            'Environment': env,
            'InstanceType': instance['InstanceType'],
            'State': instance['State']['Name'],
            'LaunchTime': instance['LaunchTime'].isoformat(),
            'Platform': instance.get('Platform', 'Linux/UNIX'),
            'Architecture': instance['Architecture'],
            'PublicIpAddress': instance.get('PublicIpAddress', 'N/A'),
            'PrivateIpAddress': instance.get('PrivateIpAddress', 'N/A'),
            'AvailabilityZone': instance['Placement']['AvailabilityZone'],
            'VpcId': instance.get('VpcId', 'N/A'),
            'SubnetId': instance.get('SubnetId', 'N/A'),
            'SecurityGroups': [sg['GroupName'] for sg in instance.get('SecurityGroups', [])],
            'KeyName': instance.get('KeyName', 'N/A'),
            'IamInstanceProfile': instance.get('IamInstanceProfile', {}).get('Arn', 'N/A'),
            'BlockDeviceMappings': instance.get('BlockDeviceMappings', []),
            'EbsOptimized': instance.get('EbsOptimized', False),
            'EnaSupport': instance.get('EnaSupport', False),
            'Hypervisor': instance.get('Hypervisor', 'N/A'),
            'ClientToken': instance.get('ClientToken', 'N/A')
        }
        
        return json.dumps(detailed_info, indent=2)
        
    except Exception as e:
        logger.error(f"Error getting EC2 instance details for {instance_id}: {e}")
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool()
async def get_ec2_syslog_recent(
    instance_id: str,
    region: str = "us-east-1",
    num_entries: int = 20,
    hours_back: int = 24
) -> str:
    """Get recent syslog entries for an EC2 instance
    
    Args:
        instance_id: EC2 instance ID
        region: AWS region (default: us-east-1)
        num_entries: Number of recent log entries to retrieve (default: 20)
        hours_back: How many hours back to search (default: 24)
    """
    # Try multiple possible log group patterns
    possible_log_groups = [
        f"/aws/ec2/i-{instance_id}",
        f"/aws/ec2/{instance_id}",
        f"/ec2/{instance_id}",
        f"/ec2/{instance_id}/syslog",
        f"/var/log/syslog",
        f"/aws/ec2/syslog"
    ]
    
    for log_group_name in possible_log_groups:
        try:
            result = await get_cloudwatch_logs(
                log_group_name=log_group_name,
                log_stream_name="syslog",
                region=region,
                hours_back=hours_back,
                max_events=num_entries,
                start_from_head=False
            )
            
            # Parse the result to check if we got logs
            result_data = json.loads(result)
            if result_data.get('success', True) and result_data.get('eventCount', 0) > 0:
                return result
                
        except Exception as e:
            logger.debug(f"Log group {log_group_name} not found or error: {e}")
            continue
    
    # If no CloudWatch logs found, return helpful message
    return json.dumps({
        "success": False,
        "error": "No CloudWatch log groups found for this instance",
        "instanceId": instance_id,
        "suggestion": "CloudWatch agent may not be installed or configured on this instance",
        "alternativeMethods": [
            f"SSH: ssh -i your-key.pem ec2-user@<public-ip>",
            f"Then run: sudo tail -n {num_entries} /var/log/syslog",
            "Or use Systems Manager Session Manager if configured"
        ],
        "triedLogGroups": possible_log_groups
    }, indent=2)

@mcp.tool()
async def find_ec2_by_name(name: str, region: str = "us-east-1") -> str:
    """Find EC2 instances by name tag
    
    Args:
        name: Instance name to search for (partial matches allowed)
        region: AWS region (default: us-east-1)
    """
    try:
        ec2 = boto3.client('ec2', region_name=region)
        
        # Search for instances with name tag containing the search term
        response = ec2.describe_instances(
            Filters=[
                {
                    'Name': 'tag:Name',
                    'Values': [f'*{name}*']
                },
                {
                    'Name': 'instance-state-name',
                    'Values': ['running', 'stopped', 'stopping', 'starting']
                }
            ]
        )
        
        instances = []
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                # Get instance name from tags
                instance_name = "N/A"
                if 'Tags' in instance:
                    for tag in instance['Tags']:
                        if tag['Key'] == 'Name':
                            instance_name = tag['Value']
                            break
                
                instances.append({
                    'InstanceId': instance['InstanceId'],
                    'Name': instance_name,
                    'InstanceType': instance['InstanceType'],
                    'State': instance['State']['Name'],
                    'PublicIpAddress': instance.get('PublicIpAddress', 'N/A'),
                    'PrivateIpAddress': instance.get('PrivateIpAddress', 'N/A'),
                    'LaunchTime': instance['LaunchTime'].isoformat()
                })
        
        result = {
            'searchTerm': name,
            'region': region,
            'instanceCount': len(instances),
            'instances': instances
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        logger.error(f"Error finding EC2 instances by name '{name}': {e}")
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool()
async def check_cloudwatch_agent_status(instance_id: str, region: str = "us-east-1") -> str:
    """Check if CloudWatch agent is configured for an EC2 instance
    
    Args:
        instance_id: EC2 instance ID
        region: AWS region (default: us-east-1)
    """
    try:
        logs_client = boto3.client('logs', region_name=region)
        
        # Common log group patterns for EC2 instances
        log_group_patterns = [
            f"/aws/ec2/i-{instance_id}",
            f"/aws/ec2/{instance_id}",
            f"/ec2/{instance_id}",
            f"/aws/amazoncloudwatch-agent/{instance_id}"
        ]
        
        found_groups = []
        
        for pattern in log_group_patterns:
            try:
                response = logs_client.describe_log_groups(
                    logGroupNamePrefix=pattern
                )
                
                for group in response.get('logGroups', []):
                    found_groups.append({
                        'logGroupName': group['logGroupName'],
                        'creationTime': datetime.fromtimestamp(group['creationTime'] / 1000, tz=timezone.utc).isoformat(),
                        'storedBytes': group.get('storedBytes', 0),
                        'retentionInDays': group.get('retentionInDays', 'Never expire')
                    })
                    
            except Exception as e:
                logger.debug(f"No log groups found for pattern {pattern}: {e}")
                continue
        
        result = {
            'instanceId': instance_id,
            'region': region,
            'cloudWatchAgentConfigured': len(found_groups) > 0,
            'logGroupsFound': len(found_groups),
            'logGroups': found_groups,
            'status': 'Configured' if found_groups else 'Not configured or no recent logs'
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        logger.error(f"Error checking CloudWatch agent status: {e}")
        return json.dumps({"success": False, "error": str(e)}, indent=2)
    
    
@mcp.tool()
async def debug_log_group_contents(log_group_name: str, region: str = "us-east-1") -> str:
    """Debug function to see what's actually in a log group
    
    Args:
        log_group_name: Exact log group name (e.g., /ec2/i-0106032745016ca2e)
        region: AWS region
    """
    try:
        logs_client = boto3.client('logs', region_name=region)
        
        # First, verify the log group exists
        try:
            group_response = logs_client.describe_log_groups(
                logGroupNamePrefix=log_group_name,
                limit=1
            )
            
            if not group_response.get('logGroups'):
                return json.dumps({
                    "success": False,
                    "error": f"Log group {log_group_name} not found"
                }, indent=2)
                
            group_info = group_response['logGroups'][0]
            
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Error accessing log group: {str(e)}"
            }, indent=2)
        
        # Get log streams
        streams_response = logs_client.describe_log_streams(
            logGroupName=log_group_name,
            orderBy='LastEventTime',
            descending=True,
            limit=10
        )
        
        streams = []
        for stream in streams_response.get('logStreams', []):
            stream_info = {
                'logStreamName': stream['logStreamName'],
                'lastEventTime': datetime.fromtimestamp(stream.get('lastEventTime', 0) / 1000, tz=timezone.utc).isoformat() if stream.get('lastEventTime') else 'N/A',
                'storedBytes': stream.get('storedBytes', 0)
            }
            streams.append(stream_info)
        
        # Try to get some recent events from any stream
        recent_events = []
        if streams:
            try:
                events_response = logs_client.filter_log_events(
                    logGroupName=log_group_name,
                    limit=5,
                    startTime=int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp() * 1000)
                )
                
                for event in events_response.get('events', []):
                    recent_events.append({
                        'timestamp': datetime.fromtimestamp(event['timestamp'] / 1000, tz=timezone.utc).isoformat(),
                        'logStreamName': event['logStreamName'],
                        'message': event['message'][:200] + '...' if len(event['message']) > 200 else event['message']
                    })
                    
            except Exception as e:
                recent_events = [{"error": f"Could not retrieve events: {str(e)}"}]
        
        result = {
            'logGroupName': log_group_name,
            'logGroupInfo': {
                'creationTime': datetime.fromtimestamp(group_info['creationTime'] / 1000, tz=timezone.utc).isoformat(),
                'storedBytes': group_info.get('storedBytes', 0),
                'retentionInDays': group_info.get('retentionInDays', 'Never expire')
            },
            'streamCount': len(streams),
            'logStreams': streams,
            'recentEvents': recent_events,
            'success': True
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        logger.error(f"Error debugging log group {log_group_name}: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "logGroupName": log_group_name
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
