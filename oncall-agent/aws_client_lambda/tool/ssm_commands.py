"""
SSM Command Manager Tool - Command execution and monitoring
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from botocore.config import Config
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

class SSMCommandManager:
    """SSM command execution and monitoring."""

    def __init__(self, region: str = 'us-east-1'):
        self.region = region
        self.ssm = boto3.client('ssm', region_name=region)

    async def execute_command(self, instance_ids: List[str], document_name: str,
                            parameters: Dict[str, List[str]],
                            comment: Optional[str] = None) -> Dict[str, Any]:
        """Execute SSM command on instances."""
        try:
            response = self.ssm.send_command(
                InstanceIds=instance_ids,
                DocumentName=document_name,
                Parameters=parameters,
                Comment=comment or f"Command execution - {datetime.now(timezone.utc).isoformat()}",
                TimeoutSeconds=3600,
                CloudWatchOutputConfig={
                    'CloudWatchLogGroupName': '/aws/ssm/commands',
                    'CloudWatchOutputEnabled': True
                }
            )

            command = response['Command']

            return {
                'success': True,
                'command_id': command['CommandId'],
                'document_name': document_name,
                'status': command.get('Status', 'InProgress'),
                'instance_count': len(instance_ids),
                'instances': instance_ids,
                'parameters': parameters,
                'requested_time': command.get('RequestedDateTime', '').isoformat() if command.get('RequestedDateTime') else 'N/A',
                'expires_after': command.get('ExpiresAfter', '').isoformat() if command.get('ExpiresAfter') else 'N/A',
                'timeout_seconds': command.get('TimeoutSeconds', 3600),
                'monitoring_url': f'<https://console.aws.amazon.com/systems-manager/run-command/{command["CommandId"]}?region={self.region}>'
            }

        except ClientError as e:
            logger.error(f"AWS error executing command: {e}")
            return {
                'success': False,
                'error': f'AWS error: {e.response["Error"]["Message"]}',
                'error_code': e.response['Error']['Code']
            }
        except Exception as e:
            logger.error(f"Error executing command: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def get_command_status(self, command_id: str) -> Dict[str, Any]:
        """Get status of a specific command."""
        try:
            # Get command details
            command_response = self.ssm.list_commands(
                CommandId=command_id
            )

            if not command_response.get('Commands'):
                return {
                    'success': False,
                    'error': f'Command {command_id} not found'
                }

            command = command_response['Commands'][0]

            # Get invocation details for each instance
            invocations_response = self.ssm.list_command_invocations(
                CommandId=command_id,
                Details=True
            )

            # Process invocation results
            invocations = []
            for invocation in invocations_response.get('CommandInvocations', []):
                invocations.append({
                    'instance_id': invocation.get('InstanceId', 'N/A'),
                    'instance_name': invocation.get('InstanceName', 'N/A'),
                    'status': invocation.get('Status', 'Unknown'),
                    'status_details': invocation.get('StatusDetails', 'N/A'),
                    'standard_output': invocation.get('StandardOutputContent', '')[:1000],  # Limit output
                    'standard_error': invocation.get('StandardErrorContent', '')[:1000],
                    'command_plugins': [
                        {
                            'name': plugin.get('Name', 'N/A'),
                            'status': plugin.get('Status', 'Unknown'),
                            'response_code': plugin.get('ResponseCode', -1),
                            'output': plugin.get('Output', '')[:500]  # Limit plugin output
                        }
                        for plugin in invocation.get('CommandPlugins', [])
                    ]
                })

            # Calculate summary statistics
            total_instances = len(invocations)
            success_count = sum(1 for inv in invocations if inv['status'] == 'Success')
            failed_count = sum(1 for inv in invocations if inv['status'] == 'Failed')
            in_progress_count = sum(1 for inv in invocations if inv['status'] == 'InProgress')

            return {
                'success': True,
                'command': {
                    'command_id': command_id,
                    'document_name': command.get('DocumentName', 'N/A'),
                    'status': command.get('Status', 'Unknown'),
                    'status_details': command.get('StatusDetails', 'N/A'),
                    'requested_time': command.get('RequestedDateTime', '').isoformat() if command.get('RequestedDateTime') else 'N/A',
                    'completed_time': command.get('CompletedDateTime', '').isoformat() if command.get('CompletedDateTime') else 'N/A',
                    'target_count': command.get('TargetCount', 0),
                    'completed_count': command.get('CompletedCount', 0),
                    'error_count': command.get('ErrorCount', 0),
                    'delivery_timed_out_count': command.get('DeliveryTimedOutCount', 0)
                },
                'summary': {
                    'total_instances': total_instances,
                    'success_count': success_count,
                    'failed_count': failed_count,
                    'in_progress_count': in_progress_count,
                    'success_rate': round((success_count / total_instances * 100), 1) if total_instances > 0 else 0
                },
                'invocations': invocations
            }

        except ClientError as e:
            logger.error(f"AWS error getting command status: {e}")
            return {
                'success': False,
                'error': f'AWS error: {e.response["Error"]["Message"]}'
            }
        except Exception as e:
            logger.error(f"Error getting command status: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def list_recent_commands(self, days_back: int = 7,
                                 instance_id: Optional[str] = None) -> Dict[str, Any]:
        """List recent SSM commands."""
        try:
            # Calculate date filter
            since_date = datetime.now(timezone.utc) - timedelta(days=days_back)

            # Build filters
            filters = []
            if instance_id:
                filters.append({
                    'key': 'InstanceId',
                    'value': instance_id
                })

            # Get commands
            response = self.ssm.list_commands(
                Filters=filters,
                MaxResults=50  # Limit results
            )

            commands = []
            for command in response.get('Commands', []):
                # Filter by date
                requested_time = command.get('RequestedDateTime')
                if requested_time and requested_time < since_date:
                    continue

                commands.append({
                    'command_id': command.get('CommandId', 'N/A'),
                    'document_name': command.get('DocumentName', 'N/A'),
                    'status': command.get('Status', 'Unknown'),
                    'requested_time': requested_time.isoformat() if requested_time else 'N/A',
                    'completed_time': command.get('CompletedDateTime', '').isoformat() if command.get('CompletedDateTime') else 'N/A',
                    'target_count': command.get('TargetCount', 0),
                    'completed_count': command.get('CompletedCount', 0),
                    'error_count': command.get('ErrorCount', 0),
                    'comment': command.get('Comment', 'N/A')
                })

            # Sort by requested time (newest first)
            commands.sort(key=lambda x: x['requested_time'], reverse=True)

            return {
                'success': True,
                'commands': commands,
                'count': len(commands),
                'days_back': days_back,
                'instance_filter': instance_id
            }

        except ClientError as e:
            logger.error(f"AWS error listing commands: {e}")
            return {
                'success': False,
                'error': f'AWS error: {e.response["Error"]["Message"]}'
            }
        except Exception as e:
            logger.error(f"Error listing commands: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def cancel_command(self, command_id: str,
                           instance_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Cancel a running command."""
        try:
            params = {'CommandId': command_id}
            if instance_ids:
                params['InstanceIds'] = instance_ids

            self.ssm.cancel_command(**params)

            return {
                'success': True,
                'command_id': command_id,
                'message': 'Command cancellation requested',
                'instances': instance_ids or 'all'
            }

        except ClientError as e:
            logger.error(f"AWS error canceling command: {e}")
            return {
                'success': False,
                'error': f'AWS error: {e.response["Error"]["Message"]}'
            }
        except Exception as e:
            logger.error(f"Error canceling command: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def get_command_output(self, command_id: str,
                               instance_id: str) -> Dict[str, Any]:
        """Get detailed output from a command execution."""
        try:
            response = self.ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )

            return {
                'success': True,
                'command_id': command_id,
                'instance_id': instance_id,
                'status': response.get('Status', 'Unknown'),
                'status_details': response.get('StatusDetails', 'N/A'),
                'execution_start_time': response.get('ExecutionStartDateTime', '').isoformat() if response.get('ExecutionStartDateTime') else 'N/A',
                'execution_end_time': response.get('ExecutionEndDateTime', '').isoformat() if response.get('ExecutionEndDateTime') else 'N/A',
                'standard_output': response.get('StandardOutputContent', ''),
                'standard_error': response.get('StandardErrorContent', ''),
                'cloud_watch_output_url': response.get('CloudWatchOutputConfig', {}).get('CloudWatchOutputUrl', 'N/A')
            }

        except ClientError as e:
            logger.error(f"AWS error getting command output: {e}")
            return {
                'success': False,
                'error': f'AWS error: {e.response["Error"]["Message"]}'
            }
        except Exception as e:
            logger.error(f"Error getting command output: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def run_shell_command(self, instance_ids: List[str],
                              commands: List[str],
                              working_directory: str = "/tmp",
                              timeout_seconds: int = 1800) -> Dict[str, Any]:
        """Run shell commands on instances."""
        try:
            parameters = {
                'commands': commands,
                'workingDirectory': [working_directory],
                'executionTimeout': [str(timeout_seconds)]
            }

            return await self.execute_command(
                instance_ids=instance_ids,
                document_name='AWS-RunShellScript',
                parameters=parameters,
                comment=f"Shell command execution - {' '.join(commands[:2])}"
            )

        except Exception as e:
            logger.error(f"Error running shell command: {e}")
            return {
                'success': False,
                'error': str(e)
            }
