# Here's the integration of SSM functionality into your AWS MCP Server:

# ```python
#!/usr/bin/env python3
"""AWS MCP Server - A Model Context Protocol server for AWS operations using FastMCP"""

import asyncio
import json
import logging
import argparse
import sys
import time
from typing import Any, Dict, List, Optional, Union
import boto3
from datetime import datetime, timedelta, timezone
from botocore.exceptions import ClientError

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

# Utility functions
def safe_json_response(success: bool = True, **data) -> str:
    """Create a consistent JSON response"""
    response = {"success": success, **data}
    return json.dumps(response, indent=2)

def handle_aws_error(operation: str, error: Exception, **context) -> str:
    """Handle AWS API errors consistently"""
    logger.error(f"Error in {operation}: {error}")
    return safe_json_response(False, error=str(error), operation=operation, **context)

# SSM Operations
@mcp.tool()
async def list_ssm_managed_instances(region: str = "us-east-1") -> str:
    """List SSM managed instances"""
    try:
        ssm = boto3.client('ssm', region_name=region)
        response = ssm.describe_instance_information()
        
        instances = []
        for instance in response.get('InstanceInformationList', []):
            instances.append({
                'InstanceId': instance['InstanceId'],
                'PingStatus': instance['PingStatus'],
                'LastPingDateTime': instance.get('LastPingDateTime', '').isoformat() if instance.get('LastPingDateTime') else 'N/A',
                'AgentVersion': instance.get('AgentVersion', 'N/A'),
                'PlatformType': instance.get('PlatformType', 'N/A'),
                'PlatformName': instance.get('PlatformName', 'N/A'),
                'PlatformVersion': instance.get('PlatformVersion', 'N/A'),
                'IPAddress': instance.get('IPAddress', 'N/A'),
                'ComputerName': instance.get('ComputerName', 'N/A'),
                'AssociationStatus': instance.get('AssociationStatus', 'N/A'),
                'LastAssociationExecutionDate': instance.get('LastAssociationExecutionDate', '').isoformat() if instance.get('LastAssociationExecutionDate') else 'N/A',
                'LastSuccessfulAssociationExecutionDate': instance.get('LastSuccessfulAssociationExecutionDate', '').isoformat() if instance.get('LastSuccessfulAssociationExecutionDate') else 'N/A'
            })
        
        return safe_json_response(True, region=region, instances=instances, count=len(instances))
    except Exception as e:
        return handle_aws_error("list_ssm_managed_instances", e, region=region)

@mcp.tool()
async def run_ssm_command(
    instance_ids: str,  # Comma-separated list or single instance ID
    commands: str,      # Commands to run (one per line or semicolon-separated)
    region: str = "us-east-1",
    document_name: str = "AWS-RunShellScript",
    timeout_seconds: int = 300,
    working_directory: Optional[str] = None,
    wait_for_completion: bool = True,
    max_wait_time: int = 300
) -> str:
    """Run commands on EC2 instances via SSM
    
    Args:
        instance_ids: Comma-separated instance IDs (e.g., "i-1234567890abcdef0,i-0987654321fedcba0")
        commands: Commands to run, separated by newlines or semicolons
        region: AWS region
        document_name: SSM document to use (default: AWS-RunShellScript)
        timeout_seconds: Command timeout in seconds
        working_directory: Working directory for command execution
        wait_for_completion: Whether to wait for command completion
        max_wait_time: Maximum time to wait for completion
    """
    try:
        ssm = boto3.client('ssm', region_name=region)
        
        # Parse instance IDs
        instance_id_list = [id.strip() for id in instance_ids.split(',')]
        
        # Parse commands
        if '\n' in commands:
            command_list = [cmd.strip() for cmd in commands.split('\n') if cmd.strip()]
        else:
            command_list = [cmd.strip() for cmd in commands.split(';') if cmd.strip()]
        
        # Prepare parameters
        parameters = {'commands': command_list}
        if working_directory:
            parameters['workingDirectory'] = [working_directory]
        
        # Send command
        response = ssm.send_command(
            InstanceIds=instance_id_list,
            DocumentName=document_name,
            Parameters=parameters,
            TimeoutSeconds=timeout_seconds
        )
        
        command_id = response['Command']['CommandId']
        
        if not wait_for_completion:
            return safe_json_response(
                True,
                command_id=command_id,
                instance_ids=instance_id_list,
                commands=command_list,
                message=f"Command sent successfully. Use get_ssm_command_output to check results."
            )
        
        # Wait for completion and get results
        results = []
        for instance_id in instance_id_list:
            output = await _get_ssm_command_output_internal(
                ssm, command_id, instance_id, wait_for_completion, max_wait_time
            )
            results.append(output)
        
        return safe_json_response(
            True,
            command_id=command_id,
            commands=command_list,
            results=results
        )
        
    except Exception as e:
        return handle_aws_error("run_ssm_command", e, instance_ids=instance_ids, commands=commands)

async def _get_ssm_command_output_internal(
    ssm_client,
    command_id: str,
    instance_id: str,
    wait_for_completion: bool = True,
    max_wait_time: int = 300
) -> Dict:
    """Internal function to get command output"""
    try:
        if wait_for_completion:
            await _wait_for_command_completion(ssm_client, command_id, instance_id, max_wait_time)
        
        response = ssm_client.get_command_invocation(
            CommandId=command_id,
            InstanceId=instance_id
        )
        
        return {
            'command_id': command_id,
            'instance_id': instance_id,
            'status': response.get('Status'),
            'status_details': response.get('StatusDetails'),
            'standard_output': response.get('StandardOutputContent', ''),
            'standard_error': response.get('StandardErrorContent', ''),
            'response_code': response.get('ResponseCode'),
            'execution_start_time': response.get('ExecutionStartDateTime', '').isoformat() if response.get('ExecutionStartDateTime') else 'N/A',
            'execution_end_time': response.get('ExecutionEndDateTime', '').isoformat() if response.get('ExecutionEndDateTime') else 'N/A'
        }
        
    except ClientError as e:
        return {
            'error': str(e),
            'command_id': command_id,
            'instance_id': instance_id
        }

async def _wait_for_command_completion(ssm_client, command_id: str, instance_id: str, max_wait_time: int):
    """Wait for command completion"""
    start_time = time.time()
    
    while time.time() - start_time < max_wait_time:
        try:
            response = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )
            
            status = response.get('Status')
            if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                logger.info(f"Command {command_id} completed with status: {status}")
                return
            
            logger.info(f"Command {command_id} status: {status}. Waiting...")
            await asyncio.sleep(5)
            
        except ClientError as e:
            if 'InvocationDoesNotExist' in str(e):
                logger.info(f"Command {command_id} still initializing...")
                await asyncio.sleep(5)
                continue
            else:
                raise e
    
    logger.warning(f"Command {command_id} did not complete within {max_wait_time} seconds")

@mcp.tool()
async def get_ssm_command_output(
    command_id: str,
    instance_id: str,
    region: str = "us-east-1",
    wait_for_completion: bool = True,
    max_wait_time: int = 300
) -> str:
    """Get output of an SSM command execution
    
    Args:
        command_id: Command ID returned by run_ssm_command
        instance_id: Instance ID where command was executed
        region: AWS region
        wait_for_completion: Whether to wait for command completion
        max_wait_time: Maximum time to wait for completion
    """
    try:
        ssm = boto3.client('ssm', region_name=region)
        output = await _get_ssm_command_output_internal(
            ssm, command_id, instance_id, wait_for_completion, max_wait_time
        )
        
        if 'error' in output:
            return safe_json_response(False, **output)
        else:
            return safe_json_response(True, **output)
            
    except Exception as e:
        return handle_aws_error("get_ssm_command_output", e, command_id=command_id, instance_id=instance_id)

@mcp.tool()
async def list_ssm_commands(
    region: str = "us-east-1",
    instance_id: Optional[str] = None,
    max_results: int = 25
) -> str:
    """List recent SSM commands
    
    Args:
        region: AWS region
        instance_id: Filter by instance ID (optional)
        max_results: Maximum number of results to return
    """
    try:
        ssm = boto3.client('ssm', region_name=region)
        
        params = {'MaxResults': max_results}
        if instance_id:
            params['InstanceId'] = instance_id
        
        response = ssm.list_commands(**params)
        commands = []
        
        for cmd in response.get('Commands', []):
            commands.append({
                'CommandId': cmd['CommandId'],
                'DocumentName': cmd['DocumentName'],
                'Comment': cmd.get('Comment', ''),
                'ExpiresAfter': cmd.get('ExpiresAfter', '').isoformat() if cmd.get('ExpiresAfter') else 'N/A',
                'Parameters': cmd.get('Parameters', {}),
                'InstanceIds': cmd.get('InstanceIds', []),
                'Targets': cmd.get('Targets', []),
                'RequestedDateTime': cmd.get('RequestedDateTime', '').isoformat() if cmd.get('RequestedDateTime') else 'N/A',
                'Status': cmd.get('Status', 'N/A'),
                'StatusDetails': cmd.get('StatusDetails', 'N/A'),
                'OutputS3Region': cmd.get('OutputS3Region', 'N/A'),
                'OutputS3BucketName': cmd.get('OutputS3BucketName', 'N/A'),
                'OutputS3KeyPrefix': cmd.get('OutputS3KeyPrefix', 'N/A'),
                'MaxConcurrency': cmd.get('MaxConcurrency', 'N/A'),
                'MaxErrors': cmd.get('MaxErrors', 'N/A'),
                'TargetCount': cmd.get('TargetCount', 0),
                'CompletedCount': cmd.get('CompletedCount', 0),
                'ErrorCount': cmd.get('ErrorCount', 0),
                'DeliveryTimedOutCount': cmd.get('DeliveryTimedOutCount', 0),
                'ServiceRole': cmd.get('ServiceRole', 'N/A'),
                'NotificationConfig': cmd.get('NotificationConfig', {}),
                'CloudWatchOutputConfig': cmd.get('CloudWatchOutputConfig', {}),
                'TimeoutSeconds': cmd.get('TimeoutSeconds', 0)
            })
        
        return safe_json_response(
            True,
            region=region,
            instance_id=instance_id,
            commands=commands,
            count=len(commands)
        )
        
    except Exception as e:
        return handle_aws_error("list_ssm_commands", e, region=region, instance_id=instance_id)

@mcp.tool()
async def run_quick_ssm_command(
    instance_id: str,
    command: str,
    region: str = "us-east-1"
) -> str:
    """Run a quick single command on an instance and get the output
    
    Args:
        instance_id: Single instance ID
        command: Single command to run
        region: AWS region
    """
    try:
        result = await run_ssm_command(
            instance_ids=instance_id,
            commands=command,
            region=region,
            wait_for_completion=True,
            max_wait_time=60
        )
        
        # Parse the result and format it for quick viewing
        result_data = json.loads(result)
        if result_data.get('success') and result_data.get('results'):
            output = result_data['results'][0]
            
            formatted_output = f"""
Command: {command}
Instance: {instance_id}
Status: {output.get('status', 'N/A')}
Response Code: {output.get('response_code', 'N/A')}

Standard Output:
{output.get('standard_output', 'No output')}

Standard Error:
{output.get('standard_error', 'No errors')}
            """.strip()
            
            return safe_json_response(
                True,
                command=command,
                instance_id=instance_id,
                formatted_output=formatted_output,
                raw_output=output
            )
        else:
            return result
            
    except Exception as e:
        return handle_aws_error("run_quick_ssm_command", e, instance_id=instance_id, command=command)

@mcp.tool()
async def check_ssm_connectivity(instance_id: str, region: str = "us-east-1") -> str:
    """Check if an instance is reachable via SSM
    
    Args:
        instance_id: Instance ID to check
        region: AWS region
    """
    try:
        ssm = boto3.client('ssm', region_name=region)
        
        # Check if instance is in SSM managed instances
        response = ssm.describe_instance_information(
            Filters=[
                {
                    'Key': 'InstanceIds',
                    'Values': [instance_id]
                }
            ]
        )
        
        instances = response.get('InstanceInformationList', [])
        
        if not instances:
            return safe_json_response(
                False,
                instance_id=instance_id,
                error="Instance not found in SSM managed instances",
                suggestion="Ensure SSM agent is installed and IAM role has SSM permissions"
            )
        
        instance_info = instances[0]
        ping_status = instance_info.get('PingStatus', 'Unknown')
        
        # Try a simple test command
        test_result = None
        if ping_status == 'Online':
            try:
                test_command_result = await run_quick_ssm_command(
                    instance_id=instance_id,
                    command="echo 'SSM connectivity test successful'",
                    region=region
                )
                test_data = json.loads(test_command_result)
                test_result = test_data.get('success', False)
            except Exception as test_error:
                test_result = f"Test command failed: {str(test_error)}"
        
        return safe_json_response(
            True,
            instance_id=instance_id,
            ping_status=ping_status,
            agent_version=instance_info.get('AgentVersion', 'N/A'),
            platform_type=instance_info.get('PlatformType', 'N/A'),
            platform_name=instance_info.get('PlatformName', 'N/A'),
            last_ping_time=instance_info.get('LastPingDateTime', '').isoformat() if instance_info.get('LastPingDateTime') else 'N/A',
            ip_address=instance_info.get('IPAddress', 'N/A'),
            computer_name=instance_info.get('ComputerName', 'N/A'),
            test_command_success=test_result,
            ssm_ready=ping_status == 'Online' and test_result is True
        )
        
    except Exception as e:
        return handle_aws_error("check_ssm_connectivity", e, instance_id=instance_id)

# Common SSM command shortcuts
@mcp.tool()
async def get_instance_system_info(instance_id: str, region: str = "us-east-1") -> str:
    """Get basic system information from an instance via SSM"""
    commands = [
        "echo '=== SYSTEM INFO ==='",
        "uname -a",
        "echo '=== DISK USAGE ==='",
        "df -h",
        "echo '=== MEMORY USAGE ==='",
        "free -h",
        "echo '=== UPTIME ==='",
        "uptime",
        "echo '=== RUNNING PROCESSES ==='",
        "ps aux --sort=-%cpu | head -10"
    ]
    
    return await run_ssm_command(
        instance_ids=instance_id,
        commands='\n'.join(commands),
        region=region,
        wait_for_completion=True
    )

@mcp.tool()
async def get_instance_logs_via_ssm(
    instance_id: str,
    log_file: str = "/var/log/syslog",
    lines: int = 50,
    region: str = "us-east-1"
) -> str:
    """Get log files from an instance via SSM
    
    Args:
        instance_id: Instance ID
        log_file: Path to log file (default: /var/log/syslog)
        lines: Number of lines to retrieve (default: 50)
        region: AWS region
    """
    command = f"tail -n {lines} {log_file}"
    
    return await run_quick_ssm_command(
        instance_id=instance_id,
        command=command,
        region=region
    )

# [Keep all the existing functions from the previous code...]
# EC2 Operations
@mcp.tool()
async def list_ec2_instances(region: str = "us-east-1") -> str:
    """List EC2 instances in the specified region"""
    try:
        ec2 = boto3.client('ec2', region_name=region)
        response = ec2.describe_instances()
        instances = []
        
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                # Get instance name from tags
                name = "N/A"
                env = "N/A"
                if 'Tags' in instance:
                    for tag in instance['Tags']:
                        if tag['Key'] == 'Name':
                            name = tag['Value']
                        elif tag['Key'] == 'Env':
                            env = tag['Value']
                
                instances.append({
                    'InstanceId': instance['InstanceId'],
                    'Name': name,
                    'Environment': env,
                    'InstanceType': instance['InstanceType'],
                    'State': instance['State']['Name'],
                    'LaunchTime': instance['LaunchTime'].isoformat(),
                    'PrivateIpAddress': instance.get('PrivateIpAddress', 'N/A'),
                    'PublicIpAddress': instance.get('PublicIpAddress', 'N/A'),
                })
        
        return safe_json_response(True, region=region, instances=instances, count=len(instances))
    except Exception as e:
        return handle_aws_error("list_ec2_instances", e, region=region)

@mcp.tool()
async def get_ec2_instance_details(instance_id: str, region: str = "us-east-1") -> str:
    """Get detailed information about an EC2 instance"""
    try:
        ec2 = boto3.client('ec2', region_name=region)
        response = ec2.describe_instances(InstanceIds=[instance_id])
        
        if not response['Reservations']:
            return safe_json_response(False, error="Instance not found", instance_id=instance_id)
        
        instance = response['Reservations'][0]['Instances'][0]
        
        # Get instance name and env from tags
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
        }
        
        return safe_json_response(True, **detailed_info)
    except Exception as e:
        return handle_aws_error("get_ec2_instance_details", e, instance_id=instance_id)

@mcp.tool()
async def find_ec2_by_name(name: str, region: str = "us-east-1") -> str:
    """Find EC2 instances by name tag (partial matches allowed)"""
    try:
        ec2 = boto3.client('ec2', region_name=region)
        response = ec2.describe_instances(
            Filters=[
                {'Name': 'tag:Name', 'Values': [f'*{name}*']},
                {'Name': 'instance-state-name', 'Values': ['running', 'stopped', 'stopping', 'starting']}
            ]
        )
        
        instances = []
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
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
        
        return safe_json_response(True, searchTerm=name, region=region, instances=instances, count=len(instances))
    except Exception as e:
        return handle_aws_error("find_ec2_by_name", e, name=name, region=region)

@mcp.tool()
async def start_ec2_instance(instance_id: str, region: str = "us-east-1") -> str:
    """Start an EC2 instance"""
    try:
        ec2 = boto3.client('ec2', region_name=region)
        response = ec2.start_instances(InstanceIds=[instance_id])
        starting_instance = response['StartingInstances'][0]
        
        return safe_json_response(
            True,
            message=f"Starting instance {instance_id} in {region}",
            instance_id=instance_id,
            current_state=starting_instance['CurrentState']['Name'],
            previous_state=starting_instance['PreviousState']['Name']
        )
    except Exception as e:
        return handle_aws_error("start_ec2_instance", e, instance_id=instance_id, region=region)

@mcp.tool()
async def stop_ec2_instance(instance_id: str, region: str = "us-east-1") -> str:
    """Stop an EC2 instance"""
    try:
        ec2 = boto3.client('ec2', region_name=region)
        response = ec2.stop_instances(InstanceIds=[instance_id])
        stopping_instance = response['StoppingInstances'][0]
        
        return safe_json_response(
            True,
            message=f"Stopping instance {instance_id} in {region}",
            instance_id=instance_id,
            current_state=stopping_instance['CurrentState']['Name'],
            previous_state=stopping_instance['PreviousState']['Name']
        )
    except Exception as e:
        return handle_aws_error("stop_ec2_instance", e, instance_id=instance_id, region=region)

# S3 Operations
@mcp.tool()
async def list_s3_buckets(region: Optional[str] = None) -> str:
    """List S3 buckets"""
    try:
        s3 = boto3.client('s3', region_name=region) if region else boto3.client('s3')
        response = s3.list_buckets()
        buckets = []
        
        for bucket in response['Buckets']:
            bucket_info = {
                'Name': bucket['Name'],
                'CreationDate': bucket['CreationDate'].isoformat()
            }
            
            if not region:
                try:
                    bucket_region = s3.get_bucket_location(Bucket=bucket['Name'])
                    bucket_info['Region'] = bucket_region.get('LocationConstraint', 'us-east-1')
                except:
                    bucket_info['Region'] = 'unknown'
            
            buckets.append(bucket_info)
        
        return safe_json_response(True, buckets=buckets, count=len(buckets))
    except Exception as e:
        return handle_aws_error("list_s3_buckets", e, region=region)

@mcp.tool()
async def create_s3_bucket(bucket_name: str, region: str = "us-east-1") -> str:
    """Create a new S3 bucket"""
    try:
        s3 = boto3.client('s3', region_name=region)
        
        if region == 'us-east-1':
            response = s3.create_bucket(Bucket=bucket_name)
        else:
            response = s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': region}
            )
        
        return safe_json_response(
            True,
            message=f"Created bucket {bucket_name} in region {region}",
            bucket_name=bucket_name,
            region=region,
            location=response['Location']
        )
    except Exception as e:
        return handle_aws_error("create_s3_bucket", e, bucket_name=bucket_name, region=region)

@mcp.tool()
async def list_s3_objects(bucket_name: str, prefix: str = "", max_keys: int = 100) -> str:
    """List objects in an S3 bucket"""
    try:
        s3 = boto3.client('s3')
        kwargs = {'Bucket': bucket_name, 'MaxKeys': max_keys}
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
        
        return safe_json_response(
            True,
            bucket=bucket_name,
            prefix=prefix,
            objects=objects,
            count=len(objects),
            is_truncated=response.get('IsTruncated', False)
        )
    except Exception as e:
        return handle_aws_error("list_s3_objects", e, bucket_name=bucket_name)

# RDS Operations
@mcp.tool()
async def list_rds_instances(region: str = "us-east-1") -> str:
    """List RDS instances in the specified region"""
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
        
        return safe_json_response(True, region=region, instances=instances, count=len(instances))
    except Exception as e:
        return handle_aws_error("list_rds_instances", e, region=region)

@mcp.tool()
async def describe_rds_instance(instance_identifier: str, region: str = "us-east-1") -> str:
    """Get detailed information about an RDS instance"""
    try:
        rds = boto3.client('rds', region_name=region)
        response = rds.describe_db_instances(DBInstanceIdentifier=instance_identifier)
        
        if not response['DBInstances']:
            return safe_json_response(False, error="Instance not found", instance_identifier=instance_identifier)
        
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
        
        return safe_json_response(True, **detailed_info)
    except Exception as e:
        return handle_aws_error("describe_rds_instance", e, instance_identifier=instance_identifier)

# CloudWatch Logs - Core Functions
async def _get_cloudwatch_logs_core(
    log_group_name: str,
    region: str = "us-east-1",
    log_stream_name: Optional[str] = None,
    hours_back: int = 1,
    max_events: int = 100,
    filter_pattern: Optional[str] = None,
    start_from_head: bool = False
) -> Dict:
    """Core function to get CloudWatch logs - returns dict for internal use"""
    try:
        logs_client = boto3.client('logs', region_name=region)
        
        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours_back)
        start_time_ms = int(start_time.timestamp() * 1000)
        end_time_ms = int(end_time.timestamp() * 1000)
        
        # Prepare filter parameters
        filter_params = {
            'logGroupName': log_group_name,
            'startTime': start_time_ms,
            'endTime': end_time_ms,
            'limit': min(max_events, 1000)
        }
        
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
            
            filter_params['limit'] = min(1000, max_events - len(events))
            response = logs_client.filter_log_events(**filter_params)
            
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
        
        return {
            'success': True,
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
            'events': events,
            'hasMoreEvents': next_token is not None
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'logGroupName': log_group_name,
            'logStreamName': log_stream_name
        }

@mcp.tool()
async def list_cloudwatch_log_groups(region: str = "us-east-1", max_groups: int = 1000) -> str:
    """List CloudWatch log groups in the specified region"""
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
        
        return safe_json_response(True, region=region, logGroups=log_groups, count=len(log_groups))
    except Exception as e:
        return handle_aws_error("list_cloudwatch_log_groups", e, region=region)

@mcp.tool()
async def list_cloudwatch_log_streams(
    log_group_name: str,
    region: str = "us-east-1",
    max_streams: int = 50,
    order_by: str = "LastEventTime"
) -> str:
    """List log streams in a CloudWatch log group"""
    try:
        logs_client = boto3.client('logs', region_name=region)
        
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
                
                # Add optional timestamp fields
                for time_field in ['firstEventTime', 'lastEventTime', 'lastIngestionTime']:
                    if time_field in stream:
                        stream_info[time_field] = datetime.fromtimestamp(stream[time_field] / 1000, tz=timezone.utc).isoformat()
                
                if 'uploadSequenceToken' in stream:
                    stream_info['uploadSequenceToken'] = stream['uploadSequenceToken']
                
                log_streams.append(stream_info)
            
            next_token = response.get('nextToken')
            if not next_token:
                break
        
        return safe_json_response(
            True,
            logGroupName=log_group_name,
            region=region,
            orderBy=order_by,
            logStreams=log_streams,
            count=len(log_streams)
        )
    except Exception as e:
        return handle_aws_error("list_cloudwatch_log_streams", e, log_group_name=log_group_name)

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
    """Get CloudWatch logs from a log group and optionally specific log stream"""
    result = await _get_cloudwatch_logs_core(
        log_group_name=log_group_name,
        region=region,
        log_stream_name=log_stream_name,
        hours_back=hours_back,
        max_events=max_events,
        filter_pattern=filter_pattern,
        start_from_head=start_from_head
    )
    return json.dumps(result, indent=2)

@mcp.tool()
async def search_cloudwatch_logs(
    log_group_name: str,
    search_term: str,
    region: str = "us-east-1",
    hours_back: int = 24,
    max_events: int = 1000,
    log_stream_name: Optional[str] = None
) -> str:
    """Search CloudWatch logs for specific terms"""
    result = await _get_cloudwatch_logs_core(
        log_group_name=log_group_name,
        region=region,
        log_stream_name=log_stream_name,
        hours_back=hours_back,
        max_events=max_events,
        filter_pattern=f'"{search_term}"'
    )
    
    # Add search-specific metadata
    if result['success']:
        result['searchTerm'] = search_term
    
    return json.dumps(result, indent=2)

@mcp.tool()
async def get_cloudwatch_log_insights(
    log_group_name: str,
    query: str,
    region: str = "us-east-1",
    hours_back: int = 24,
    max_results: int = 1000
) -> str:
    """Run CloudWatch Logs Insights query"""
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
        max_wait_time = 30
        poll_interval = 1
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
                
                return safe_json_response(
                    True,
                    logGroupName=log_group_name,
                    query=query,
                    region=region,
                    queryId=query_id,
                    status=status,
                    timeRange={
                        'start': start_time.isoformat(),
                        'end': end_time.isoformat(),
                        'hoursBack': hours_back
                    },
                    results=results,
                    count=len(results),
                    statistics=result_response.get('statistics', {})
                )
            elif status in ['Failed', 'Cancelled']:
                return safe_json_response(False, error=f"Query {status.lower()}", queryId=query_id, status=status)
            
            await asyncio.sleep(poll_interval)
            waited += poll_interval
        
        return safe_json_response(False, error="Query timed out", queryId=query_id, status="Timeout")
    except Exception as e:
        return handle_aws_error("get_cloudwatch_log_insights", e, log_group_name=log_group_name, query=query)

# EC2-specific log functions (using the core function)
@mcp.tool()
async def get_ec2_logs(
    instance_id: str,
    log_stream_name: Optional[str] = None,
    search_term: str = "",
    region: str = "us-east-1",
    hours_back: int = 24,
    max_events: int = 1000
) -> str:
    """Get or search EC2 logs for a specific instance"""
    # Try multiple possible log group patterns
    possible_log_groups = [
        f"/aws/ec2/{instance_id}",
        f"/ec2/{instance_id}",
        f"/aws/ec2/i-{instance_id}",
    ]
    
    for log_group_name in possible_log_groups:
        try:
            if search_term:
                result = await _get_cloudwatch_logs_core(
                    log_group_name=log_group_name,
                    region=region,
                    log_stream_name=log_stream_name,
                    hours_back=hours_back,
                    max_events=max_events,
                    filter_pattern=f'"{search_term}"'
                )
            else:
                result = await _get_cloudwatch_logs_core(
                    log_group_name=log_group_name,
                    region=region,
                    log_stream_name=log_stream_name,
                    hours_back=hours_back,
                    max_events=max_events
                )
            
            if result['success'] and result.get('eventCount', 0) > 0:
                result['instanceId'] = instance_id
                if search_term:
                    result['searchTerm'] = search_term
                return json.dumps(result, indent=2)
        
        except Exception as e:
            logger.debug(f"Log group {log_group_name} not accessible: {e}")
            continue
    
    # If no CloudWatch logs found
    return safe_json_response(
        False,
        error="No CloudWatch log groups found for this instance",
        instanceId=instance_id,
        suggestion="CloudWatch agent may not be installed or configured on this instance",
        triedLogGroups=possible_log_groups
    )

@mcp.tool()
async def get_ec2_log_streams(instance_id: str, region: str = "us-east-1") -> str:
    """Get all log streams for a specific EC2 instance"""
    log_group_name = f"/ec2/{instance_id}"
    return await list_cloudwatch_log_streams(log_group_name=log_group_name, region=region, max_streams=100)

@mcp.tool()
async def get_recent_ec2_errors(
    instance_id: str,
    region: str = "us-east-1",
    hours_back: int = 24,
    max_events: int = 500
) -> str:
    """Get recent error messages from EC2 instance logs"""
    error_patterns = ['ERROR', 'FAILED', 'CRITICAL', 'FATAL', 'Exception']
    all_errors = []
    
    for pattern in error_patterns:
        try:
            result_json = await get_ec2_logs(
                instance_id=instance_id,
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
    
    return safe_json_response(
        True,
        instanceId=instance_id,
        region=region,
        timeRange={'hoursBack': hours_back},
        errors=all_errors,
        count=len(all_errors),
        searchPatterns=error_patterns
    )

@mcp.tool()
async def check_cloudwatch_agent_status(instance_id: str, region: str = "us-east-1") -> str:
    """Check if CloudWatch agent is configured for an EC2 instance"""
    try:
        logs_client = boto3.client('logs', region_name=region)
        
        log_group_patterns = [
            f"/aws/ec2/{instance_id}",
            f"/ec2/{instance_id}",
            f"/aws/amazoncloudwatch-agent/{instance_id}"
        ]
        
        found_groups = []
        
        for pattern in log_group_patterns:
            try:
                response = logs_client.describe_log_groups(logGroupNamePrefix=pattern)
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
        
        return safe_json_response(
            True,
            instanceId=instance_id,
            region=region,
            cloudWatchAgentConfigured=len(found_groups) > 0,
            logGroups=found_groups,
            count=len(found_groups),
            status='Configured' if found_groups else 'Not configured or no recent logs'
        )
    except Exception as e:
        return handle_aws_error("check_cloudwatch_agent_status", e, instance_id=instance_id)

# Utility AWS functions
@mcp.tool()
async def get_aws_regions() -> str:
    """Get list of available AWS regions"""
    try:
        ec2 = boto3.client('ec2', region_name='us-east-1')
        response = ec2.describe_regions()
        regions = [
            {
                'RegionName': region['RegionName'],
                'OptInStatus': region['OptInStatus']
            }
            for region in response['Regions']
        ]
        return safe_json_response(True, regions=regions, count=len(regions))
    except Exception as e:
        return handle_aws_error("get_aws_regions", e)

@mcp.tool()
async def get_aws_account_info() -> str:
    """Get AWS account information"""
    try:
        sts = boto3.client('sts')
        response = sts.get_caller_identity()
        
        return safe_json_response(
            True,
            Account=response.get('Account', 'N/A'),
            UserId=response.get('UserId', 'N/A'),
            Arn=response.get('Arn', 'N/A')
        )
    except Exception as e:
        return handle_aws_error("get_aws_account_info", e)

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
            print(f"Starting AWS MCP Server with HTTP transport on {args.host}:{args.port}", file=sys.stderr)
            asyncio.run(mcp.run_http_async(host=args.host, port=args.port))
        elif args.transport == 'sse':
            print(f"Starting AWS MCP Server with SSE transport on {args.host}:{args.port}", file=sys.stderr)
            asyncio.run(mcp.run_sse_async(host=args.host, port=args.port))
        else:
            print("Starting AWS MCP Server with stdio transport", file=sys.stderr)
            mcp.run()
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
# ```

# ## New SSM Functions Added:

# ### **Core SSM Operations:**
# 1. **`list_ssm_managed_instances`** - List all SSM-managed instances
# 2. **`run_ssm_command`** - Run commands on multiple instances
# 3. **`get_ssm_command_output`** - Get output of previously run commands
# 4. **`list_ssm_commands`** - List recent SSM commands
# 5. **`check_ssm_connectivity`** - Check if an instance is SSM-accessible

# ### **Convenience Functions:**
# 6. **`run_quick_ssm_command`** - Run a single command and get output quickly
# 7. **`get_instance_system_info`** - Get comprehensive system information
# 8. **`get_instance_logs_via_ssm`** - Get log files directly via SSM

# ## Key Features:

# ### **Multi-Instance Support:**
# ```python
# # Run commands on multiple instances
# await run_ssm_command(
#     instance_ids="i-1234567890abcdef0,i-0987654321fedcba0",
#     commands="uptime; df -h; free -m"
# )
# ```

# ### **Flexible Command Input:**
# - Commands can be separated by newlines or semicolons
# - Support for multi-line scripts
# - Working directory specification

# ### **Async Command Execution:**
# - Non-blocking command execution
# - Configurable timeout and wait settings
# - Proper error handling and status reporting

# ### **Built-in System Information:**
# ```python
# # Get comprehensive system info
# await get_instance_system_info("i-1234567890abcdef0")
# ```

# ### **SSM Connectivity Testing:**
# ```python
# # Check if instance is accessible via SSM
# await check_ssm_connectivity("i-1234567890abcdef0")
# ```

# ## Prerequisites:

# 1. **EC2 Instance Requirements:**
#    - SSM Agent installed (pre-installed on newer AMIs)
#    - Instance IAM role with `AmazonSSMManagedInstanceCore` policy
#    - Instance must be reachable (running and network connectivity)

# 2. **AWS Permissions:**
#    - `ssm:DescribeInstanceInformation`
#    - `ssm:SendCommand`
#    - `ssm:GetCommandInvocation`
#    - `ssm:ListCommands`

# The SSM integration provides powerful remote execution capabilities while maintaining the same consistent API design as the rest of your MCP server.