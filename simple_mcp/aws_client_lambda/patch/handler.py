import boto3
import csv
from datetime import datetime
import json
from typing import List, Dict, Optional
import os

pwd = os.getcwd()

class MaintenanceWindowPackageExtractor:
    def __init__(self, region_name='us-east-1', debug=True):
        """Initialize AWS clients"""
        self.ssm_client = boto3.client('ssm', region_name=region_name)
        self.region = region_name
        self.debug = debug
    
    def debug_print(self, message):
        """Print debug messages if debug mode is on"""
        if self.debug:
            print(f"[DEBUG] {message}")
    
    def get_maintenance_windows(self) -> List[Dict]:
        """Get all maintenance windows"""
        windows = []
        paginator = self.ssm_client.get_paginator('describe_maintenance_windows')
        
        for page in paginator.paginate():
            windows.extend(page['WindowIdentities'])
        
        return windows
    
    def get_maintenance_window_executions(self, window_id: str) -> List[Dict]:
        """Get executions for a specific maintenance window"""
        executions = []
        paginator = self.ssm_client.get_paginator('describe_maintenance_window_executions')
        
        for page in paginator.paginate(WindowId=window_id):
            executions.extend(page['WindowExecutions'])
        
        return executions
    
    def get_maintenance_window_execution_tasks(self, window_execution_id: str) -> List[Dict]:
        """Get tasks for a specific maintenance window execution"""
        tasks = []
        paginator = self.ssm_client.get_paginator('describe_maintenance_window_execution_tasks')
        
        for page in paginator.paginate(WindowExecutionId=window_execution_id):
            tasks.extend(page['WindowExecutionTaskIdentities'])
        
        return tasks
    
    def get_command_invocation_details(self, command_id: str, instance_id: str) -> Optional[Dict]:
        """Get details of a specific command invocation"""
        try:
            response = self.ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )
            return response
        except Exception as e:
            self.debug_print(f"Error getting command details for command {command_id}, instance {instance_id}: {e}")
            return None
    
    def save_raw_output(self, output: str, instance_id: str, command_id: str):
        """Save raw command output for debugging"""
        if output:
            filename = f"raw_output_{instance_id}_{command_id[:8]}.txt"
            with open(filename, 'w') as f:
                f.write(output)
            self.debug_print(f"Saved raw output to {filename}")
    
    def extract_packages_from_output(self, output: str, command_name: str = None) -> List[Dict]:
        """Extract package information from command output"""
        packages = []
        
        if not output:
            self.debug_print("No output to parse")
            return packages
        
        lines = output.strip().split('\n')
        self.debug_print(f"Total lines to parse: {len(lines)}")
        
        # Try to detect the command/format type
        if command_name:
            self.debug_print(f"Command name: {command_name}")
        
        # Different parsing strategies based on command type or output format
        
        # Strategy 1: AWS-RunPatchBaseline output
        if 'AWS-RunPatchBaseline' in str(command_name) or 'PatchSummary' in output:
            self.debug_print("Detected AWS-RunPatchBaseline format")
            in_package_section = False
            
            for line in lines:
                line = line.strip()
                
                # Look for installed packages section
                if 'Installed:' in line or 'installed_packages' in line.lower():
                    in_package_section = True
                    continue
                elif 'Updated:' in line or 'Missing:' in line or 'Failed:' in line:
                    in_package_section = False
                    continue
                
                if in_package_section and line and not line.startswith(('=', '-', '#')):
                    # Parse package line
                    parts = line.split()
                    if parts:
                        packages.append({
                            'name': parts[0],
                            'version': parts[1] if len(parts) > 1 else 'N/A',
                            'full_line': line
                        })
        
        # Strategy 2: yum list installed output
        elif 'yum' in str(command_name) or '.amzn' in output or '.el' in output:
            self.debug_print("Detected yum format")
            for line in lines:
                line = line.strip()
                if not line or line.startswith(('Loaded', 'Installed', 'Available', 'Updated')):
                    continue
                
                # yum format: package-name.arch    version    repo
                parts = line.split()
                if len(parts) >= 2:
                    package_name = parts[0]
                    # Remove architecture suffix
                    if '.' in package_name:
                        name_parts = package_name.rsplit('.', 1)
                        if name_parts[-1] in ['x86_64', 'i386', 'i686', 'noarch', 'aarch64']:
                            package_name = name_parts[0]
                    
                    packages.append({
                        'name': package_name,
                        'version': parts[1] if len(parts) > 1 else 'N/A',
                        'full_line': line
                    })
        
        # Strategy 3: apt/dpkg output
        elif 'dpkg' in str(command_name) or 'apt' in str(command_name) or 'ii  ' in output:
            self.debug_print("Detected apt/dpkg format")
            for line in lines:
                if line.startswith('ii '):
                    # dpkg format: ii  package-name  version  description
                    parts = line.split(None, 3)
                    if len(parts) >= 3:
                        packages.append({
                            'name': parts[1],
                            'version': parts[2],
                            'full_line': line
                        })
        
        # Strategy 4: Generic parsing
        else:
            self.debug_print("Using generic parsing")
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Skip common header lines
                skip_patterns = ['Package', 'Loading', 'Loaded', '======', '------', 'Name', 'Version']
                if any(pattern in line for pattern in skip_patterns):
                    continue
                
                # Try to parse as space or tab separated
                if '\t' in line:
                    parts = line.split('\t')
                else:
                    parts = line.split()
                
                if parts and len(parts[0]) > 2:  # Basic sanity check
                    packages.append({
                        'name': parts[0],
                        'version': parts[1] if len(parts) > 1 else 'N/A',
                        'full_line': line
                    })
        
        self.debug_print(f"Extracted {len(packages)} packages")
        return packages
    
    def get_packages_from_maintenance_window(self, window_id: str, execution_id: str = None) -> List[Dict]:
        """Get all packages from a maintenance window execution"""
        all_packages = []
        
        # If no execution_id provided, get the latest
        if not execution_id:
            executions = self.get_maintenance_window_executions(window_id)
            if not executions:
                print(f"No executions found for window {window_id}")
                return []
            
            # Sort by StartTime and get the latest
            executions.sort(key=lambda x: x.get('StartTime', datetime.min), reverse=True)
            execution_id = executions[0]['WindowExecutionId']
            print(f"Using latest execution: {execution_id}")
        
        # Get tasks for this execution
        tasks = self.get_maintenance_window_execution_tasks(execution_id)
        
        print(f"Found {len(tasks)} tasks in execution")
        
        for task in tasks:
            task_id = task.get('TaskExecutionId')
            task_type = task.get('TaskType')
            task_arn = task.get('TaskArn', '')
            
            self.debug_print(f"Processing task {task_id}, type: {task_type}, ARN: {task_arn}")
            
            if task_type == 'RUN_COMMAND':
                # Get the task invocations
                try:
                    invocations_response = self.ssm_client.describe_maintenance_window_execution_task_invocations(
                        WindowExecutionId=execution_id,
                        TaskId=task_id
                    )
                    
                    invocations = invocations_response.get('WindowExecutionTaskInvocationIdentities', [])
                    print(f"Processing {len(invocations)} invocations for task {task_id}")
                    
                    for invocation in invocations:
                        command_id = invocation.get('ExecutionId')
                        instance_id = invocation.get('InstanceId')
                        
                        if command_id and instance_id:
                            # Get command output
                            details = self.get_command_invocation_details(command_id, instance_id)
                            
                            if details:
                                status = details.get('Status')
                                self.debug_print(f"Command {command_id} status: {status}")
                                
                                if status == 'Success':
                                    output = details.get('StandardOutputContent', '')
                                    command_name = details.get('DocumentName', '')
                                    
                                    if output:
                                        # Save raw output for debugging
                                        if self.debug:
                                            self.save_raw_output(output, instance_id, command_id)
                                        
                                        # Extract packages from output
                                        packages = self.extract_packages_from_output(output, command_name)
                                        
                                        print(f"Found {len(packages)} packages for instance {instance_id}")
                                        
                                        # Add metadata to each package
                                        for pkg in packages:
                                            pkg.update({
                                                'instance_id': instance_id,
                                                'window_id': window_id,
                                                'execution_id': execution_id,
                                                'task_id': task_id,
                                                'command_id': command_id,
                                                'command_name': command_name,
                                                'execution_time': invocation.get('StartTime', '').isoformat() if invocation.get('StartTime') else ''
                                            })
                                        
                                        all_packages.extend(packages)
                                    else:
                                        self.debug_print(f"No output for command {command_id}")
                                        
                                    # Also check StandardErrorContent
                                    error_output = details.get('StandardErrorContent', '')
                                    if error_output:
                                        self.debug_print(f"Error output: {error_output[:200]}...")
                
                except Exception as e:
                    print(f"Error processing task {task_id}: {e}")
                    import traceback
                    self.debug_print(traceback.format_exc())
        
        return all_packages
    
    def export_to_csv(self, packages: List[Dict], filename: str = 'maintenance_window_packages.csv'):
        """Export packages to CSV file"""
        if not packages:
            print("No packages to export")
            # Create empty CSV with headers
            fieldnames = ['instance_id', 'package_name', 'version', 'window_id', 
                          'execution_id', 'task_id', 'command_id', 'command_name', 
                          'execution_time', 'full_line']
            
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
            
            print(f"Created empty CSV file with headers: {filename}")
            return
        
        # Define CSV columns
        fieldnames = ['instance_id', 'package_name', 'version', 'window_id', 
                      'execution_id', 'task_id', 'command_id', 'command_name',
                      'execution_time', 'full_line']
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for pkg in packages:
                writer.writerow({
                    'instance_id': pkg.get('instance_id', ''),
                    'package_name': pkg.get('name', ''),
                    'version': pkg.get('version', ''),
                    'window_id': pkg.get('window_id', ''),
                    'execution_id': pkg.get('execution_id', ''),
                    'task_id': pkg.get('task_id', ''),
                    'command_id': pkg.get('command_id', ''),
                    'command_name': pkg.get('command_name', ''),
                    'execution_time': pkg.get('execution_time', ''),
                    'full_line': pkg.get('full_line', '')
                })
        
        print(f"Exported {len(packages)} packages to {filename}")
    
    def get_all_packages_from_all_windows(self) -> List[Dict]:
        """Get packages from all maintenance windows"""
        all_packages = []
        windows = self.get_maintenance_windows()
        
        print(f"Found {len(windows)} maintenance windows")
        
        for window in windows:
            window_id = window['WindowId']
            window_name = window.get('Name', 'Unnamed')
            print(f"\nProcessing window: {window_name} ({window_id})")
            
            try:
                packages = self.get_packages_from_maintenance_window(window_id)
                all_packages.extend(packages)
            except Exception as e:
                print(f"Error processing window {window_id}: {e}")
                if self.debug:
                    import traceback
                    self.debug_print(traceback.format_exc())
        
        return all_packages
    
    def get_latest_packages_as_csv(self, window_id: str = None):
        """Get packages from the latest maintenance window execution and save as CSV"""
        if window_id:
            # Get packages from specific window
            packages = self.get_packages_from_maintenance_window(window_id)
            filename = f'packages_window_{window_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        else:
            # Get packages from all windows
            packages = self.get_all_packages_from_all_windows()
            filename = f'all_maintenance_window_packages_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        
        filepath = os.path.join(pwd, filename)
        self.export_to_csv(packages, filepath)
        return filepath

# Example usage
if __name__ == "__main__":
    # Initialize the extractor with debug mode
    extractor = MaintenanceWindowPackageExtractor(region_name='us-east-1', debug=True)
    
    # Get packages from all maintenance windows
    print("Extracting packages from all maintenance windows...")
    csv_file = extractor.get_latest_packages_as_csv()
    print(f"\nCSV file created: {csv_file}")
    
    # Check if raw output files were created
    import os
    raw_files = [f for f in os.listdir('.') if f.startswith('raw_output_')]
    if raw_files:
        print(f"\nRaw output files created for debugging: {raw_files}")
        print("Check these files to see the actual command output format")