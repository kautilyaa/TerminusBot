"""
Diagnostic Manager Tool - Complete implementation with all methods
"""

import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config
import json
import re

logger = logging.getLogger(__name__)

# Configure boto3 with retry settings
config = Config(
    retries=dict(
        max_attempts=10,
        mode='adaptive'
    ),
    read_timeout=300
)

class DiagnosticManager:
    """System diagnostics and troubleshooting tools - Complete implementation."""

    def __init__(self, region: str = 'us-east-1'):
        self.region = region
        self.ssm = boto3.client('ssm', region_name=region, config=config)
        self.ec2 = boto3.client('ec2', region_name=region, config=config)
        self.logs = boto3.client('logs', region_name=region, config=config)

    def diagnose_patch_failures(self, instance_ids: List[str]) -> Dict[str, Any]:
        """Diagnose patch installation failures."""
        try:
            results = {}

            for instance_id in instance_ids:
                try:
                    diagnosis = {
                        'instance_id': instance_id,
                        'checks': {},
                        'issues_found': [],
                        'recommendations': []
                    }

                    # Check 1: SSM Agent connectivity
                    ping_result = self._check_ssm_connectivity(instance_id)
                    diagnosis['checks']['ssm_connectivity'] = ping_result
                    if not ping_result['success']:
                        diagnosis['issues_found'].append('SSM Agent connectivity issues')
                        diagnosis['recommendations'].append('Check SSM Agent installation and IAM permissions')

                    # Check 2: Disk space
                    disk_result = self._check_disk_space(instance_id)
                    diagnosis['checks']['disk_space'] = disk_result
                    if not disk_result['success']:
                        diagnosis['issues_found'].append('Insufficient disk space')
                        diagnosis['recommendations'].append('Free up disk space before patching')

                    # Check 3: Recent patch failures
                    patch_failures = self._check_recent_patch_failures(instance_id)
                    diagnosis['checks']['patch_failures'] = patch_failures
                    if patch_failures.get('failure_count', 0) > 0:
                        diagnosis['issues_found'].append(f"Recent patch failures: {patch_failures['failure_count']}")
                        diagnosis['recommendations'].append('Review patch failure logs and resolve conflicts')

                    # Check 4: System reboot requirement
                    reboot_check = self._check_reboot_required(instance_id)
                    diagnosis['checks']['reboot_required'] = reboot_check
                    if reboot_check.get('required', False):
                        diagnosis['issues_found'].append('System reboot required')
                        diagnosis['recommendations'].append('Reboot instance to complete previous installations')

                    # Check 5: Package manager status
                    package_mgr = self._check_package_manager_status(instance_id)
                    diagnosis['checks']['package_manager'] = package_mgr
                    if not package_mgr['success']:
                        diagnosis['issues_found'].append('Package manager issues')
                        diagnosis['recommendations'].append('Resolve package manager conflicts or locks')

                    # Generate overall health score
                    successful_checks = sum(1 for check in diagnosis['checks'].values() if check.get('success', False))
                    total_checks = len(diagnosis['checks'])
                    diagnosis['health_score'] = round((successful_checks / total_checks * 100), 1) if total_checks > 0 else 0

                    results[instance_id] = diagnosis

                except Exception as e:
                    results[instance_id] = {
                        'instance_id': instance_id,
                        'error': str(e),
                        'health_score': 0
                    }

            return {
                'success': True,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'instances': results,
                'summary': self._generate_diagnostic_summary(results)
            }

        except Exception as e:
            logger.error(f"Error in diagnose_patch_failures: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def collect_system_info(self, instance_ids: List[str]) -> Dict[str, Any]:
        """Collect comprehensive system information."""
        try:
            results = {}

            for instance_id in instance_ids:
                try:
                    system_info = {
                        'instance_id': instance_id,
                        'collected_at': datetime.now(timezone.utc).isoformat(),
                        'info': {}
                    }

                    # Get basic instance info
                    instance_info = self._get_instance_details(instance_id)
                    system_info['info']['instance'] = instance_info

                    # Get OS information
                    os_info = self._get_os_information(instance_id)
                    system_info['info']['operating_system'] = os_info

                    # Get disk usage
                    disk_usage = self._get_disk_usage(instance_id)
                    system_info['info']['disk_usage'] = disk_usage

                    # Get memory usage
                    memory_info = self._get_memory_info(instance_id)
                    system_info['info']['memory'] = memory_info

                    # Get network information
                    network_info = self._get_network_info(instance_id)
                    system_info['info']['network'] = network_info

                    # Get running services
                    services_info = self._get_running_services(instance_id)
                    system_info['info']['services'] = services_info

                    results[instance_id] = system_info

                except Exception as e:
                    results[instance_id] = {
                        'instance_id': instance_id,
                        'error': str(e)
                    }

            return {
                'success': True,
                'instances': results,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error collecting system info: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def analyze_logs(self, instance_ids: List[str],
                     log_type: str = 'patch',
                     hours_back: int = 24) -> Dict[str, Any]:
        """Analyze system logs for issues."""
        try:
            results = {}

            for instance_id in instance_ids:
                try:
                    log_analysis = {
                        'instance_id': instance_id,
                        'log_type': log_type,
                        'analysis_period': f"{hours_back} hours",
                        'logs': {},
                        'issues_found': [],
                        'patterns': {}
                    }

                    if log_type == 'patch':
                        # Analyze patch-related logs
                        patch_logs = self._get_patch_logs(instance_id, hours_back)
                        log_analysis['logs']['patch'] = patch_logs

                        # Look for error patterns
                        error_patterns = self._analyze_patch_errors(patch_logs)
                        log_analysis['patterns']['errors'] = error_patterns

                    elif log_type == 'system':
                        # Analyze system logs
                        system_logs = self._get_system_logs(instance_id, hours_back)
                        log_analysis['logs']['system'] = system_logs

                        # Look for system issues
                        system_patterns = self._analyze_system_errors(system_logs)
                        log_analysis['patterns']['system_issues'] = system_patterns

                    results[instance_id] = log_analysis

                except Exception as e:
                    results[instance_id] = {
                        'instance_id': instance_id,
                        'error': str(e)
                    }

            return {
                'success': True,
                'instances': results,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error analyzing logs: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def repair_common_issues(self, instance_ids: List[str],
                            issue_type: str = 'auto') -> Dict[str, Any]:
        """Attempt to repair common patch-related issues."""
        try:
            results = {}

            for instance_id in instance_ids:
                try:
                    repair_result = {
                        'instance_id': instance_id,
                        'issue_type': issue_type,
                        'repairs_attempted': [],
                        'repairs_successful': [],
                        'repairs_failed': []
                    }

                    if issue_type == 'auto' or issue_type == 'package_manager':
                        # Repair package manager issues
                        pkg_repair = self._repair_package_manager(instance_id)
                        repair_result['repairs_attempted'].append('package_manager')
                        if pkg_repair['success']:
                            repair_result['repairs_successful'].append('package_manager')
                        else:
                            repair_result['repairs_failed'].append(f"package_manager: {pkg_repair.get('error', 'Unknown error')}")

                    if issue_type == 'auto' or issue_type == 'ssm_agent':
                        # Restart SSM agent
                        ssm_repair = self._restart_ssm_agent(instance_id)
                        repair_result['repairs_attempted'].append('ssm_agent')
                        if ssm_repair['success']:
                            repair_result['repairs_successful'].append('ssm_agent')
                        else:
                            repair_result['repairs_failed'].append(f"ssm_agent: {ssm_repair.get('error', 'Unknown error')}")

                    if issue_type == 'auto' or issue_type == 'cleanup':
                        # Cleanup temporary files
                        cleanup_repair = self._cleanup_temp_files(instance_id)
                        repair_result['repairs_attempted'].append('cleanup')
                        if cleanup_repair['success']:
                            repair_result['repairs_successful'].append('cleanup')
                        else:
                            repair_result['repairs_failed'].append(f"cleanup: {cleanup_repair.get('error', 'Unknown error')}")

                    # Calculate success rate
                    total_attempted = len(repair_result['repairs_attempted'])
                    successful = len(repair_result['repairs_successful'])
                    repair_result['success_rate'] = round((successful / total_attempted * 100), 1) if total_attempted > 0 else 0

                    results[instance_id] = repair_result

                except Exception as e:
                    results[instance_id] = {
                        'instance_id': instance_id,
                        'error': str(e)
                    }

            return {
                'success': True,
                'instances': results,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error in repair_common_issues: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    # ========== COMPLETE IMPLEMENTATION OF ALL HELPER METHODS ==========

    def _check_ssm_connectivity(self, instance_id: str) -> Dict[str, Any]:
        """Check SSM Agent connectivity."""
        try:
            response = self.ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={
                    'commands': ['echo "SSM connectivity test successful"'],
                    'executionTimeout': ['30']
                },
                TimeoutSeconds=60
            )

            command_id = response['Command']['CommandId']

            # Wait for execution
            time.sleep(5)

            # Check result
            result = self.ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )

            return {
                'success': result.get('Status') == 'Success',
                'status': result.get('Status', 'Unknown'),
                'details': result.get('StandardOutputContent', '')
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _check_disk_space(self, instance_id: str) -> Dict[str, Any]:
        """Check available disk space."""
        try:
                response = self.ssm.send_command(
                    InstanceIds=[instance_id],
                    DocumentName='AWS-RunShellScript',
                    Parameters= {
                        'commands': ["df -h / | tail -1 | awk \\'{print $5}\\'"],
                        'executionTimeout': ['30']
                    }
                )

                command_id = response['Command']['CommandId']
                time.sleep(3)

                result = self.ssm.get_command_invocation(
                    CommandId=command_id,
                    InstanceId=instance_id
                )

                if result.get('Status') == 'Success':
                    usage_str = result.get('StandardOutputContent', '').strip()
                    if usage_str.endswith('%'):
                        usage_percent = int(usage_str[:-1])
                        return {
                            'success': usage_percent < 90,  # Consider 90%+ as problematic
                            'usage_percent': usage_percent,
                            'details': f"Disk usage: {usage_str}"
                        }

                return {
                    'success': False,
                    'error': 'Could not determine disk usage'
                }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _check_recent_patch_failures(self, instance_id: str) -> Dict[str, Any]:
        """Check for recent patch failures."""
        try:
            # Get recent commands for this instance
            response = self.ssm.list_command_invocations(
                InstanceId=instance_id,
                Filters=[
                    {
                        'key': 'DocumentName',
                        'value': 'AWS-RunPatchBaseline'
                    }
                ],
                MaxResults=10
            )

            failures = 0
            recent_commands = response.get('CommandInvocations', [])

            for command in recent_commands:
                if command.get('Status') == 'Failed':
                    failures += 1

            return {
                'success': failures == 0,
                'failure_count': failures,
                'total_recent_commands': len(recent_commands)
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _check_reboot_required(self, instance_id: str) -> Dict[str, Any]:
        """Check if system reboot is required."""
        try:
            # Different commands for different OS types
            commands = [
                # For Ubuntu/Debian
                'if [ -f /var/run/reboot-required ]; then echo "REBOOT_REQUIRED"; fi',
                # For Amazon Linux/RHEL/CentOS
                'if needs-restarting -r 2>/dev/null; then echo "NO_REBOOT_REQUIRED"; else echo "REBOOT_REQUIRED"; fi',
                # For Windows
                'if (Get-ItemProperty "HKLM:\\\\SOFTWARE\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\WindowsUpdate\\\\Auto Update\\\\RebootRequired" -ErrorAction SilentlyContinue) { "REBOOT_REQUIRED" } else { "NO_REBOOT_REQUIRED" }'
            ]

            # Try Linux commands first
            response = self.ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={
                    'commands': commands[:2]
                }
            )

            command_id = response['Command']['CommandId']
            time.sleep(3)

            result = self.ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )

            if result.get('Status') == 'Success':
                output = result.get('StandardOutputContent', '').strip()
                required = 'REBOOT_REQUIRED' in output

                return {
                    'success': True,
                    'required': required,
                    'details': 'Reboot required' if required else 'No reboot required'
                }

            return {
                'success': False,
                'error': 'Could not check reboot status'
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _check_package_manager_status(self, instance_id: str) -> Dict[str, Any]:
        """Check package manager status."""
        try:
            # Commands to check package manager locks
            commands = [
                # Check for apt locks (Ubuntu/Debian)
                'if command -v apt >/dev/null 2>&1; then if lsof /var/lib/dpkg/lock* /var/lib/apt/lists/lock* 2>/dev/null | grep -q .; then echo "LOCKED_APT"; else echo "OK_APT"; fi; fi',
                # Check for yum locks (RHEL/CentOS/Amazon Linux)
                'if command -v yum >/dev/null 2>&1; then if [ -f /var/run/yum.pid ] && kill -0 $(cat /var/run/yum.pid) 2>/dev/null; then echo "LOCKED_YUM"; else echo "OK_YUM"; fi; fi',
                # Check for dnf locks (Fedora/RHEL 8+)
                'if command -v dnf >/dev/null 2>&1; then if [ -f /var/run/dnf.pid ] && kill -0 $(cat /var/run/dnf.pid) 2>/dev/null; then echo "LOCKED_DNF"; else echo "OK_DNF"; fi; fi'
            ]

            response = self.ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={
                    'commands': commands
                }
            )

            command_id = response['Command']['CommandId']
            time.sleep(3)

            result = self.ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )

            if result.get('Status') == 'Success':
                output = result.get('StandardOutputContent', '').strip()

                return {
                    'success': 'OK' in output and 'LOCKED' not in output,
                    'status': output,
                    'locked': 'LOCKED' in output
                }

            return {
                'success': False,
                'error': 'Could not check package manager status'
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _get_instance_details(self, instance_id: str) -> Dict[str, Any]:
        """Get detailed EC2 instance information."""
        try:
            response = self.ec2.describe_instances(InstanceIds=[instance_id])

            if not response['Reservations']:
                return {'error': 'Instance not found'}

            instance = response['Reservations'][0]['Instances'][0]

            # Extract tags
            tags = {}
            for tag in instance.get('Tags', []):
                tags[tag['Key']] = tag['Value']

            return {
                'instance_id': instance_id,
                'instance_type': instance.get('InstanceType', 'N/A'),
                'state': instance['State']['Name'],
                'platform': instance.get('Platform', 'Linux/UNIX'),
                'architecture': instance.get('Architecture', 'x86_64'),
                'ami_id': instance.get('ImageId', 'N/A'),
                'launch_time': instance.get('LaunchTime', '').isoformat() if instance.get('LaunchTime') else 'N/A',
                'availability_zone': instance['Placement']['AvailabilityZone'],
                'private_ip': instance.get('PrivateIpAddress', 'N/A'),
                'public_ip': instance.get('PublicIpAddress', 'N/A'),
                'vpc_id': instance.get('VpcId', 'N/A'),
                'subnet_id': instance.get('SubnetId', 'N/A'),
                'security_groups': [sg['GroupName'] for sg in instance.get('SecurityGroups', [])],
                'iam_role': instance.get('IamInstanceProfile', {}).get('Arn', 'N/A'),
                'tags': tags,
                'name': tags.get('Name', 'N/A'),
                'environment': tags.get('Environment', tags.get('Env', 'N/A'))
            }

        except Exception as e:
            logger.error(f"Error getting instance details: {e}")
            return {'error': str(e)}

    def _get_os_information(self, instance_id: str) -> Dict[str, Any]:
        """Get operating system information."""
        try:
            commands = [
                'cat /etc/os-release 2>/dev/null || cat /etc/redhat-release 2>/dev/null || echo "Unknown OS"',
                'uname -a',
                'hostname',
                'uptime',
                'cat /proc/version 2>/dev/null || echo "Version info not available"'
            ]

            response = self.ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={
                    'commands': commands
                }
            )

            command_id = response['Command']['CommandId']
            time.sleep(3)

            result = self.ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )

            if result.get('Status') == 'Success':
                output_lines = result.get('StandardOutputContent', '').strip().split('\\n')

                # Parse OS information
                os_info = {
                    'os_release': 'Unknown',
                    'kernel': 'Unknown',
                    'hostname': 'Unknown',
                    'uptime': 'Unknown',
                    'version': 'Unknown'
                }

                # Parse OS release info
                for line in output_lines:
                    if 'NAME=' in line:
                        os_info['os_release'] = line.split('=')[1].strip('"')
                    elif 'Linux' in line and 'GNU/Linux' in line:
                        os_info['kernel'] = line
                    elif 'up' in line and ('days' in line or 'min' in line or 'hours' in line):
                        os_info['uptime'] = line

                return {
                    'success': True,
                    'os_info': os_info,
                    'raw_output': output_lines
                }

            return {
                'success': False,
                'error': 'Could not get OS information'
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _get_disk_usage(self, instance_id: str) -> Dict[str, Any]:
        """Get detailed disk usage information."""
        try:
            commands = [
                'df -h',
                'df -i',  # Inode usage
                'du -sh /var/log 2>/dev/null || echo "/var/log: N/A"',
                'du -sh /tmp 2>/dev/null || echo "/tmp: N/A"',
                'du -sh /opt 2>/dev/null || echo "/opt: N/A"'
            ]

            response = self.ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={
                    'commands': commands
                }
            )

            command_id = response['Command']['CommandId']
            time.sleep(3)

            result = self.ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )

            if result.get('Status') == 'Success':
                output = result.get('StandardOutputContent', '').strip()

                # Parse df output
                filesystems = []
                lines = output.split('\\n')

                for line in lines[1:]:  # Skip header
                    if line and not line.startswith('Filesystem'):
                        parts = line.split()
                        if len(parts) >= 6:
                            filesystems.append({
                                'filesystem': parts[0],
                                'size': parts[1],
                                'used': parts[2],
                                'available': parts[3],
                                'use_percent': parts[4],
                                'mount_point': parts[5]
                            })

                return {
                    'success': True,
                    'filesystems': filesystems,
                    'raw_output': output
                }

            return {
                'success': False,
                'error': 'Could not get disk usage'
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _get_memory_info(self, instance_id: str) -> Dict[str, Any]:
        """Get memory usage information."""
        try:
            commands = [
                'free -h',
                'cat /proc/meminfo | head -10',
                'ps aux --sort=-%mem | head -10'
            ]

            response = self.ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={
                    'commands': commands
                }
            )

            command_id = response['Command']['CommandId']
            time.sleep(3)

            result = self.ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )

            if result.get('Status') == 'Success':
                output = result.get('StandardOutputContent', '').strip()
                lines = output.split('\\n')

                # Parse free command output
                memory_info = {
                    'total': 'N/A',
                    'used': 'N/A',
                    'free': 'N/A',
                    'available': 'N/A',
                    'swap_total': 'N/A',
                    'swap_used': 'N/A'
                }

                for line in lines:
                    if 'Mem:' in line:
                        parts = line.split()
                        if len(parts) >= 4:
                            memory_info['total'] = parts[1]
                            memory_info['used'] = parts[2]
                            memory_info['free'] = parts[3]
                    elif 'Swap:' in line:
                        parts = line.split()
                        if len(parts) >= 3:
                            memory_info['swap_total'] = parts[1]
                            memory_info['swap_used'] = parts[2]

                return {
                    'success': True,
                    'memory': memory_info,
                    'raw_output': output
                }

            return {
                'success': False,
                'error': 'Could not get memory information'
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _get_network_info(self, instance_id: str) -> Dict[str, Any]:
        """Get network configuration information."""
        try:
            commands = [
                'ip addr show 2>/dev/null || ifconfig',
                'ip route show 2>/dev/null || route -n',
                'ss -tunlp 2>/dev/null || netstat -tunlp',
                'cat /etc/resolv.conf'
            ]

            response = self.ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={
                    'commands': commands
                }
            )

            command_id = response['Command']['CommandId']
            time.sleep(3)

            result = self.ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )

            if result.get('Status') == 'Success':
                output = result.get('StandardOutputContent', '').strip()

                # Parse network interfaces
                interfaces = []
                lines = output.split('\\n')

                current_interface = None
                for line in lines:
                    if re.match(r'^\\d+:', line):  # New interface
                        if current_interface:
                            interfaces.append(current_interface)
                        parts = line.split(':')
                        if len(parts) >= 2:
                            current_interface = {
                                'name': parts[1].strip(),
                                'addresses': []
                            }
                    elif current_interface and 'inet ' in line:
                        # Extract IP address
                        match = re.search(r'inet\\s+(\\d+\\.\\d+\\.\\d+\\.\\d+)', line)
                        if match:
                            current_interface['addresses'].append(match.group(1))

                if current_interface:
                    interfaces.append(current_interface)

                return {
                    'success': True,
                    'interfaces': interfaces,
                    'raw_output': output
                }

            return {
                'success': False,
                'error': 'Could not get network information'
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _get_running_services(self, instance_id: str) -> Dict[str, Any]:
        """Get list of running services."""
        try:
            commands = [
                # For systemd systems
                'systemctl list-units --type=service --state=running --no-pager 2>/dev/null | head -20',
                # For older init systems
                'service --status-all 2>/dev/null | grep running | head -20',
                # Process list as fallback
                'ps aux | head -20'
            ]

            response = self.ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={
                    'commands': commands
                }
            )

            command_id = response['Command']['CommandId']
            time.sleep(3)

            result = self.ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )

            if result.get('Status') == 'Success':
                output = result.get('StandardOutputContent', '').strip()

                # Parse services
                services = []
                lines = output.split('\\n')

                for line in lines:
                    if '.service' in line and 'running' in line.lower():
                        # Parse systemd output
                        parts = line.split()
                        if parts:
                            service_name = parts[0].replace('.service', '')
                            services.append({
                                'name': service_name,
                                'status': 'running'
                            })
                    elif '[ + ]' in line:
                        # Parse service --status-all output
                        match = re.search(r'\\[ \\+ \\]\\s+(.+)', line)
                        if match:
                            services.append({
                                'name': match.group(1),
                                'status': 'running'
                            })

                return {
                    'success': True,
                    'services': services[:20],  # Limit to top 20
                    'service_count': len(services),
                    'raw_output': output[:2000]  # Limit output size
                }

            return {
                'success': False,
                'error': 'Could not get running services'
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _get_patch_logs(self, instance_id: str, hours_back: int) -> Dict[str, Any]:
        """Get patch-related logs from the instance."""
        try:
            # Commands to get patch logs from different locations
            commands = [
                # YUM history (RHEL/CentOS/Amazon Linux)
                f'yum history list all 2>/dev/null | head -30',
                # APT history (Ubuntu/Debian)
                f'grep -E "Commandline:|Start-Date:" /var/log/apt/history.log 2>/dev/null | tail -30',
                # DNF history (Fedora/RHEL 8+)
                f'dnf history list 2>/dev/null | head -30',
                # SSM patch logs
                f'tail -100 /var/log/amazon/ssm/amazon-ssm-agent.log 2>/dev/null | grep -i patch',
                # Windows Update logs
                f'Get-WindowsUpdateLog -LogPath C:\\\\Temp\\\\WindowsUpdate.log 2>$null; Get-Content C:\\\\Temp\\\\WindowsUpdate.log -Tail 100'
            ]

            response = self.ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={
                    'commands': commands
                }
            )

            command_id = response['Command']['CommandId']
            time.sleep(5)

            result = self.ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )

            if result.get('Status') == 'Success':
                output = result.get('StandardOutputContent', '').strip()

                return {
                    'success': True,
                    'logs': output,
                    'log_lines': output.split('\\n')[:100]  # Limit to 100 lines
                }

            return {
                'success': False,
                'error': 'Could not retrieve patch logs'
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _get_system_logs(self, instance_id: str, hours_back: int) -> Dict[str, Any]:
        """Get system logs from the instance."""
        try:
            # Calculate time filter
            since_time = datetime.now() - timedelta(hours=hours_back)
            since_str = since_time.strftime('%Y-%m-%d %H:%M:%S')

            commands = [
                # System logs (journalctl for systemd systems)
                f'journalctl --since="{since_str}" --no-pager 2>/dev/null | tail -100',
                # Syslog (for older systems)
                f'tail -100 /var/log/syslog 2>/dev/null || tail -100 /var/log/messages 2>/dev/null',
                # Kernel logs
                f'dmesg | tail -50',
                # Authentication logs
                f'tail -50 /var/log/secure 2>/dev/null || tail -50 /var/log/auth.log 2>/dev/null'
            ]

            response = self.ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={
                    'commands': commands
                }
            )

            command_id = response['Command']['CommandId']
            time.sleep(5)

            result = self.ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )

            if result.get('Status') == 'Success':
                output = result.get('StandardOutputContent', '').strip()

                return {
                    'success': True,
                    'logs': output,
                    'log_lines': output.split('\\n')[:200]  # Limit to 200 lines
                }

            return {
                'success': False,
                'error': 'Could not retrieve system logs'
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _analyze_patch_errors(self, patch_logs: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze patch logs for error patterns."""
        try:
            if not patch_logs.get('success') or not patch_logs.get('logs'):
                return {
                    'error_count': 0,
                    'patterns': []
                }

            logs = patch_logs.get('logs', '')
            patterns_found = []

            # Common patch error patterns
            error_patterns = {
                'dependency_conflict': [
                    r'dependency.*conflict',
                    r'requires.*but.*installed',
                    r'Conflicts:',
                    r'package.*conflicts'
                ],
                'repository_error': [
                    r'Cannot find a valid baseurl',
                    r'Could not resolve host',
                    r'Repository.*not found',
                    r'404 Not Found'
                ],
                'disk_space': [
                    r'No space left on device',
                    r'Insufficient disk space',
                    r'disk.*full'
                ],
                'permission_denied': [
                    r'Permission denied',
                    r'Access denied',
                    r'Operation not permitted'
                ],
                'package_not_found': [
                    r'No package.*available',
                    r'Package.*not found',
                    r'Unable to locate package'
                ],
                'transaction_error': [
                    r'Transaction check error',
                    r'Transaction failed',
                    r'RPM transaction failed'
                ],
                'lock_error': [
                    r'Could not get lock',
                    r'Another app is currently holding the yum lock',
                    r'waiting for lock'
                ]
            }

            # Search for patterns
            for error_type, patterns in error_patterns.items():
                for pattern in patterns:
                    if re.search(pattern, logs, re.IGNORECASE):
                        patterns_found.append({
                            'type': error_type,
                            'pattern': pattern,
                            'severity': 'high' if error_type in ['dependency_conflict', 'transaction_error'] else 'medium'
                        })
                        break

            # Count total errors
            error_count = len(re.findall(r'error|failed|failure', logs, re.IGNORECASE))

            return {
                'error_count': error_count,
                'patterns': patterns_found,
                'has_critical_errors': any(p['severity'] == 'high' for p in patterns_found)
            }

        except Exception as e:
            return {
                'error_count': 0,
                'patterns': [],
                'error': str(e)
            }

    def _analyze_system_errors(self, system_logs: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze system logs for error patterns."""
        try:
            if not system_logs.get('success') or not system_logs.get('logs'):
                return {
                    'error_count': 0,
                    'patterns': []
                }

            logs = system_logs.get('logs', '')
            patterns_found = []

            # Common system error patterns
            error_patterns = {
                'out_of_memory': [
                    r'Out of memory',
                    r'OOM killer',
                    r'Memory exhausted',
                    r'Cannot allocate memory'
                ],
                'disk_error': [
                    r'I/O error',
                    r'Input/output error',
                    r'disk error',
                    r'filesystem.*error'
                ],
                'kernel_panic': [
                    r'kernel panic',
                    r'Kernel panic',
                    r'BUG:',
                    r'Oops:'
                ],
                'service_failure': [
                    r'service.*failed',
                    r'Failed to start',
                    r'Unit.*entered failed state',
                    r'systemd.*Failed'
                ],
                'network_error': [
                    r'Network is unreachable',
                    r'Connection refused',
                    r'No route to host',
                    r'link.*down'
                ],
                'authentication_failure': [
                    r'authentication failure',
                    r'Failed password',
                    r'Invalid user',
                    r'Access denied'
                ],
                'segfault': [
                    r'segfault',
                    r'Segmentation fault',
                    r'core dumped'
                ]
            }

            # Search for patterns
            for error_type, patterns in error_patterns.items():
                for pattern in patterns:
                    matches = re.findall(pattern, logs, re.IGNORECASE)
                    if matches:
                        patterns_found.append({
                            'type': error_type,
                            'pattern': pattern,
                            'count': len(matches),
                            'severity': 'critical' if error_type in ['kernel_panic', 'out_of_memory', 'segfault'] else 'high'
                        })
                        break

            # Count total errors and warnings
            error_count = len(re.findall(r'error|fail|critical|emergency', logs, re.IGNORECASE))
            warning_count = len(re.findall(r'warning|warn', logs, re.IGNORECASE))

            return {
                'error_count': error_count,
                'warning_count': warning_count,
                'patterns': patterns_found,
                'has_critical_errors': any(p['severity'] == 'critical' for p in patterns_found)
            }

        except Exception as e:
            return {
                'error_count': 0,
                'warning_count': 0,
                'patterns': [],
                'error': str(e)
            }

    def _repair_package_manager(self, instance_id: str) -> Dict[str, Any]:
        """Attempt to repair package manager issues."""
        try:
            # Commands to fix common package manager issues
            repair_commands = [
                # For YUM (RHEL/CentOS/Amazon Linux)
                'if command -v yum >/dev/null 2>&1; then yum clean all && yum makecache; fi',
                # For APT (Ubuntu/Debian)
                'if command -v apt-get >/dev/null 2>&1; then apt-get clean && apt-get update; fi',
                # For DNF (Fedora/RHEL 8+)
                'if command -v dnf >/dev/null 2>&1; then dnf clean all && dnf makecache; fi',
                # Kill stuck package manager processes
                'pkill -9 yum 2>/dev/null; pkill -9 apt-get 2>/dev/null; pkill -9 dpkg 2>/dev/null',
                # Remove lock files
                'rm -f /var/lib/dpkg/lock* /var/lib/apt/lists/lock* /var/cache/apt/archives/lock* 2>/dev/null',
                'rm -f /var/run/yum.pid 2>/dev/null'
            ]

            response = self.ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={
                    'commands': repair_commands
                }
            )

            command_id = response['Command']['CommandId']
            time.sleep(10)  # Give more time for cleanup

            result = self.ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )

            if result.get('Status') == 'Success':
                return {
                    'success': True,
                    'message': 'Package manager repair completed successfully',
                    'output': result.get('StandardOutputContent', '')[:500]
                }
            else:
                return {
                    'success': False,
                    'error': 'Package manager repair failed',
                    'details': result.get('StandardErrorContent', '')[:500]
                }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _restart_ssm_agent(self, instance_id: str) -> Dict[str, Any]:
        """Restart SSM agent on the instance."""
        try:
            # Commands to restart SSM agent on different platforms
            restart_commands = [
                # For systemd systems
                'systemctl restart amazon-ssm-agent 2>/dev/null || systemctl restart ssm-agent 2>/dev/null',
                # For older init systems
                'service amazon-ssm-agent restart 2>/dev/null || service ssm-agent restart 2>/dev/null',
                # For Windows
                'Restart-Service AmazonSSMAgent -Force 2>$null',
                # Verify agent is running
                'sleep 5; systemctl status amazon-ssm-agent 2>/dev/null || service amazon-ssm-agent status 2>/dev/null'
            ]

            response = self.ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={
                    'commands': restart_commands
                }
            )

            command_id = response['Command']['CommandId']
            time.sleep(10)  # Give agent time to restart

            result = self.ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )

            if result.get('Status') == 'Success':
                return {
                    'success': True,
                    'message': 'SSM agent restarted successfully',
                    'output': result.get('StandardOutputContent', '')[:500]
                }
            else:
                return {
                    'success': False,
                    'error': 'SSM agent restart failed',
                    'details': result.get('StandardErrorContent', '')[:500]
                }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _cleanup_temp_files(self, instance_id: str) -> Dict[str, Any]:
        """Cleanup temporary files to free up disk space."""
        try:
            # Commands to clean up temporary files
            cleanup_commands = [
                # Clean package manager cache
                'yum clean all 2>/dev/null',
                'apt-get clean 2>/dev/null',
                'dnf clean all 2>/dev/null',
                # Clean temp directories
                'find /tmp -type f -atime +7 -delete 2>/dev/null',
                'find /var/tmp -type f -atime +7 -delete 2>/dev/null',
                # Clean old logs
                'find /var/log -name "*.gz" -type f -mtime +30 -delete 2>/dev/null',
                'find /var/log -name "*.old" -type f -mtime +30 -delete 2>/dev/null',
                # Truncate large log files
                'for log in /var/log/messages /var/log/syslog; do if [ -f "$log" ] && [ $(stat -c%s "$log") -gt 1073741824 ]; then echo "Truncating $log"; > "$log"; fi; done',
                # Report disk usage after cleanup
                'df -h /'
            ]

            response = self.ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={
                    'commands': cleanup_commands
                }
            )

            command_id = response['Command']['CommandId']
            time.sleep(10)  # Give time for cleanup

            result = self.ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )

            if result.get('Status') == 'Success':
                output = result.get('StandardOutputContent', '')

                # Parse disk usage after cleanup
                disk_usage_after = 'Unknown'
                for line in output.split('\\n'):
                    if '/' in line and '%' in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            disk_usage_after = parts[4]
                            break

                return {
                    'success': True,
                    'message': 'Temporary files cleaned up successfully',
                    'disk_usage_after': disk_usage_after,
                    'output': output[:500]
                }
            else:
                return {
                    'success': False,
                    'error': 'Cleanup failed',
                    'details': result.get('StandardErrorContent', '')[:500]
                }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _generate_diagnostic_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate summary of diagnostic results."""
        total_instances = len(results)
        healthy_instances = sum(1 for r in results.values() if r.get('health_score', 0) >= 80)
        critical_instances = sum(1 for r in results.values() if r.get('health_score', 0) < 50)

        # Aggregate issues
        all_issues = []
        for instance_id, data in results.items():
            if 'issues_found' in data:
                all_issues.extend(data['issues_found'])

        # Count issue types
        issue_counts = {}
        for issue in all_issues:
            issue_type = issue.split(':')[0] if ':' in issue else issue
            issue_counts[issue_type] = issue_counts.get(issue_type, 0) + 1

        return {
            'total_instances': total_instances,
            'healthy_instances': healthy_instances,
            'unhealthy_instances': total_instances - healthy_instances,
            'critical_instances': critical_instances,
            'average_health_score': round(sum(r.get('health_score', 0) for r in results.values()) / total_instances, 1) if total_instances > 0 else 0,
            'common_issues': sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        }
