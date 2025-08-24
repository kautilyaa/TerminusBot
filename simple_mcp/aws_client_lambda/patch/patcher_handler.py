import boto3
import csv
from datetime import datetime, timedelta, timezone
import json
from typing import List, Dict, Optional, Set
from collections import defaultdict

class MaintenanceWindowPackageExtractor:
    def __init__(self, region_name='us-east-1', debug=True):
        """Initialize AWS clients"""
        self.ssm_client = boto3.client('ssm', region_name=region_name)
        self.ec2_client = boto3.client('ec2', region_name=region_name)
        self.region = region_name
        self.debug = debug
    
    def debug_print(self, message):
        """Print debug messages if debug mode is on"""
        if self.debug:
            print(f"[DEBUG] {message}")
    
    def get_instance_details(self, instance_ids: List[str]) -> Dict[str, Dict]:
        """Get EC2 instance details"""
        instance_details = {}
        if not instance_ids:
            return instance_details
        
        try:
            # Process in batches of 100 (AWS limit)
            for i in range(0, len(instance_ids), 100):
                batch = instance_ids[i:i+100]
                response = self.ec2_client.describe_instances(InstanceIds=batch)
                
                for reservation in response['Reservations']:
                    for instance in reservation['Instances']:
                        instance_id = instance['InstanceId']
                        instance_details[instance_id] = {
                            'Name': self._get_tag_value(instance.get('Tags', []), 'Name'),
                            'State': instance['State']['Name'],
                            'InstanceType': instance['InstanceType'],
                            'Platform': instance.get('Platform', 'Linux/UNIX'),
                            'LaunchTime': instance['LaunchTime'].isoformat() if instance.get('LaunchTime') else ''
                        }
        except Exception as e:
            self.debug_print(f"Error getting instance details: {e}")
        
        return instance_details
    
    def _get_tag_value(self, tags: List[Dict], key: str) -> str:
        """Get tag value from tag list"""
        for tag in tags:
            if tag.get('Key') == key:
                return tag.get('Value', '')
        return ''
    
    def get_latest_patched_instances(self, days_back: int = 7) -> Dict[str, Dict]:
        """Get instances that were patched recently"""
        latest_patches = {}
        # Make cutoff_date timezone-aware (UTC)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
        
        # Get all maintenance windows
        windows = []
        paginator = self.ssm_client.get_paginator('describe_maintenance_windows')
        for page in paginator.paginate():
            windows.extend(page['WindowIdentities'])
        
        print(f"Checking {len(windows)} maintenance windows for recent executions...")
        
        for window in windows:
            window_id = window['WindowId']
            window_name = window.get('Name', 'Unnamed')
            
            # Get all executions for this window
            executions = []
            paginator = self.ssm_client.get_paginator('describe_maintenance_window_executions')
            
            try:
                for page in paginator.paginate(WindowId=window_id):
                    executions.extend(page['WindowExecutions'])
            except Exception as e:
                self.debug_print(f"Error getting executions for window {window_id}: {e}")
                continue
            
            # Filter executions by date
            recent_executions = []
            for ex in executions:
                if ex.get('StartTime'):
                    # Ensure StartTime is timezone-aware
                    start_time = ex['StartTime']
                    if start_time.tzinfo is None:
                        # If naive, assume UTC
                        start_time = start_time.replace(tzinfo=timezone.utc)
                    
                    if start_time >= cutoff_date:
                        recent_executions.append(ex)
            
            self.debug_print(f"Window {window_name}: {len(recent_executions)} recent executions out of {len(executions)} total")
            
            # Process each recent execution
            for execution in recent_executions:
                execution_id = execution['WindowExecutionId']
                execution_time = execution.get('StartTime')
                
                # Get tasks
                tasks = []
                paginator = self.ssm_client.get_paginator('describe_maintenance_window_execution_tasks')
                
                try:
                    for page in paginator.paginate(WindowExecutionId=execution_id):
                        tasks.extend(page['WindowExecutionTaskIdentities'])
                except Exception as e:
                    self.debug_print(f"Error getting tasks for execution {execution_id}: {e}")
                    continue
                
                for task in tasks:
                    if task.get('TaskType') == 'RUN_COMMAND':
                        task_id = task['TaskExecutionId']
                        
                        try:
                            # Get invocations
                            invocations = self.ssm_client.describe_maintenance_window_execution_task_invocations(
                                WindowExecutionId=execution_id,
                                TaskId=task_id
                            ).get('WindowExecutionTaskInvocationIdentities', [])
                            
                            for invocation in invocations:
                                instance_id = invocation.get('InstanceId')
                                if instance_id:
                                    # Track latest patch time for each instance
                                    if instance_id not in latest_patches or latest_patches[instance_id]['execution_time'] < execution_time:
                                        latest_patches[instance_id] = {
                                            'window_id': window_id,
                                            'window_name': window_name,
                                            'execution_id': execution_id,
                                            'execution_time': execution_time,
                                            'task_id': task_id,
                                            'command_id': invocation.get('ExecutionId'),
                                            'status': invocation.get('Status')
                                        }
                        except Exception as e:
                            self.debug_print(f"Error processing task: {e}")
        
        return latest_patches
    
    def get_packages_from_command(self, command_id: str, instance_id: str) -> List[Dict]:
        """Extract packages from a command execution"""
        packages = []
        
        try:
            details = self.ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )
            
            if details.get('Status') == 'Success':
                output = details.get('StandardOutputContent', '')
                command_name = details.get('DocumentName', '')
                
                if output:
                    if self.debug:
                        filename = f"output_{instance_id}_{command_id[:8]}.txt"
                        with open(filename, 'w') as f:
                            f.write(output)
                        self.debug_print(f"Saved output to {filename}")
                    
                    packages = self.extract_packages_from_output(output, command_name)
        
        except Exception as e:
            self.debug_print(f"Error getting command output: {e}")
        
        return packages
    
    def get_packages_from_inventory(self, instance_id: str) -> List[Dict]:
        """Get packages from SSM Inventory"""
        packages = []
        
        try:
            # Get inventory for AWS:Application type
            response = self.ssm_client.list_inventory_entries(
                InstanceId=instance_id,
                TypeName='AWS:Application',
                MaxResults=50
            )
            
            for entry in response.get('Entries', []):
                packages.append({
                    'name': entry.get('Name', ''),
                    'version': entry.get('Version', ''),
                    'full_line': f"{entry.get('Name', '')} {entry.get('Version', '')}"
                })
            
            # Continue pagination if needed
            while response.get('NextToken'):
                response = self.ssm_client.list_inventory_entries(
                    InstanceId=instance_id,
                    TypeName='AWS:Application',
                    NextToken=response['NextToken'],
                    MaxResults=50
                )
                
                for entry in response.get('Entries', []):
                    packages.append({
                        'name': entry.get('Name', ''),
                        'version': entry.get('Version', ''),
                        'full_line': f"{entry.get('Name', '')} {entry.get('Version', '')}"
                    })
            
            self.debug_print(f"Found {len(packages)} packages from inventory for {instance_id}")
            
        except Exception as e:
            self.debug_print(f"Error getting inventory: {e}")
        
        return packages
    
    def extract_packages_from_output(self, output: str, command_name: str = None) -> List[Dict]:
        """Extract package information from command output"""
        packages = []
        
        if not output:
            return packages
        
        lines = output.strip().split('\n')
        self.debug_print(f"Parsing {len(lines)} lines from command output (command: {command_name})")
        
        # AWS-RunPatchBaseline specific parsing
        if 'AWS-RunPatchBaseline' in str(command_name):
            self.debug_print("Using AWS-RunPatchBaseline parser")
            in_installed_section = False
            
            for line in lines:
                # Look for the installed packages section
                if 'Installed:' in line:
                    in_installed_section = True
                    self.debug_print("Found 'Installed:' section")
                    continue
                elif any(section in line for section in ['Missing:', 'Failed:', 'InstalledRejected:']):
                    in_installed_section = False
                    continue
                
                if in_installed_section and line.strip():
                    # Parse package line (usually format: package-name.arch version)
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        package_name = parts[0]
                        # Remove architecture suffix if present
                        if '.' in package_name:
                            name_parts = package_name.rsplit('.', 1)
                            if name_parts[-1] in ['x86_64', 'i386', 'i686', 'noarch', 'aarch64']:
                                package_name = name_parts[0]
                        
                        packages.append({
                            'name': package_name,
                            'version': parts[1],
                            'full_line': line.strip()
                        })
        
        # If no packages found and it's a patch baseline, look for different patterns
        if not packages and 'AWS-RunPatchBaseline' in str(command_name):
            self.debug_print("No packages found in Installed section, trying alternative parsing")
            for line in lines:
                line = line.strip()
                # Look for package patterns
                if line and not any(skip in line for skip in ['Step', 'Patch', 'reboot', 'No packages']):
                    if '.' in line and any(arch in line for arch in ['x86_64', 'i386', 'noarch']):
                        parts = line.split()
                        if len(parts) >= 2:
                            package_name = parts[0].rsplit('.', 1)[0]
                            packages.append({
                                'name': package_name,
                                'version': parts[1] if len(parts) > 1 else 'N/A',
                                'full_line': line
                            })
        
        # Standard package manager outputs
        elif 'dpkg' in str(command_name):
            self.debug_print("Using dpkg parser")
            for line in lines:
                if line.startswith('ii '):
                    parts = line.split(None, 3)
                    if len(parts) >= 3:
                        packages.append({
                            'name': parts[1],
                            'version': parts[2],
                            'full_line': line
                        })
        
        elif any(pm in str(command_name) for pm in ['yum', 'dnf']):
            self.debug_print("Using yum/dnf parser")
            for line in lines:
                line = line.strip()
                if not line or line.startswith(('Loaded', 'Installed', 'Last metadata')):
                    continue
                
                parts = line.split()
                if len(parts) >= 2:
                    package_name = parts[0]
                    if '.' in package_name:
                        package_name = package_name.rsplit('.', 1)[0]
                    
                    packages.append({
                        'name': package_name,
                        'version': parts[1] if len(parts) > 1 else 'N/A',
                        'full_line': line
                    })
        
        else:
            # Generic parsing - try to identify package lines
            self.debug_print("Using generic parser")
            for line in lines:
                line = line.strip()
                if not line or any(skip in line.lower() for skip in ['loading', 'loaded', 'package', '======', '------']):
                    continue
                
                # Skip lines that look like headers or status messages
                if line.startswith(('Total', 'Complete', 'Downloading', 'Installing')):
                    continue
                
                parts = line.split()
                if parts and len(parts[0]) > 2:  # Basic sanity check
                    packages.append({
                        'name': parts[0],
                        'version': parts[1] if len(parts) > 1 else 'N/A',
                        'full_line': line
                    })
        
        self.debug_print(f"Extracted {len(packages)} packages")
        return packages
    
    def get_packages_by_instance(self, instance_id: str) -> List[Dict]:
        """Get installed packages for a specific instance using various methods"""
        packages = []
        
        # Method 1: Try to get from latest patch execution
        latest_patch_info = self.get_latest_patch_info_for_instance(instance_id)
        if latest_patch_info and latest_patch_info.get('command_id'):
            self.debug_print(f"Trying to get packages from patch command {latest_patch_info['command_id']}")
            packages = self.get_packages_from_command(
                latest_patch_info['command_id'],
                instance_id
            )
        
        # Method 2: If no packages from patch, try SSM Inventory
        if not packages:
            self.debug_print("No packages from patch command, trying SSM Inventory")
            packages = self.get_packages_from_inventory(instance_id)
        
        return packages
    
    def get_latest_patch_info_for_instance(self, instance_id: str) -> Optional[Dict]:
        """Get the latest patch execution info for a specific instance"""
        latest_patches = self.get_latest_patched_instances(days_back=30)
        return latest_patches.get(instance_id)
    
    def get_packages_for_latest_instances(self, top_n: int = None) -> Dict[str, List[Dict]]:
        """Get packages for the most recently patched instances"""
        # Get latest patched instances
        latest_patches = self.get_latest_patched_instances(days_back=30)
        
        if not latest_patches:
            print("No recently patched instances found")
            return {}
        
        # Sort by execution time (most recent first)
        sorted_instances = sorted(
            latest_patches.items(),
            key=lambda x: x[1]['execution_time'],
            reverse=True
        )
        
        # Limit to top N if specified
        if top_n:
            sorted_instances = sorted_instances[:top_n]
        
        print(f"\nFound {len(sorted_instances)} recently patched instances")
        
        # Get instance details
        instance_ids = [inst[0] for inst in sorted_instances]
        instance_details = self.get_instance_details(instance_ids)
        
        # Get packages for each instance
        all_packages = {}
        
        for instance_id, patch_info in sorted_instances:
            instance_name = instance_details.get(instance_id, {}).get('Name', 'Unknown')
            print(f"\nProcessing instance: {instance_id} ({instance_name})")
            print(f"  Last patched: {patch_info['execution_time']}")
            print(f"  Window: {patch_info['window_name']}")
            
            packages = self.get_packages_by_instance(instance_id)
            
            if packages:
                print(f"  Found {len(packages)} packages")
                # Add metadata to packages
                for pkg in packages:
                    pkg.update({
                        'instance_id': instance_id,
                        'instance_name': instance_name,
                        'last_patch_time': patch_info['execution_time'].isoformat() if patch_info['execution_time'] else '',
                        'window_name': patch_info['window_name'],
                        'window_id': patch_info['window_id']
                    })
                all_packages[instance_id] = packages
            else:
                print(f"  No packages found")
        
        return all_packages
    
    def export_latest_instances_to_csv(self, packages_by_instance: Dict[str, List[Dict]], 
                                     filename: str = None):
        """Export packages from latest instances to CSV"""
        if not filename:
            filename = f'latest_instances_packages_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        
        all_packages = []
        for instance_id, packages in packages_by_instance.items():
            all_packages.extend(packages)
        
        if not all_packages:
            print("No packages to export")
            # Create empty CSV with headers
            fieldnames = ['instance_id', 'instance_name', 'package_name', 'version', 
                          'last_patch_time', 'window_name', 'window_id', 'full_line']
            
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
            
            print(f"Created empty CSV: {filename}")
            return
        
        fieldnames = ['instance_id', 'instance_name', 'package_name', 'version', 
                      'last_patch_time', 'window_name', 'window_id', 'full_line']
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for pkg in all_packages:
                writer.writerow({
                    'instance_id': pkg.get('instance_id', ''),
                    'instance_name': pkg.get('instance_name', ''),
                    'package_name': pkg.get('name', ''),
                    'version': pkg.get('version', ''),
                    'last_patch_time': pkg.get('last_patch_time', ''),
                    'window_name': pkg.get('window_name', ''),
                    'window_id': pkg.get('window_id', ''),
                    'full_line': pkg.get('full_line', '')
                })
        
        print(f"\nExported {len(all_packages)} packages to {filename}")
        
        # Also create a summary file
        summary_filename = f'latest_instances_summary_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        with open(summary_filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Instance ID', 'Instance Name', 'Package Count', 'Last Patch Time', 'Window Name'])
            
            for instance_id, packages in packages_by_instance.items():
                if packages:
                    writer.writerow([
                        instance_id,
                        packages[0].get('instance_name', ''),
                        len(packages),
                        packages[0].get('last_patch_time', ''),
                        packages[0].get('window_name', '')
                    ])
        
        print(f"Created summary file: {summary_filename}")

# Example usage
if __name__ == "__main__":
    # Initialize the extractor
    extractor = MaintenanceWindowPackageExtractor(region_name='us-east-1', debug=True)
    
    # Option 1: Get packages for top 5 most recently patched instances
    print("Getting packages for most recently patched instances...")
    packages = extractor.get_packages_for_latest_instances(top_n=5)
    extractor.export_latest_instances_to_csv(packages)
    
    # Option 2: Get packages for a specific instance (uncomment to use)
    # instance_id = "i-0ff2a974711381e6a"  # Replace with your instance ID
    # packages_dict = {}
    # packages = extractor.get_packages_by_instance(instance_id)
    # if packages:
    #     print(f"Found {len(packages)} packages for instance {instance_id}")
    #     # Add instance metadata
    #     for pkg in packages:
    #         pkg.update({
    #             'instance_id': instance_id,
    #             'instance_name': 'Manual Check',
    #             'last_patch_time': datetime.now(timezone.utc).isoformat(),
    #             'window_name': 'Manual',
    #             'window_id': 'manual'
    #         })
    #     packages_dict[instance_id] = packages
    #     extractor.export_latest_instances_to_csv(packages_dict)