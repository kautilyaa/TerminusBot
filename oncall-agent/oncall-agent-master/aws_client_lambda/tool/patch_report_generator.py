# patch_report_generator.py
import json
import boto3
import csv
import io
from datetime import datetime, timezone
from typing import Dict, List, Any
import logging

logger = logging.getLogger()

class PatchReportGenerator:
    """Generates comprehensive patch reports in multiple formats"""
    
    def __init__(self, region='us-east-1'):
        self.ssm = boto3.client('ssm', region_name=region)
        self.ec2 = boto3.client('ec2', region_name=region)
        self.s3 = boto3.client('s3', region_name=region)
        self.storage = PatchReportStorage(region)
        
    def generate_comprehensive_report(self, window_id: str, execution_id: str = None) -> Dict:
        """Generate a comprehensive patch report"""
        
        report_id = f"report_{window_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Gather all data
        report = {
            'report_id': report_id,
            'window_id': window_id,
            'execution_id': execution_id,
            'report_type': 'comprehensive',
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'summary': {},
            'by_environment': {},
            'package_updates': [],
            'security_updates': [],
            'failed_patches': [],
            'pending_reboots': [],
            'compliance_metrics': {},
            'recommendations': []
        }
        
        # Get window execution details
        window_data = self._get_window_execution_data(window_id, execution_id)
        report['window_execution'] = window_data
        
        # Get all instances and their patch states
        instance_data = self._get_instance_patch_states(window_data.get('instance_ids', []))
        report['instances'] = instance_data
        
        # Analyze by environment
        report['by_environment'] = self._analyze_by_environment(instance_data)
        
        # Extract package information
        report['package_updates'] = self._extract_package_updates(instance_data)
        
        # Identify security updates
        report['security_updates'] = self._identify_security_updates(report['package_updates'])
        
        # Calculate compliance metrics
        report['compliance_metrics'] = self._calculate_compliance_metrics(instance_data)
        
        # Generate recommendations
        report['recommendations'] = self._generate_recommendations(report)
        
        # Generate summary
        report['summary'] = self._generate_summary(report)
        
        # Save to DynamoDB
        self.storage.save_report(report)
        
        # Generate and upload to S3 if large
        if len(json.dumps(report)) > 400000:  # If > 400KB
            s3_url = self._upload_to_s3(report)
            report['s3_location'] = s3_url
            
            # Store trimmed version in DynamoDB
            trimmed_report = self._trim_report(report)
            self.storage.save_report(trimmed_report)
        
        return report
    
    def _get_window_execution_data(self, window_id: str, execution_id: str = None) -> Dict:
        """Get maintenance window execution details"""
        try:
            # Get window details
            window = self.ssm.get_maintenance_window(WindowId=window_id)
            
            # Get latest execution if not specified
            if not execution_id:
                executions = self.ssm.describe_maintenance_window_executions(
                    WindowId=window_id,
                    MaxResults=1
                )
                if executions['WindowExecutions']:
                    execution_id = executions['WindowExecutions'][0]['WindowExecutionId']
            
            if execution_id:
                # Get execution tasks
                tasks = self.ssm.describe_maintenance_window_execution_tasks(
                    WindowExecutionId=execution_id
                )
                
                # Get all instance IDs
                instance_ids = set()
                for task in tasks.get('WindowExecutionTaskIdentities', []):
                    invocations = self.ssm.describe_maintenance_window_execution_task_invocations(
                        WindowExecutionId=execution_id,
                        TaskId=task['TaskExecutionId']
                    )
                    for inv in invocations.get('WindowExecutionTaskInvocationIdentities', []):
                        if 'Parameters' in inv:
                            ids = inv['Parameters'].get('InstanceIds', [])
                            instance_ids.update(ids)
                
                return {
                    'window_name': window.get('Name'),
                    'execution_id': execution_id,
                    'instance_ids': list(instance_ids),
                    'task_count': len(tasks.get('WindowExecutionTaskIdentities', []))
                }
            
            return {'window_name': window.get('Name'), 'instance_ids': []}
            
        except Exception as e:
            logger.error(f"Error getting window data: {e}")
            return {}
    
    def _get_instance_patch_states(self, instance_ids: List[str]) -> List[Dict]:
        """Get detailed patch states for instances"""
        results = []
        
        if not instance_ids:
            return results
        
        # Get EC2 details
        ec2_data = {}
        try:
            response = self.ec2.describe_instances(InstanceIds=instance_ids)
            for reservation in response['Reservations']:
                for instance in reservation['Instances']:
                    tags = {tag['Key']: tag['Value'] for tag in instance.get('Tags', [])}
                    ec2_data[instance['InstanceId']] = {
                        'name': tags.get('Name', 'N/A'),
                        'environment': tags.get('Environment', tags.get('Env', 'unknown')),
                        'application': tags.get('Application', tags.get('App', 'N/A')),
                        'instance_type': instance['InstanceType'],
                        'platform': instance.get('Platform', 'Linux')
                    }
        except Exception as e:
            logger.error(f"Error getting EC2 data: {e}")
        
        # Get patch states
        try:
            patch_states = self.ssm.describe_instance_patch_states(
                InstanceIds=instance_ids
            )
            
            for state in patch_states.get('InstancePatchStates', []):
                instance_id = state['InstanceId']
                
                # Get detailed patches
                patches = []
                try:
                    patch_response = self.ssm.describe_instance_patches(
                        InstanceId=instance_id,
                        MaxResults=100
                    )
                    patches = patch_response.get('Patches', [])
                except:
                    pass
                
                instance_info = {
                    'instance_id': instance_id,
                    **ec2_data.get(instance_id, {}),
                    'patch_state': {
                        'installed_count': state.get('InstalledCount', 0),
                        'installed_pending_reboot': state.get('InstalledPendingRebootCount', 0),
                        'missing_count': state.get('MissingCount', 0),
                        'failed_count': state.get('FailedCount', 0),
                        'not_applicable_count': state.get('NotApplicableCount', 0),
                        'operation': state.get('Operation', 'N/A'),
                        'reboot_option': state.get('RebootOption', 'N/A')
                    },
                    'patches': patches,
                    'compliance_status': self._determine_compliance_status(state)
                }
                
                results.append(instance_info)
                
        except Exception as e:
            logger.error(f"Error getting patch states: {e}")
        
        return results
    
    def _determine_compliance_status(self, state: Dict) -> str:
        """Determine compliance status from patch state"""
        if state.get('FailedCount', 0) > 0:
            return 'CRITICAL'
        elif state.get('MissingCount', 0) > 0:
            return 'NON_COMPLIANT'
        elif state.get('InstalledPendingRebootCount', 0) > 0:
            return 'PENDING_REBOOT'
        else:
            return 'COMPLIANT'
    
    def _analyze_by_environment(self, instances: List[Dict]) -> Dict:
        """Analyze patch status by environment"""
        environments = {}
        
        for instance in instances:
            env = instance.get('environment', 'unknown')
            
            if env not in environments:
                environments[env] = {
                    'total': 0,
                    'compliant': 0,
                    'non_compliant': 0,
                    'critical': 0,
                    'pending_reboot': 0,
                    'instances': []
                }
            
            environments[env]['total'] += 1
            environments[env]['instances'].append(instance['instance_id'])
            
            status = instance.get('compliance_status', 'UNKNOWN')
            if status == 'COMPLIANT':
                environments[env]['compliant'] += 1
            elif status == 'NON_COMPLIANT':
                environments[env]['non_compliant'] += 1
            elif status == 'CRITICAL':
                environments[env]['critical'] += 1
            elif status == 'PENDING_REBOOT':
                environments[env]['pending_reboot'] += 1
        
        # Calculate percentages
        for env in environments.values():
            if env['total'] > 0:
                env['compliance_percentage'] = (env['compliant'] / env['total']) * 100
        
        return environments
    
    def _extract_package_updates(self, instances: List[Dict]) -> List[Dict]:
        """Extract unique package updates across all instances"""
        package_map = {}
        
        for instance in instances:
            for patch in instance.get('patches', []):
                if patch.get('State') in ['INSTALLED', 'INSTALLED_PENDING_REBOOT']:
                    pkg_key = f"{patch.get('Title', 'Unknown')}_{patch.get('KBId', '')}"
                    
                    if pkg_key not in package_map:
                        package_map[pkg_key] = {
                            'name': patch.get('Title', 'Unknown'),
                            'kb_id': patch.get('KBId', 'N/A'),
                            'classification': patch.get('Classification', 'N/A'),
                            'severity': patch.get('Severity', 'N/A'),
                            'cve_ids': patch.get('CVEIds', []),
                            'instances': [],
                            'install_count': 0
                        }
                    
                    package_map[pkg_key]['instances'].append(instance['instance_id'])
                    package_map[pkg_key]['install_count'] += 1
        
        # Sort by install count
        packages = list(package_map.values())
        packages.sort(key=lambda x: x['install_count'], reverse=True)
        
        return packages
    
    def _identify_security_updates(self, packages: List[Dict]) -> List[Dict]:
        """Identify security-related updates"""
        security_updates = []
        
        security_keywords = ['Security', 'Critical', 'Important', 'CVE']
        
        for package in packages:
            is_security = False
            
            # Check classification
            if any(keyword in package.get('classification', '') for keyword in security_keywords):
                is_security = True
            
            # Check severity
            if package.get('severity') in ['Critical', 'Important', 'High']:
                is_security = True
            
            # Check for CVEs
            if package.get('cve_ids'):
                is_security = True
            
            if is_security:
                security_updates.append(package)
        
        return security_updates
    
    def _calculate_compliance_metrics(self, instances: List[Dict]) -> Dict:
        """Calculate overall compliance metrics"""
        metrics = {
            'total_instances': len(instances),
            'compliant': 0,
            'non_compliant': 0,
            'critical': 0,
            'pending_reboot': 0,
            'total_patches_installed': 0,
            'total_patches_failed': 0,
            'total_patches_missing': 0,
            'compliance_percentage': 0
        }
        
        for instance in instances:
            status = instance.get('compliance_status', 'UNKNOWN')
            if status == 'COMPLIANT':
                metrics['compliant'] += 1
            elif status == 'NON_COMPLIANT':
                metrics['non_compliant'] += 1
            elif status == 'CRITICAL':
                metrics['critical'] += 1
            elif status == 'PENDING_REBOOT':
                metrics['pending_reboot'] += 1
            
            patch_state = instance.get('patch_state', {})
            metrics['total_patches_installed'] += patch_state.get('installed_count', 0)
            metrics['total_patches_failed'] += patch_state.get('failed_count', 0)
            metrics['total_patches_missing'] += patch_state.get('missing_count', 0)
        
        if metrics['total_instances'] > 0:
            metrics['compliance_percentage'] = (metrics['compliant'] / metrics['total_instances']) * 100
        
        return metrics
    
    def _generate_recommendations(self, report: Dict) -> List[Dict]:
        """Generate actionable recommendations"""
        recommendations = []
        
        metrics = report.get('compliance_metrics', {})
        
        # Critical patches
        if metrics.get('critical', 0) > 0:
            recommendations.append({
                'priority': 'CRITICAL',
                'title': 'Address Critical Patch Failures',
                'description': f"{metrics['critical']} instances have critical patch failures",
                'action': 'Investigate and remediate failed patches immediately',
                'command': '/aws diagnose patch failures for critical instances'
            })
        
        # Missing patches
        if metrics.get('total_patches_missing', 0) > 0:
            recommendations.append({
                'priority': 'HIGH',
                'title': 'Apply Missing Patches',
                'description': f"{metrics['total_patches_missing']} patches are missing across instances",
                'action': 'Schedule patch installation for non-compliant instances',
                'command': '/aws apply patches to non-compliant instances'
            })
        
        # Pending reboots
        if metrics.get('pending_reboot', 0) > 0:
            recommendations.append({
                'priority': 'MEDIUM',
                'title': 'Schedule Instance Reboots',
                'description': f"{metrics['pending_reboot']} instances require reboot",
                'action': 'Schedule reboots during next maintenance window',
                'command': '/aws schedule reboot for pending instances'
            })
        
        # Security updates
        security_updates = report.get('security_updates', [])
        if len(security_updates) > 0:
            critical_security = [u for u in security_updates if u.get('severity') == 'Critical']
            if critical_security:
                recommendations.append({
                    'priority': 'CRITICAL',
                    'title': 'Critical Security Updates',
                    'description': f"{len(critical_security)} critical security updates identified",
                    'action': 'Apply critical security patches immediately',
                    'command': '/aws apply critical security patches'
                })
        
        # Low compliance environments
        by_env = report.get('by_environment', {})
        for env_name, env_data in by_env.items():
            if env_data.get('compliance_percentage', 100) < 80:
                recommendations.append({
                    'priority': 'HIGH',
                    'title': f'Low Compliance in {env_name.upper()}',
                    'description': f"Only {env_data['compliance_percentage']:.1f}% compliant",
                    'action': f'Focus patch efforts on {env_name} environment',
                    'command': f'/aws generate patch plan for {env_name}'
                })
        
        return recommendations
    
    def _generate_summary(self, report: Dict) -> Dict:
        """Generate executive summary"""
        metrics = report.get('compliance_metrics', {})
        by_env = report.get('by_environment', {})
        recommendations = report.get('recommendations', [])
        
        summary = {
            'overall_status': self._determine_overall_status(metrics),
            'compliance_percentage': metrics.get('compliance_percentage', 0),
            'total_instances': metrics.get('total_instances', 0),
            'critical_issues': len([r for r in recommendations if r['priority'] == 'CRITICAL']),
            'environments_checked': list(by_env.keys()),
            'total_patches_applied': metrics.get('total_patches_installed', 0),
            'action_items': len(recommendations)
        }
        
        return summary
    
    def _determine_overall_status(self, metrics: Dict) -> str:
        """Determine overall patch status"""
        if metrics.get('critical', 0) > 0:
            return 'CRITICAL'
        elif metrics.get('compliance_percentage', 0) < 80:
            return 'WARNING'
        elif metrics.get('compliance_percentage', 0) < 95:
            return 'ATTENTION'
        else:
            return 'HEALTHY'
    
    def _upload_to_s3(self, report: Dict) -> str:
        """Upload full report to S3"""
        bucket = os.environ.get('PATCH_REPORTS_BUCKET', 'patch-reports')
        key = f"reports/{report['window_id']}/{report['report_id']}.json"
        
        try:
            self.s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=json.dumps(report, indent=2),
                ContentType='application/json',
                ServerSideEncryption='AES256'
            )
            
            # Generate presigned URL (valid for 7 days)
            url = self.s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket, 'Key': key},
                ExpiresIn=604800
            )
            
            return url
            
        except Exception as e:
            logger.error(f"Error uploading to S3: {e}")
            return None
    
    def _trim_report(self, report: Dict) -> Dict:
        """Trim report for DynamoDB storage"""
        trimmed = report.copy()
        
        # Keep only summary data
        if 'instances' in trimmed:
            trimmed['instance_count'] = len(trimmed['instances'])
            del trimmed['instances']
        
        if 'patches' in trimmed:
            del trimmed['patches']
        
        # Limit package updates to top 10
        if 'package_updates' in trimmed:
            trimmed['package_updates'] = trimmed['package_updates'][:10]
        
        return trimmed
    
    def generate_csv_report(self, report: Dict) -> str:
        """Generate CSV format report"""
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            'Instance ID', 'Name', 'Environment', 'Compliance Status',
            'Installed', 'Pending Reboot', 'Missing', 'Failed'
        ])
        
        # Write instance data
        for instance in report.get('instances', []):
            patch_state = instance.get('patch_state', {})
            writer.writerow([
                instance['instance_id'],
                instance.get('name', 'N/A'),
                instance.get('environment', 'unknown'),
                instance.get('compliance_status', 'UNKNOWN'),
                patch_state.get('installed_count', 0),
                patch_state.get('installed_pending_reboot', 0),
                patch_state.get('missing_count', 0),
                patch_state.get('failed_count', 0)
            ])
        
        return output.getvalue()
    
    def format_for_slack(self, report: Dict) -> str:
        """Format report for Slack message"""
        summary = report.get('summary', {})
        metrics = report.get('compliance_metrics', {})
        by_env = report.get('by_environment', {})
        recommendations = report.get('recommendations', [])
        
        # Determine emoji based on status
        status_emoji = {
            'CRITICAL': '🔴',
            'WARNING': '🟡',
            'ATTENTION': '🟠',
            'HEALTHY': '🟢'
        }.get(summary.get('overall_status', 'UNKNOWN'), '⚪')
        
        # Build Slack message
        slack_text = f"""{status_emoji} *Patch Compliance Report*
*Report ID:* `{report['report_id']}`
*Generated:* {report['generated_at']}

📊 *Executive Summary*
• *Overall Status:* {summary.get('overall_status', 'UNKNOWN')}
• *Compliance:* {summary.get('compliance_percentage', 0):.1f}%
• *Total Instances:* {summary.get('total_instances', 0)}
• *Patches Applied:* {summary.get('total_patches_applied', 0)}
• *Critical Issues:* {summary.get('critical_issues', 0)}

🏢 *By Environment*"""
        
        for env_name, env_data in by_env.items():
            env_emoji = '✅' if env_data['compliance_percentage'] >= 95 else '⚠️'
            slack_text += f"""
*{env_name.upper()}:* {env_emoji}
  • Compliance: {env_data['compliance_percentage']:.1f}%
  • Instances: {env_data['total']} (✅ {env_data['compliant']} | ❌ {env_data['non_compliant']} | ⚠️ {env_data['pending_reboot']})"""
        
        # Add top recommendations
        if recommendations:
            slack_text += "\n\n🎯 *Top Recommendations*"
            for rec in recommendations[:3]:
                priority_emoji = {
                    'CRITICAL': '🔴',
                    'HIGH': '🟠',
                    'MEDIUM': '🟡',
                    'LOW': '🟢'
                }.get(rec['priority'], '⚪')
                
                slack_text += f"""
{priority_emoji} *{rec['title']}*
  • {rec['description']}
  • Action: `{rec['command']}`"""
        
        # Add report access info
        if report.get('s3_location'):
            slack_text += f"\n\n📄 *Full Report:* <{report['s3_location']}|Download>"
        
        slack_text += f"""

🔧 *Quick Actions*
• View details: `/aws show report {report['report_id']}`
• Apply patches: `/aws apply patches from report {report['report_id']}`
• Generate remediation: `/aws generate remediation plan {report['report_id']}`"""
        
        return slack_text