# Here's the updated Lambda function that's compatible with your enhanced AWS MCP Server:

# ```python
import json
import os
import time
import logging
from typing import Optional, Dict, List
import boto3
from botocore.config import Config
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta, timezone
import re

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configure boto3 client with retry settings
config = Config(
    retries=dict(
        max_attempts=10,
        mode='adaptive'
    ),
    read_timeout=300,
    max_pool_connections=50
)

bedrock_client = boto3.client(
    service_name='bedrock-runtime',
    region_name='us-east-1',
    config=config
)

class AWSMCPLambdaClient:
    def __init__(self, region: str = 'us-east-1'):
        """Initialize the AWS MCP Lambda Client"""
        self.region = region
        self.last_request_time = 0
        self.min_request_interval = 1.0
        self.session = None
        self._init_session()
        logger.info(f"AWSMCPLambdaClient initialized for region: {region}")

    def _init_session(self):
        """Initialize HTTP session with retry strategy"""
        self.session = requests.Session()

        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def rate_limit(self):
        """Implement rate limiting for Bedrock API calls"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last_request
            logger.info(f"Rate limiting applied: waiting {sleep_time:.2f} seconds")
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    def get_available_tools(self) -> List[Dict]:
        """Return the list of available AWS tools - updated for enhanced server"""
        with open('lambda_config.json', 'r') as f:
            tools = json.load(f)

        return tools

    def execute_tool(self, tool_name: str, tool_inputs: Dict) -> str:
        """Execute a tool call with enhanced error handling and AWS API calls"""
        try:
            logger.info(f"Executing tool: {tool_name} with inputs: {tool_inputs}")
            
            # Set default region
            region = tool_inputs.get('region', self.region)
            
            # EC2 Operations
            if tool_name == "list_ec2_instances":
                return self._list_ec2_instances(region)
            elif tool_name == "get_ec2_instance_details":
                return self._get_ec2_instance_details(tool_inputs['instance_id'], region)
            elif tool_name == "find_ec2_by_name":
                return self._find_ec2_by_name(tool_inputs['name'], region)
            elif tool_name == "start_ec2_instance":
                return self._start_ec2_instance(tool_inputs['instance_id'], region)
            elif tool_name == "stop_ec2_instance":
                return self._stop_ec2_instance(tool_inputs['instance_id'], region)
            
            # SSM Operations
            elif tool_name == "list_ssm_managed_instances":
                return self._list_ssm_managed_instances(region)
            elif tool_name == "run_ssm_command":
                return self._run_ssm_command(
                    tool_inputs['instance_ids'],
                    tool_inputs['commands'],
                    region,
                    tool_inputs.get('wait_for_completion', True),
                    tool_inputs.get('max_wait_time', 300)
                )
            elif tool_name == "run_quick_ssm_command":
                return self._run_quick_ssm_command(
                    tool_inputs['instance_id'],
                    tool_inputs['command'],
                    region
                )
            elif tool_name == "check_ssm_connectivity":
                return self._check_ssm_connectivity(tool_inputs['instance_id'], region)
            elif tool_name == "get_instance_system_info":
                return self._get_instance_system_info(tool_inputs['instance_id'], region)
            elif tool_name == "get_instance_logs_via_ssm":
                return self._get_instance_logs_via_ssm(
                    tool_inputs['instance_id'],
                    tool_inputs.get('log_file', '/var/log/syslog'),
                    tool_inputs.get('lines', 50),
                    region
                )
            
            # S3 Operations
            elif tool_name == "list_s3_buckets":
                return self._list_s3_buckets(tool_inputs.get('region'))
            elif tool_name == "list_s3_objects":
                return self._list_s3_objects(
                    tool_inputs['bucket_name'],
                    tool_inputs.get('prefix', ''),
                    tool_inputs.get('max_keys', 100)
                )
            elif tool_name == "create_s3_bucket":
                return self._create_s3_bucket(tool_inputs['bucket_name'], region)
            
            # RDS Operations
            elif tool_name == "list_rds_instances":
                return self._list_rds_instances(region)
            elif tool_name == "describe_rds_instance":
                return self._describe_rds_instance(tool_inputs['instance_identifier'], region)
            
            # CloudWatch Logs Operations
            elif tool_name == "list_cloudwatch_log_groups":
                return self._list_cloudwatch_log_groups(
                    region,
                    tool_inputs.get('max_groups', 1000)
                )
            elif tool_name == "list_cloudwatch_log_streams":
                return self._list_cloudwatch_log_streams(
                    tool_inputs['log_group_name'],
                    region,
                    tool_inputs.get('max_streams', 50),
                    tool_inputs.get('order_by', 'LastEventTime')
                )
            elif tool_name == "get_cloudwatch_logs":
                return self._get_cloudwatch_logs(
                    tool_inputs['log_group_name'],
                    tool_inputs.get('log_stream_name'),
                    region,
                    tool_inputs.get('hours_back', 1),
                    tool_inputs.get('max_events', 100),
                    tool_inputs.get('filter_pattern'),
                    tool_inputs.get('start_from_head', False)
                )
            elif tool_name == "search_cloudwatch_logs":
                return self._search_cloudwatch_logs(
                    tool_inputs['log_group_name'],
                    tool_inputs['search_term'],
                    region,
                    tool_inputs.get('hours_back', 24),
                    tool_inputs.get('max_events', 1000),
                    tool_inputs.get('log_stream_name')
                )
            elif tool_name == "get_cloudwatch_log_insights":
                return self._get_cloudwatch_log_insights(
                    tool_inputs['log_group_name'],
                    tool_inputs['query'],
                    region,
                    tool_inputs.get('hours_back', 24),
                    tool_inputs.get('max_results', 1000)
                )
            
            # EC2-specific log functions
            elif tool_name == "get_ec2_logs":
                return self._get_ec2_logs(
                    tool_inputs['instance_id'],
                    tool_inputs.get('log_stream_name'),
                    tool_inputs.get('search_term', ''),
                    region,
                    tool_inputs.get('hours_back', 24),
                    tool_inputs.get('max_events', 1000)
                )
            elif tool_name == "get_ec2_log_streams":
                return self._get_ec2_log_streams(tool_inputs['instance_id'], region)
            elif tool_name == "get_recent_ec2_errors":
                return self._get_recent_ec2_errors(
                    tool_inputs['instance_id'],
                    region,
                    tool_inputs.get('hours_back', 24),
                    tool_inputs.get('max_events', 500)
                )
            elif tool_name == "check_cloudwatch_agent_status":
                return self._check_cloudwatch_agent_status(tool_inputs['instance_id'], region)
            
            # Utility functions
            elif tool_name == "get_aws_regions":
                return self._get_aws_regions()
            elif tool_name == "get_aws_account_info":
                return self._get_aws_account_info()
            
            else:
                return f"Tool {tool_name} not implemented yet."

        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {str(e)}")
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    def _safe_json_response(self, success: bool = True, **data) -> str:
        """Create a consistent JSON response"""
        response = {"success": success, **data}
        return json.dumps(response, indent=2, default=str)

    def _handle_aws_error(self, operation: str, error: Exception, **context) -> str:
        """Handle AWS API errors consistently"""
        logger.error(f"Error in {operation}: {error}")
        return self._safe_json_response(False, error=str(error), operation=operation, **context)

    # EC2 Operations
    def _list_ec2_instances(self, region: str) -> str:
        """List EC2 instances"""
        try:
            ec2 = boto3.client('ec2', region_name=region)
            response = ec2.describe_instances()
            instances = []
            
            for reservation in response['Reservations']:
                for instance in reservation['Instances']:
                    # Get instance name and env from tags
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
            
            return self._safe_json_response(True, region=region, instances=instances, count=len(instances))
        except Exception as e:
            return self._handle_aws_error("list_ec2_instances", e, region=region)

    def _get_ec2_instance_details(self, instance_id: str, region: str) -> str:
        """Get detailed EC2 instance information"""
        try:
            ec2 = boto3.client('ec2', region_name=region)
            response = ec2.describe_instances(InstanceIds=[instance_id])
            
            if not response['Reservations']:
                return self._safe_json_response(False, error="Instance not found", instance_id=instance_id)
            
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
            
            return self._safe_json_response(True, **detailed_info)
        except Exception as e:
            return self._handle_aws_error("get_ec2_instance_details", e, instance_id=instance_id)

    def _find_ec2_by_name(self, name: str, region: str) -> str:
        """Find EC2 instances by name tag"""
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
            
            return self._safe_json_response(True, searchTerm=name, region=region, instances=instances, count=len(instances))
        except Exception as e:
            return self._handle_aws_error("find_ec2_by_name", e, name=name, region=region)

    def _start_ec2_instance(self, instance_id: str, region: str) -> str:
        """Start an EC2 instance"""
        try:
            ec2 = boto3.client('ec2', region_name=region)
            response = ec2.start_instances(InstanceIds=[instance_id])
            starting_instance = response['StartingInstances'][0]
            
            return self._safe_json_response(
                True,
                message=f"Starting instance {instance_id} in {region}",
                instance_id=instance_id,
                current_state=starting_instance['CurrentState']['Name'],
                previous_state=starting_instance['PreviousState']['Name']
            )
        except Exception as e:
            return self._handle_aws_error("start_ec2_instance", e, instance_id=instance_id, region=region)

    def _stop_ec2_instance(self, instance_id: str, region: str) -> str:
        """Stop an EC2 instance"""
        try:
            ec2 = boto3.client('ec2', region_name=region)
            response = ec2.stop_instances(InstanceIds=[instance_id])
            stopping_instance = response['StoppingInstances'][0]
            
            return self._safe_json_response(
                True,
                message=f"Stopping instance {instance_id} in {region}",
                instance_id=instance_id,
                current_state=stopping_instance['CurrentState']['Name'],
                previous_state=stopping_instance['PreviousState']['Name']
            )
        except Exception as e:
            return self._handle_aws_error("stop_ec2_instance", e, instance_id=instance_id, region=region)

    # SSM Operations
    def _list_ssm_managed_instances(self, region: str) -> str:
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
                    'IPAddress': instance.get('IPAddress', 'N/A'),
                })
            
            return self._safe_json_response(True, region=region, instances=instances, count=len(instances))
        except Exception as e:
            return self._handle_aws_error("list_ssm_managed_instances", e, region=region)

    def _run_ssm_command(self, instance_ids: str, commands: str, region: str, 
                        wait_for_completion: bool = True, max_wait_time: int = 300) -> str:
        """Run SSM commands on instances"""
        try:
            ssm = boto3.client('ssm', region_name=region)
            
            # Parse instance IDs and commands
            instance_id_list = [id.strip() for id in instance_ids.split(',')]
            if '\n' in commands:
                command_list = [cmd.strip() for cmd in commands.split('\n') if cmd.strip()]
            else:
                command_list = [cmd.strip() for cmd in commands.split(';') if cmd.strip()]
            
            # Send command
            response = ssm.send_command(
                InstanceIds=instance_id_list,
                DocumentName="AWS-RunShellScript",
                Parameters={'commands': command_list},
                TimeoutSeconds=300
            )
            
            command_id = response['Command']['CommandId']
            
            if not wait_for_completion:
                return self._safe_json_response(
                    True,
                    command_id=command_id,
                    instance_ids=instance_id_list,
                    commands=command_list,
                    message="Command sent successfully. Check results with get_ssm_command_output."
                )
            
            # Wait for completion and get results
            results = []
            for instance_id in instance_id_list:
                # Simple wait logic
                import time
                time.sleep(5)  # Give command time to execute
                
                try:
                    output_response = ssm.get_command_invocation(
                        CommandId=command_id,
                        InstanceId=instance_id
                    )
                    
                    results.append({
                        'instance_id': instance_id,
                        'status': output_response.get('Status'),
                        'standard_output': output_response.get('StandardOutputContent', ''),
                        'standard_error': output_response.get('StandardErrorContent', ''),
                        'response_code': output_response.get('ResponseCode')
                    })
                except Exception as e:
                    results.append({
                        'instance_id': instance_id,
                        'error': str(e)
                    })
            
            return self._safe_json_response(
                True,
                command_id=command_id,
                commands=command_list,
                results=results
            )
            
        except Exception as e:
            return self._handle_aws_error("run_ssm_command", e, instance_ids=instance_ids)

    def _run_quick_ssm_command(self, instance_id: str, command: str, region: str) -> str:
        """Run a quick single command"""
        result = self._run_ssm_command(instance_id, command, region, True, 60)
        
        try:
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
                
                return self._safe_json_response(
                    True,
                    command=command,
                    instance_id=instance_id,
                    formatted_output=formatted_output,
                    raw_output=output
                )
        except:
            pass
        
        return result

    def _check_ssm_connectivity(self, instance_id: str, region: str) -> str:
        """Check SSM connectivity for an instance"""
        try:
            ssm = boto3.client('ssm', region_name=region)
            
            response = ssm.describe_instance_information(
                Filters=[{'Key': 'InstanceIds', 'Values': [instance_id]}]
            )
            
            instances = response.get('InstanceInformationList', [])
            
            if not instances:
                return self._safe_json_response(
                    False,
                    instance_id=instance_id,
                    error="Instance not found in SSM managed instances",
                    suggestion="Ensure SSM agent is installed and IAM role has SSM permissions"
                )
            
            instance_info = instances[0]
            ping_status = instance_info.get('PingStatus', 'Unknown')
            
            return self._safe_json_response(
                True,
                instance_id=instance_id,
                ping_status=ping_status,
                agent_version=instance_info.get('AgentVersion', 'N/A'),
                platform_type=instance_info.get('PlatformType', 'N/A'),
                platform_name=instance_info.get('PlatformName', 'N/A'),
                ssm_ready=ping_status == 'Online'
            )
            
        except Exception as e:
            return self._handle_aws_error("check_ssm_connectivity", e, instance_id=instance_id)

    def _get_instance_system_info(self, instance_id: str, region: str) -> str:
        """Get system information via SSM"""
        commands = [
            "echo '=== SYSTEM INFO ==='",
            "uname -a",
            "echo '=== DISK USAGE ==='", 
            "df -h",
            "echo '=== MEMORY USAGE ==='",
            "free -h",
            "echo '=== UPTIME ==='",
            "uptime"
        ]
        
        return self._run_ssm_command(instance_id, '\n'.join(commands), region, True)

    def _get_instance_logs_via_ssm(self, instance_id: str, log_file: str = "/var/log/syslog", 
                                  lines: int = 50, region: str = "us-east-1") -> str:
        """Get log files via SSM"""
        command = f"tail -n {lines} {log_file}"
        return self._run_quick_ssm_command(instance_id, command, region)

    # S3 Operations
    def _list_s3_buckets(self, region: Optional[str] = None) -> str:
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
            
            return self._safe_json_response(True, buckets=buckets, count=len(buckets))
        except Exception as e:
            return self._handle_aws_error("list_s3_buckets", e, region=region)

    def _list_s3_objects(self, bucket_name: str, prefix: str = "", max_keys: int = 100) -> str:
        """List objects in S3 bucket"""
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
            
            return self._safe_json_response(
                True,
                bucket=bucket_name,
                prefix=prefix,
                objects=objects,
                count=len(objects),
                is_truncated=response.get('IsTruncated', False)
            )
        except Exception as e:
            return self._handle_aws_error("list_s3_objects", e, bucket_name=bucket_name)

    def _create_s3_bucket(self, bucket_name: str, region: str) -> str:
        """Create S3 bucket"""
        try:
            s3 = boto3.client('s3', region_name=region)
            
            if region == 'us-east-1':
                response = s3.create_bucket(Bucket=bucket_name)
            else:
                response = s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': region}
                )
            
            return self._safe_json_response(
                True,
                message=f"Created bucket {bucket_name} in region {region}",
                bucket_name=bucket_name,
                region=region,
                location=response['Location']
            )
        except Exception as e:
            return self._handle_aws_error("create_s3_bucket", e, bucket_name=bucket_name, region=region)

    # RDS Operations
    def _list_rds_instances(self, region: str) -> str:
        """List RDS instances"""
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
            
            return self._safe_json_response(True, region=region, instances=instances, count=len(instances))
        except Exception as e:
            return self._handle_aws_error("list_rds_instances", e, region=region)

    def _describe_rds_instance(self, instance_identifier: str, region: str) -> str:
        """Get detailed RDS instance information"""
        try:
            rds = boto3.client('rds', region_name=region)
            response = rds.describe_db_instances(DBInstanceIdentifier=instance_identifier)
            
            if not response['DBInstances']:
                return self._safe_json_response(False, error="Instance not found", instance_identifier=instance_identifier)
            
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
                'SecurityGroups': [sg['VpcSecurityGroupId'] for sg in instance.get('VpcSecurityGroups', [])],
                'BackupRetentionPeriod': instance['BackupRetentionPeriod'],
            }
            
            return self._safe_json_response(True, **detailed_info)
        except Exception as e:
            return self._handle_aws_error("describe_rds_instance", e, instance_identifier=instance_identifier)

    # CloudWatch Logs Operations
    def _list_cloudwatch_log_groups(self, region: str, max_groups: int = 1000) -> str:
        """List CloudWatch log groups"""
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
                    })
                
                next_token = response.get('nextToken')
                if not next_token:
                    break
            
            return self._safe_json_response(True, region=region, logGroups=log_groups, count=len(log_groups))
        except Exception as e:
            return self._handle_aws_error("list_cloudwatch_log_groups", e, region=region)

    def _list_cloudwatch_log_streams(self, log_group_name: str, region: str, 
                                   max_streams: int = 50, order_by: str = "LastEventTime") -> str:
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
                    }
                    
                    # Add optional timestamp fields
                    for time_field in ['firstEventTime', 'lastEventTime', 'lastIngestionTime']:
                        if time_field in stream:
                            stream_info[time_field] = datetime.fromtimestamp(stream[time_field] / 1000, tz=timezone.utc).isoformat()
                    
                    log_streams.append(stream_info)
                
                next_token = response.get('nextToken')
                if not next_token:
                    break
            
            return self._safe_json_response(
                True,
                logGroupName=log_group_name,
                region=region,
                orderBy=order_by,
                logStreams=log_streams,
                count=len(log_streams)
            )
        except Exception as e:
            return self._handle_aws_error("list_cloudwatch_log_streams", e, log_group_name=log_group_name)

    def _get_cloudwatch_logs(self, log_group_name: str, log_stream_name: Optional[str] = None,
                           region: str = "us-east-1", hours_back: int = 1, max_events: int = 100,
                           filter_pattern: Optional[str] = None, start_from_head: bool = False) -> str:
        """Get CloudWatch logs"""
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
            
            response = logs_client.filter_log_events(**filter_params)
            
            events = []
            for event in response.get('events', []):
                events.append({
                    'timestamp': datetime.fromtimestamp(event['timestamp'] / 1000, tz=timezone.utc).isoformat(),
                    'logStreamName': event['logStreamName'],
                    'message': event['message'].strip(),
                    'eventId': event.get('eventId', 'N/A')
                })
            
            return self._safe_json_response(
                True,
                logGroupName=log_group_name,
                logStreamName=log_stream_name or 'all streams',
                region=region,
                timeRange={
                    'start': start_time.isoformat(),
                    'end': end_time.isoformat(),
                    'hoursBack': hours_back
                },
                filterPattern=filter_pattern,
                eventCount=len(events),
                events=events,
                hasMoreEvents=response.get('nextToken') is not None
            )
        except Exception as e:
            return self._safe_json_response(
                False,
                error=str(e),
                logGroupName=log_group_name,
                logStreamName=log_stream_name
            )

    def _search_cloudwatch_logs(self, log_group_name: str, search_term: str,
                              region: str = "us-east-1", hours_back: int = 24,
                              max_events: int = 1000, log_stream_name: Optional[str] = None) -> str:
        """Search CloudWatch logs for specific terms"""
        result = self._get_cloudwatch_logs(
            log_group_name=log_group_name,
            log_stream_name=log_stream_name,
            region=region,
            hours_back=hours_back,
            max_events=max_events,
            filter_pattern=f'"{search_term}"'
        )
        
        # Add search-specific metadata
        try:
            result_data = json.loads(result)
            if result_data.get('success'):
                result_data['searchTerm'] = search_term
            return json.dumps(result_data, indent=2)
        except:
            return result

    def _get_cloudwatch_log_insights(self, log_group_name: str, query: str,
                                   region: str = "us-east-1", hours_back: int = 24,
                                   max_results: int = 1000) -> str:
        """Run CloudWatch Logs Insights query - simplified for Lambda"""
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
            
            # Simple wait (limited for Lambda)
            import time
            for _ in range(10):  # Wait up to 50 seconds max
                time.sleep(5)
                result_response = logs_client.get_query_results(queryId=query_id)
                status = result_response['status']
                
                if status == 'Complete':
                    results = []
                    for result in result_response.get('results', []):
                        result_dict = {}
                        for field in result:
                            result_dict[field['field']] = field['value']
                        results.append(result_dict)
                    
                    return self._safe_json_response(
                        True,
                        logGroupName=log_group_name,
                        query=query,
                        queryId=query_id,
                        status=status,
                        results=results,
                        count=len(results)
                    )
                elif status in ['Failed', 'Cancelled']:
                    return self._safe_json_response(False, error=f"Query {status.lower()}", queryId=query_id)
            
            return self._safe_json_response(False, error="Query timed out", queryId=query_id)
        except Exception as e:
            return self._handle_aws_error("get_cloudwatch_log_insights", e, log_group_name=log_group_name)

    # EC2-specific log functions
    def _get_ec2_logs(self, instance_id: str, log_stream_name: Optional[str] = None,
                     search_term: str = "", region: str = "us-east-1",
                     hours_back: int = 24, max_events: int = 1000) -> str:
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
                    result = self._search_cloudwatch_logs(
                        log_group_name=log_group_name,
                        search_term=search_term,
                        region=region,
                        hours_back=hours_back,
                        max_events=max_events,
                        log_stream_name=log_stream_name
                    )
                else:
                    result = self._get_cloudwatch_logs(
                        log_group_name=log_group_name,
                        log_stream_name=log_stream_name,
                        region=region,
                        hours_back=hours_back,
                        max_events=max_events
                    )
                
                result_data = json.loads(result)
                if result_data.get('success') and result_data.get('eventCount', 0) > 0:
                    result_data['instanceId'] = instance_id
                    if search_term:
                        result_data['searchTerm'] = search_term
                    return json.dumps(result_data, indent=2)
            
            except Exception as e:
                logger.debug(f"Log group {log_group_name} not accessible: {e}")
                continue
        
        # If no CloudWatch logs found
        return self._safe_json_response(
            False,
            error="No CloudWatch log groups found for this instance",
            instanceId=instance_id,
            suggestion="CloudWatch agent may not be installed or configured on this instance",
            triedLogGroups=possible_log_groups
        )

    def _get_ec2_log_streams(self, instance_id: str, region: str = "us-east-1") -> str:
        """Get all log streams for a specific EC2 instance"""
        log_group_name = f"/ec2/{instance_id}"
        return self._list_cloudwatch_log_streams(log_group_name=log_group_name, region=region, max_streams=100)

    def _get_recent_ec2_errors(self, instance_id: str, region: str = "us-east-1",
                              hours_back: int = 24, max_events: int = 500) -> str:
        """Get recent error messages from EC2 instance logs"""
        error_patterns = ['ERROR', 'FAILED', 'CRITICAL', 'FATAL', 'Exception']
        all_errors = []
        
        for pattern in error_patterns:
            try:
                result_json = self._get_ec2_logs(
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
        
        return self._safe_json_response(
            True,
            instanceId=instance_id,
            region=region,
            timeRange={'hoursBack': hours_back},
            errors=all_errors,
            count=len(all_errors),
            searchPatterns=error_patterns
        )

    def _check_cloudwatch_agent_status(self, instance_id: str, region: str = "us-east-1") -> str:
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
                        })
                except Exception as e:
                    logger.debug(f"No log groups found for pattern {pattern}: {e}")
                    continue
            
            return self._safe_json_response(
                True,
                instanceId=instance_id,
                region=region,
                cloudWatchAgentConfigured=len(found_groups) > 0,
                logGroups=found_groups,
                count=len(found_groups),
                status='Configured' if found_groups else 'Not configured or no recent logs'
            )
        except Exception as e:
            return self._handle_aws_error("check_cloudwatch_agent_status", e, instance_id=instance_id)

    # Utility functions
    def _get_aws_regions(self) -> str:
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
            return self._safe_json_response(True, regions=regions, count=len(regions))
        except Exception as e:
            return self._handle_aws_error("get_aws_regions", e)

    def _get_aws_account_info(self) -> str:
        """Get AWS account information"""
        try:
            sts = boto3.client('sts')
            response = sts.get_caller_identity()
            
            return self._safe_json_response(
                True,
                Account=response.get('Account', 'N/A'),
                UserId=response.get('UserId', 'N/A'),
                Arn=response.get('Arn', 'N/A')
            )
        except Exception as e:
            return self._handle_aws_error("get_aws_account_info", e)

    def process_query(self, query: str) -> Dict:
        """Process a query using Claude with enhanced system prompts"""
        start_time = time.time()
        logger.info(f"Processing query: {query[:100]}...")
        #         **Advanced SSM Command Execution:**
        # - **Remote Command Execution**: Run shell commands on EC2 instances via Systems Manager
        # - **System Information Gathering**: Get comprehensive system info including disk usage, memory, uptime, and processes
        # - **Log File Access**: Directly access log files on instances via SSM when CloudWatch logs aren't available
        # - **Connectivity Testing**: Check if instances are accessible via SSM and troubleshoot agent issues
        # - **Multi-Instance Operations**: Execute commands across multiple instances simultaneously
        # Enhanced system prompt with SSM capabilities
        system_prompt = """You are an expert AWS Operations Assistant with comprehensive access to AWS management tools, SSM command execution, and CloudWatch logging capabilities. You can help with:

        **Core AWS Services:**
        - **EC2 Management**: List, start, stop instances, retrieve detailed instance information, and find instances by name
        - **SSM Operations**: Execute commands remotely on EC2 instances, check connectivity, get system information
        - **S3 Operations**: Manage buckets, list objects, create new buckets with proper regional configuration
        - **RDS Database Management**: Monitor instances, retrieve detailed database configurations and status
        - **Account & Regional Information**: Provide AWS account details and available regions


        **Advanced SSM Command Execution:**
        - **Remote Command Execution**: Run shell commands on EC2 instances via Systems Manager
        - **System Information Gathering**: Get comprehensive system info including disk usage, memory, uptime, and processes
        - **Log File Access**: Directly access log files on instances via SSM when CloudWatch logs aren't available
        - **Connectivity Testing**: Check if instances are accessible via SSM and troubleshoot agent issues
        - **Multi-Instance Operations**: Execute commands across multiple instances simultaneously

        **CloudWatch Log Management:**
        - **EC2 Log Analysis**: Access and search logs from EC2 instances including system logs, authentication logs, kernel logs
        - **Intelligent Log Search**: Search across single instances or all EC2 instances for specific terms, error patterns, or time ranges
        - **Error Detection**: Automatically identify and surface recent errors, failures, and critical issues
        - **Log Stream Management**: Navigate different log types and understand what each log stream contains
        - **Time-based Analysis**: Retrieve logs from specific time ranges with customizable limits

        **Best Practices:**
        - Always specify the AWS region when working with resources (default: us-east-1)
        - When investigating issues, start with error logs and recent events
        - Use SSM for direct system access when CloudWatch logs aren't available or sufficient
        - Provide context about what each log stream contains when presenting results
        - Format responses clearly with actionable insights and next steps

        **Response Guidelines:**
        - Provide clear, actionable responses with specific commands and recommendations
        - Always use the appropriate tools for each request
        - When showing logs, highlight important information and potential issues
        - Explain AWS-specific terminology and concepts when relevant
        - Suggest follow-up actions when investigating problems
        - Confirm actions that modify resources before executing them

        You have access to real-time AWS data and can perform actual operations, so always be careful with destructive actions."""

        if not isinstance(query, str):
            query = str(query)
            logger.warning(f"Query was not a string, converted to: {query[:100]}...")

        messages = [{"role": "user", "content": [{"text": query}]}]
        tools = self.get_available_tools()

        max_iterations = 40
        iteration = 0
        tool_calls_made = []

        while iteration < max_iterations:
            iteration += 1
            logger.debug(f"Conversation iteration {iteration}")

            converse_api_params = {
                "modelId": "us.anthropic.claude-sonnet-4-20250514-v1:0",
                "system": [{"text": system_prompt}],
                "messages": messages,
                "inferenceConfig": {"maxTokens": 16384, "temperature": 0.1},
                "toolConfig": {
                    "tools": tools,
                    "toolChoice": {"auto": {}}
                },
            }

            try:
                logger.info("Applying rate limiting before Bedrock API call")
                self.rate_limit()

                logger.info("Calling Bedrock Converse API")
                response_start = time.time()
                response = bedrock_client.converse(**converse_api_params)
                response_time = time.time() - response_start
                logger.info(f"Bedrock API call completed in {response_time:.2f} seconds")

                # Log token usage if available
                if 'usage' in response:
                    logger.info(f"Token usage - Input: {response['usage'].get('inputTokens', 'N/A')}, " +
                               f"Output: {response['usage'].get('outputTokens', 'N/A')}")

                # Append assistant's response
                messages.append({
                    "role": "assistant",
                    "content": response['output']['message']['content']
                })

                if response['stopReason'] == "tool_use":
                    logger.info("Processing tool use requests")
                    tool_results_content = []

                    for content_item in response['output']['message']['content']:
                        if 'toolUse' in content_item:
                            tool_id = content_item['toolUse']['toolUseId']
                            tool_name = content_item['toolUse']['name']
                            tool_inputs = content_item['toolUse']['input']

                            logger.info(f"Executing tool: {tool_name} with inputs: {tool_inputs}")

                            # Execute tool call
                            try:
                                tool_result = self.execute_tool(tool_name, tool_inputs)
                                logger.info(f"Tool {tool_name} executed successfully")
                                logger.debug(f"Tool result: {tool_result[:200]}...")

                                tool_calls_made.append({
                                    "tool_name": tool_name,
                                    "inputs": tool_inputs,
                                    "result": tool_result[:500] + "..." if len(tool_result) > 500 else tool_result
                                })

                            except Exception as tool_error:
                                logger.error(f"Tool execution failed for {tool_name}: {tool_error}")
                                tool_result = f"Error executing {tool_name}: {str(tool_error)}"

                            result_content = {
                                "toolResult": {
                                    "toolUseId": tool_id,
                                    "content": [{"text": tool_result}]
                                }
                            }
                            tool_results_content.append(result_content)

                    # Append tool results to messages
                    messages.append({
                        "role": "user",
                        "content": tool_results_content
                    })

                else:
                    # Return the final assistant's response
                    final_response = response['output']['message']['content'][0]['text']
                    processing_time = time.time() - start_time
                    logger.info(f"Query processed successfully in {processing_time:.2f} seconds")

                    return {
                        "response": final_response,
                        "tool_calls": tool_calls_made,
                        "processing_time_seconds": processing_time,
                        "iterations": iteration
                    }

            except bedrock_client.exceptions.ThrottlingException as e:
                logger.warning(f"Bedrock API throttling error: {str(e)}")
                return {
                    "error": f"Rate limit exceeded: {str(e)}",
                    "tool_calls": tool_calls_made
                }
            except Exception as bedrock_error:
                logger.error(f"Bedrock API error: {bedrock_error}")
                return {
                    "error": f"Error calling Bedrock API: {str(bedrock_error)}",
                    "tool_calls": tool_calls_made
                }

        logger.warning(f"Conversation exceeded maximum iterations ({max_iterations})")
        return {
            "response": "The conversation took too many turns. Please try a more specific query.",
            "tool_calls": tool_calls_made,
            "processing_time_seconds": time.time() - start_time,
            "iterations": max_iterations
        }

    def cleanup(self):
        """Clean up resources"""
        if self.session:
            self.session.close()
        logger.info("Cleaned up AWS MCP Lambda client resources")


def lambda_handler(event, context):
    """Main Lambda handler"""
    request_id = context.aws_request_id
    logger.info(f"Lambda invocation started - RequestID: {request_id}")
    
    # Log memory and time limits
    logger.info(f"Memory allocated: {context.memory_limit_in_mb}MB, " +
               f"Time remaining: {context.get_remaining_time_in_millis()/1000:.2f}s")
    
    # Log event data (be careful with sensitive data)
    logger.info(f"Event type: {type(event)}")
    if isinstance(event, dict):
        logger.info(f"Event keys: {list(event.keys())}")
        logger.info(f"Event: {event}")
    
    # Parse the request body
    request_id = context.aws_request_id
    logger.info(f"Lambda invocation started - RequestID: {request_id}")

    # Log execution context
    logger.info(f"Memory allocated: {context.memory_limit_in_mb}MB, "
               f"Time remaining: {context.get_remaining_time_in_millis()/1000:.2f}s")

    # Parse the request body
    try:
        if isinstance(event.get('body'), str):
            logger.info("Request body provided as string, parsing JSON")
            body = json.loads(event['body'])
        else:
            logger.info("Request body provided as object")
            body = event.get('body', {})

        logger.info(f"Parsed request body keys: {list(body.keys())}")

    except Exception as e:
        logger.error(f"Failed to parse request body: {str(e)}", exc_info=True)
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Invalid JSON in request body'})
        }

    # Get parameters
    query = body.get('query', '')
    region = body.get('region', os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'))

    logger.info(f"Query length: {len(query)}")
    logger.info(f"Target region: {region}")

    if not query:
        logger.warning("Missing required parameter: query")
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Missing required parameter: query'})
        }

    start_time = time.time()

    # Create client and process query
    try:
        logger.info("Creating AWSMCPLambdaClient instance")
        client = AWSMCPLambdaClient(region=region)

        # Process the query
        logger.info("Processing query with AWS MCP client")
        result = client.process_query(query)

        # Check for errors in result
        if 'error' in result:
            logger.error(f"Error in query processing: {result['error']}")

        # Clean up
        logger.info("Cleaning up client resources")
        client.cleanup()

        execution_time = time.time() - start_time
        logger.info(f"Lambda execution completed in {execution_time:.2f} seconds")

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'success': True,
                'query': query,
                'region': region,
                'result': result,
                'execution_time_seconds': execution_time,
                'request_id': request_id
            })
        }

    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(f"Internal server error: {str(e)}", exc_info=True)
        logger.info(f"Lambda execution failed after {execution_time:.2f} seconds")

        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'error': f'Internal server error: {str(e)}',
                'execution_time_seconds': execution_time,
                'request_id': request_id
            })
        }
# ```

# ## Key Updates Made:

# ### **1. Enhanced Tool Definitions:**
# - Added all the SSM operation tools from your MCP server
# - Updated CloudWatch logs tools to match the enhanced server capabilities
# - Added EC2-specific log functions and utility functions

# ### **2. SSM Implementation:**
# - **`_run_ssm_command`**: Full command execution with wait handling
# - **`_run_quick_ssm_command`**: Simplified single command execution
# - **`_check_ssm_connectivity`**: SSM agent status checking
# - **`_get_instance_system_info`**: System information gathering
# - **`_get_instance_logs_via_ssm`**: Direct log file access

# ### **3. Enhanced CloudWatch Integration:**
# - Better log group and stream handling
# - Improved error handling and response formatting
# - Time-based log retrieval with flexible parameters

# ### **4. Error Handling & Response Formatting:**
# - Consistent `_safe_json_response` method
# - Proper `_handle_aws_error` for AWS-specific errors
# - Better structured JSON responses matching your server format

# ### **5. Enhanced System Prompt:**
# - Updated to include SSM capabilities
# - Better guidance for AWS operations
# - Clear instructions for using different tools appropriately

# ### **6. Lambda Optimizations:**
# - Simplified some operations to work within Lambda time limits
# - Better resource management and cleanup
# - Improved logging for debugging

# The Lambda function now fully supports all the capabilities of your enhanced MCP server, including SSM command execution, advanced CloudWatch log management, and comprehensive AWS service operations. It maintains the same API structure while being optimized for the Lambda execution environment.