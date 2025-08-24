"""
Patch Manager Tool - Core patch management operations
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

logger = logging.getLogger(__name__)

# Configure boto3 with retry settings
config = Config(
    retries=dict(
        max_attempts=10,
        mode='adaptive'
    ),
    read_timeout=300
)

class PatchManager:
    """Core patch management operations."""

    def __init__(self, region: str = 'us-east-1'):
        self.region = region
        self.ssm = boto3.client('ssm', region_name=region, config=config)
        self.ec2 = boto3.client('ec2', region_name=region, config=config)

    def check_patch_status(self, instance_ids: List[str]) -> Dict[str, Any]:
        """Check patch compliance status for instances."""
        try:
            results = {}

            for instance_id in instance_ids:
                try:
                    # Get patch compliance summary
                    compliance_response = self.ssm.list_compliance_items(
                        ResourceIds=[instance_id],
                        ResourceTypes=['ManagedInstance'],
                        Filters=[
                            {
                                'Key': 'ComplianceType',
                                'Values': ['Patch'],
                                'Type': 'EQUAL'
                            }
                        ]
                    )

                    # Get patch state details
                    patch_state_response = self.ssm.describe_instance_patch_states(
                        InstanceIds=[instance_id]
                    )

                    if patch_state_response.get('InstancePatchStates'):
                        patch_state = patch_state_response['InstancePatchStates'][0]

                        # Get instance info
                        instance_info = self._get_instance_info(instance_id)

                        results[instance_id] = {
                            'instance_info': instance_info,
                            'patch_state': {
                                'baseline_id': patch_state.get('BaselineId', 'N/A'),
                                'patch_group': patch_state.get('PatchGroup', 'Default'),
                                'operation': patch_state.get('Operation', 'N/A'),
                                'operation_start_time': patch_state.get('OperationStartTime', '').isoformat() if patch_state.get('OperationStartTime') else 'N/A',
                                'operation_end_time': patch_state.get('OperationEndTime', '').isoformat() if patch_state.get('OperationEndTime') else 'N/A',
                                'patch_counts': {
                                    'installed': patch_state.get('InstalledCount', 0),
                                    'installed_other': patch_state.get('InstalledOtherCount', 0),
                                    'installed_pending_reboot': patch_state.get('InstalledPendingRebootCount', 0),
                                    'installed_rejected': patch_state.get('InstalledRejectedCount', 0),
                                    'missing': patch_state.get('MissingCount', 0),
                                    'failed': patch_state.get('FailedCount', 0),
                                    'not_applicable': patch_state.get('NotApplicableCount', 0),
                                    'unreported_not_applicable': patch_state.get('UnreportedNotApplicableCount', 0)
                                },
                                'compliance_status': self._determine_compliance_status(patch_state),
                                'last_no_reboot_install_operation_time': patch_state.get('LastNoRebootInstallOperationTime', '').isoformat() if patch_state.get('LastNoRebootInstallOperationTime') else 'N/A',
                                'reboot_option': patch_state.get('RebootOption', 'N/A')
                            },
                            'compliance_items': self._parse_compliance_items(compliance_response.get('ComplianceItems', []))
                        }
                    else:
                        results[instance_id] = {'error': 'No patch state found - instance may not be managed by SSM'}

                except ClientError as e:
                    error_code = e.response['Error']['Code']
                    if error_code == 'InvalidInstanceId.NotFound':
                        results[instance_id] = {'error': 'Instance not found'}
                    elif error_code == 'AccessDenied':
                        results[instance_id] = {'error': 'Access denied - check IAM permissions'}
                    else:
                        results[instance_id] = {'error': f'AWS error: {e.response["Error"]["Message"]}'}
                except Exception as e:
                    results[instance_id] = {'error': f'Unexpected error: {str(e)}'}

            return {
                'success': True,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'instances': results,
                'summary': self._generate_summary(results)
            }

        except Exception as e:
            logger.error(f"Error in check_patch_status: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

    def apply_patches(self, instance_ids: List[str], operation: str = "Install",
                          reboot_option: str = "RebootIfNeeded",
                          baseline_id: Optional[str] = None) -> Dict[str, Any]:
        """Apply patches to instances."""
        try:
            # Validate inputs
            valid_operations = ['Install', 'Scan']
            valid_reboot_options = ['RebootIfNeeded', 'NoReboot']

            if operation not in valid_operations:
                return {
                    'success': False,
                    'error': f'Invalid operation. Must be one of: {valid_operations}'
                }

            if reboot_option not in valid_reboot_options:
                return {
                    'success': False,
                    'error': f'Invalid reboot option. Must be one of: {valid_reboot_options}'
                }

            # Prepare command parameters
            parameters = {
                'Operation': [operation],
                'RebootOption': [reboot_option]
            }

            if baseline_id:
                parameters['BaselineOverride'] = [baseline_id]

            # Send the command
            response = self.ssm.send_command(
                InstanceIds=instance_ids,
                DocumentName='AWS-RunPatchBaseline',
                Parameters=parameters,
                Comment=f'Patch {operation} - {datetime.now(timezone.utc).isoformat()}',
                TimeoutSeconds=3600,  # 1 hour timeout
                CloudWatchOutputConfig={
                    'CloudWatchLogGroupName': '/aws/ssm/patch-manager',
                    'CloudWatchOutputEnabled': True
                }
            )

            command_id = response['Command']['CommandId']

            return {
                'success': True,
                'command_id': command_id,
                'operation': operation,
                'reboot_option': reboot_option,
                'baseline_id': baseline_id,
                'instance_count': len(instance_ids),
                'instances': instance_ids,
                'started_at': datetime.now(timezone.utc).isoformat(),
                'estimated_completion': self._estimate_completion_time(len(instance_ids), operation),
                'monitoring_url': f'https://console.aws.amazon.com/systems-manager/run-command/{command_id}?region={self.region}'
            }

        except ClientError as e:
            logger.error(f"AWS error applying patches: {e}")
            return {
                'success': False,
                'error': f'AWS error: {e.response["Error"]["Message"]}',
                'error_code': e.response['Error']['Code']
            }
        except Exception as e:
            logger.error(f"Error applying patches: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def get_patch_history(self, instance_ids: List[str],
                               days_back: int = 30) -> Dict[str, Any]:
        """Get patch installation history for instances."""
        try:
            results = {}
            
            # Calculate date filter
            since_date = datetime.now(timezone.utc) - timedelta(days=days_back)

            for instance_id in instance_ids:
                try:
                    # Get patch history using describe_instance_patches
                    patches_response = self.ssm.describe_instance_patches(
                        InstanceId=instance_id,
                        MaxResults=100
                    )
                    
                    # Get command execution history
                    commands_response = self.ssm.list_command_invocations(
                        InstanceId=instance_id,
                        MaxResults=50,
                        Filters=[
                            {
                                'key': 'DocumentName',
                                'value': 'AWS-RunPatchBaseline'
                            }
                        ]
                    )
                    
                    # Filter and format patches
                    patches = []
                    for patch in patches_response.get('Patches', []):
                        patches.append({
                            'title': patch.get('Title', 'N/A'),
                            'kb_id': patch.get('KBId', 'N/A'),
                            'classification': patch.get('Classification', 'N/A'),
                            'severity': patch.get('Severity', 'N/A'),
                            'state': patch.get('State', 'N/A'),
                            'installed_time': patch.get('InstalledTime', '').isoformat() if patch.get('InstalledTime') else 'N/A',
                            'cve_ids': patch.get('CVEIds', [])
                        })
                    
                    # Filter and format command history
                    command_history = []
                    for cmd in commands_response.get('CommandInvocations', []):
                        if cmd.get('RequestedDateTime') and cmd['RequestedDateTime'] >= since_date:
                            command_history.append({
                                'command_id': cmd['CommandId'],
                                'document_name': cmd['DocumentName'],
                                'status': cmd.get('Status', 'Unknown'),
                                'requested_date': cmd['RequestedDateTime'].isoformat() if cmd.get('RequestedDateTime') else 'N/A',
                                'status_details': cmd.get('StatusDetails', 'N/A'),
                                'comment': cmd.get('Comment', 'N/A')
                            })
                    
                    results[instance_id] = {
                        'patches': patches,
                        'command_history': command_history,
                        'total_patches': len(patches),
                        'total_commands': len(command_history)
                    }

                except ClientError as e:
                    results[instance_id] = {'error': f'AWS error: {e.response["Error"]["Message"]}'}
                except Exception as e:
                    results[instance_id] = {'error': str(e)}

            return {
                'success': True,
                'instances': results,
                'days_back': days_back,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error getting patch history: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def get_maintenance_windows(self, window_id: Optional[str] = None) -> Dict[str, Any]:
        """Get maintenance window information."""
        try:
            if window_id:
                # Get specific window details
                try:
                    window_response = self.ssm.get_maintenance_window(
                        WindowId=window_id
                    )
                    
                    # Get window targets
                    targets_response = self.ssm.describe_maintenance_window_targets(
                        WindowId=window_id
                    )
                    
                    # Get window tasks
                    tasks_response = self.ssm.describe_maintenance_window_tasks(
                        WindowId=window_id
                    )
                    
                    # Get recent executions
                    executions_response = self.ssm.describe_maintenance_window_executions(
                        WindowId=window_id,
                        MaxResults=10
                    )
                    
                    return {
                        'success': True,
                        'window': {
                            'window_id': window_id,
                            'name': window_response.get('Name', 'N/A'),
                            'description': window_response.get('Description', ''),
                            'enabled': window_response.get('Enabled', False),
                            'schedule': window_response.get('Schedule', ''),
                            'schedule_timezone': window_response.get('ScheduleTimezone', 'UTC'),
                            'schedule_offset': window_response.get('ScheduleOffset', 0),
                            'duration': window_response.get('Duration', 0),
                            'cutoff': window_response.get('Cutoff', 0),
                            'allow_unassociated_targets': window_response.get('AllowUnassociatedTargets', False),
                            'next_execution_time': window_response.get('NextExecutionTime', ''),
                            'created_date': window_response.get('CreatedDate', '').isoformat() if window_response.get('CreatedDate') else 'N/A',
                            'modified_date': window_response.get('ModifiedDate', '').isoformat() if window_response.get('ModifiedDate') else 'N/A',
                            'targets': [
                                {
                                    'window_target_id': target.get('WindowTargetId', 'N/A'),
                                    'resource_type': target.get('ResourceType', 'N/A'),
                                    'targets': target.get('Targets', []),
                                    'owner_information': target.get('OwnerInformation', ''),
                                    'name': target.get('Name', 'N/A'),
                                    'description': target.get('Description', '')
                                }
                                for target in targets_response.get('Targets', [])
                            ],
                            'tasks': [
                                {
                                    'window_task_id': task.get('WindowTaskId', 'N/A'),
                                    'task_arn': task.get('TaskArn', 'N/A'),
                                    'type': task.get('Type', 'N/A'),
                                    'max_concurrency': task.get('MaxConcurrency', 'N/A'),
                                    'max_errors': task.get('MaxErrors', 'N/A'),
                                    'priority': task.get('Priority', 0),
                                    'name': task.get('Name', 'N/A'),
                                    'description': task.get('Description', '')
                                }
                                for task in tasks_response.get('Tasks', [])
                            ],
                            'recent_executions': [
                                {
                                    'window_execution_id': exec.get('WindowExecutionId', 'N/A'),
                                    'status': exec.get('Status', 'N/A'),
                                    'status_details': exec.get('StatusDetails', 'N/A'),
                                    'start_time': exec.get('StartTime', '').isoformat() if exec.get('StartTime') else 'N/A',
                                    'end_time': exec.get('EndTime', '').isoformat() if exec.get('EndTime') else 'N/A'
                                }
                                for exec in executions_response.get('WindowExecutions', [])
                            ]
                        }
                    }
                    
                except ClientError as e:
                    if e.response['Error']['Code'] == 'DoesNotExistException':
                        return {
                            'success': False,
                            'error': f'Maintenance window {window_id} not found'
                        }
                    raise
                    
            else:
                # Get all windows
                response = self.ssm.describe_maintenance_windows(
                    MaxResults=50
                )
                
                windows = []
                for window in response.get('WindowIdentities', []):
                    windows.append({
                        'window_id': window['WindowId'],
                        'name': window.get('Name', 'N/A'),
                        'description': window.get('Description', ''),
                        'enabled': window.get('Enabled', False),
                        'schedule': window.get('Schedule', ''),
                        'schedule_timezone': window.get('ScheduleTimezone', 'UTC'),
                        'duration': window.get('Duration', 0),
                        'cutoff': window.get('Cutoff', 0),
                        'next_execution_time': window.get('NextExecutionTime', '').isoformat() if window.get('NextExecutionTime') else 'Not scheduled'
                    })
                
                return {
                    'success': True,
                    'windows': windows,
                    'count': len(windows)
                }

        except ClientError as e:
            logger.error(f"AWS error getting maintenance windows: {e}")
            return {
                'success': False,
                'error': f'AWS error: {e.response["Error"]["Message"]}'
            }
        except Exception as e:
            logger.error(f"Error getting maintenance windows: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def _get_instance_info(self, instance_id: str) -> Dict[str, Any]:
        """Get basic EC2 instance information."""
        try:
            response = self.ec2.describe_instances(InstanceIds=[instance_id])

            for reservation in response.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    if instance['InstanceId'] == instance_id:
                        # Get tags
                        tags = {}
                        for tag in instance.get('Tags', []):
                            tags[tag['Key']] = tag['Value']
                        
                        return {
                            'instance_id': instance_id,
                            'state': instance['State']['Name'],
                            'instance_type': instance.get('InstanceType', 'unknown'),
                            'platform': instance.get('Platform', 'Linux/UNIX'),
                            'platform_details': instance.get('PlatformDetails', 'N/A'),
                            'architecture': instance.get('Architecture', 'x86_64'),
                            'name': tags.get('Name', f'Instance-{instance_id}'),
                            'environment': tags.get('Environment', tags.get('Env', 'N/A')),
                            'private_ip': instance.get('PrivateIpAddress', 'N/A'),
                            'public_ip': instance.get('PublicIpAddress', 'N/A'),
                            'availability_zone': instance['Placement']['AvailabilityZone'],
                            'launch_time': instance.get('LaunchTime', '').isoformat() if instance.get('LaunchTime') else 'N/A',
                            'tags': tags
                        }

            return {'instance_id': instance_id, 'state': 'unknown'}

        except Exception as e:
            logger.warning(f"Could not get instance info for {instance_id}: {e}")
            return {'instance_id': instance_id, 'error': str(e)}

    def _determine_compliance_status(self, patch_state: Dict[str, Any]) -> str:
        """Determine overall compliance status."""
        missing = patch_state.get('MissingCount', 0)
        failed = patch_state.get('FailedCount', 0)
        pending_reboot = patch_state.get('InstalledPendingRebootCount', 0)

        if missing == 0 and failed == 0 and pending_reboot == 0:
            return 'COMPLIANT'
        elif failed > 0:
            return 'NON_COMPLIANT_CRITICAL'
        elif pending_reboot > 0:
            return 'PENDING_REBOOT'
        else:
            return 'NON_COMPLIANT'

    def _parse_compliance_items(self, compliance_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Parse compliance items for easier consumption."""
        parsed_items = []

        for item in compliance_items:
            parsed_items.append({
                'id': item.get('Id', 'N/A'),
                'title': item.get('Title', 'N/A'),
                'status': item.get('Status', 'N/A'),
                'severity': item.get('Severity', 'N/A'),
                'classification': item.get('Classification', 'N/A'),
                'compliance_type': item.get('ComplianceType', 'N/A'),
                'resource_id': item.get('ResourceId', 'N/A'),
                'resource_type': item.get('ResourceType', 'N/A'),
                'details': item.get('Details', {})
            })

        return parsed_items

    def _generate_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate summary statistics."""
        total_instances = len(results)
        compliant_instances = 0
        non_compliant_instances = 0
        non_compliant_critical = 0
        pending_reboot = 0
        error_instances = 0

        total_missing = 0
        total_failed = 0
        total_installed = 0
        total_pending_reboot = 0

        for instance_id, data in results.items():
            if 'error' in data:
                error_instances += 1
            elif 'patch_state' in data:
                patch_counts = data['patch_state'].get('patch_counts', {})
                missing = patch_counts.get('missing', 0)
                failed = patch_counts.get('failed', 0)
                pending_reboot_count = patch_counts.get('installed_pending_reboot', 0)

                total_missing += missing
                total_failed += failed
                total_installed += patch_counts.get('installed', 0)
                total_pending_reboot += pending_reboot_count

                compliance_status = data['patch_state'].get('compliance_status', 'UNKNOWN')
                
                if compliance_status == 'COMPLIANT':
                    compliant_instances += 1
                elif compliance_status == 'NON_COMPLIANT_CRITICAL':
                    non_compliant_critical += 1
                    non_compliant_instances += 1
                elif compliance_status == 'PENDING_REBOOT':
                    pending_reboot += 1
                elif compliance_status == 'NON_COMPLIANT':
                    non_compliant_instances += 1

        compliance_percentage = (compliant_instances / total_instances * 100) if total_instances > 0 else 0

        return {
            'total_instances': total_instances,
            'compliant_instances': compliant_instances,
            'non_compliant_instances': non_compliant_instances,
            'non_compliant_critical': non_compliant_critical,
            'pending_reboot_instances': pending_reboot,
            'error_instances': error_instances,
            'compliance_percentage': round(compliance_percentage, 1),
            'total_patches': {
                'missing': total_missing,
                'failed': total_failed,
                'installed': total_installed,
                'pending_reboot': total_pending_reboot
            }
        }

    def _estimate_completion_time(self, instance_count: int, operation: str) -> str:
        """Estimate completion time based on instance count and operation."""
        if operation == 'Scan':
            base_minutes = 5
        else:  # Install
            base_minutes = 15

        # Add time based on instance count
        total_minutes = base_minutes + (instance_count * 2)

        if total_minutes < 60:
            return f"{total_minutes} minutes"
        else:
            hours = total_minutes // 60
            minutes = total_minutes % 60
            return f"{hours}h {minutes}m"
        
    def get_window_execution_details(self, window_id: str, execution_id: Optional[str] = None) -> Dict[str, Any]:
        """Get detailed execution results for a maintenance window."""
        try:
            # Get the latest execution if not specified
            if not execution_id:
                exec_response = self.ssm.describe_maintenance_window_executions(
                    WindowId=window_id,
                    MaxResults=10
                )
                if exec_response.get('WindowExecutions'):
                    execution_id = exec_response['WindowExecutions'][0]['WindowExecutionId']
                else:
                    return {'success': False, 'error': 'No executions found'}
            
            # Get task executions
            task_response = self.ssm.describe_maintenance_window_execution_tasks(
                WindowExecutionId=execution_id
            )
            
            instance_results = []
            for task in task_response.get('WindowExecutionTaskIdentities', []):
                task_exec_id = task['TaskExecutionId']
                
                # Get invocation details
                invocation_response = self.ssm.describe_maintenance_window_execution_task_invocations(
                    WindowExecutionId=execution_id,
                    TaskId=task_exec_id,
                    MaxResults=50
                )
                
                for invocation in invocation_response.get('WindowExecutionTaskInvocationIdentities', []):
                    instance_id = invocation.get('Parameters', {}).get('InstanceIds', ['Unknown'])[0]
                    
                    # Try to get command output
                    command_output = None
                    invocation_id = invocation.get('InvocationId')
                    if invocation_id:
                        try:
                            cmd_id = invocation_id.split('/')[-1]
                            cmd_response = self.ssm.get_command_invocation(
                                CommandId=cmd_id,
                                InstanceId=instance_id
                            )
                            command_output = {
                                'stdout': cmd_response.get('StandardOutputContent', '')[:2000],
                                'stderr': cmd_response.get('StandardErrorContent', '')[:1000],
                                'status': cmd_response.get('Status')
                            }
                        except:
                            pass
                    
                    instance_results.append({
                        'instance_id': instance_id,
                        'status': invocation['Status'],
                        'status_details': invocation.get('StatusDetails', ''),
                        'start_time': invocation.get('StartTime', '').isoformat() if invocation.get('StartTime') else 'N/A',
                        'end_time': invocation.get('EndTime', '').isoformat() if invocation.get('EndTime') else 'N/A',
                        'command_output': command_output,
                        'instance_info': self._get_instance_info(instance_id)
                    })
            
            # Group by environment
            by_environment = {}
            for result in instance_results:
                env = result.get('instance_info', {}).get('environment', 'Unknown')
                if env not in by_environment:
                    by_environment[env] = []
                by_environment[env].append(result)
            
            return {
                'success': True,
                'window_id': window_id,
                'execution_id': execution_id,
                'instance_results': instance_results,
                'by_environment': by_environment,
                'summary': {
                    'total': len(instance_results),
                    'success': len([r for r in instance_results if r['status'] == 'SUCCESS']),
                    'failed': len([r for r in instance_results if r['status'] in ['FAILED', 'TIMED_OUT']])
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting window execution details: {e}")
            return {'success': False, 'error': str(e)}

