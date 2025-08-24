import boto3
import time
import json
from typing import List, Dict, Optional, Union
from botocore.exceptions import ClientError, BotoCoreError
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SSMManager:
    """
    AWS Systems Manager (SSM) client for running commands on EC2 instances
    """

    def __init__(self, region_name: str = 'us-east-1', profile_name: Optional[str] = None):
        """
        Initialize SSM Manager

        Args:
            region_name (str): AWS region name
            profile_name (str, optional): AWS profile name
        """
        try:
            session = boto3.Session(profile_name=profile_name) if profile_name else boto3.Session()
            self.ssm_client = session.client('ssm', region_name=region_name)
            self.region = region_name
            logger.info(f"SSM Manager initialized for region: {region_name}")
        except Exception as e:
            logger.error(f"Failed to initialize SSM Manager: {str(e)}")
            raise

    def get_managed_instances(self, filters: Optional[List[Dict]] = None) -> List[Dict]:
        """
        Get list of SSM managed instances

        Args:
            filters (List[Dict], optional): Filters to apply

        Returns:
            List[Dict]: List of managed instances
        """
        try:
            params = {}
            if filters:
                params['Filters'] = filters

            response = self.ssm_client.describe_instance_information(**params)
            return response.get('InstanceInformationList', [])
        except ClientError as e:
            logger.error(f"Error getting managed instances: {e}")
            return []

    def run_command(self,
                   instance_ids: Union[str, List[str]],
                   commands: Union[str, List[str]],
                   document_name: str = "AWS-RunShellScript",
                   timeout_seconds: int = 300,
                   working_directory: Optional[str] = None,
                   execution_timeout: Optional[str] = None) -> Optional[str]:
        """
        Run command(s) on specified instance(s)

        Args:
            instance_ids: Single instance ID or list of instance IDs
            commands: Single command or list of commands to run
            document_name: SSM document name (default: AWS-RunShellScript)
            timeout_seconds: Timeout for command execution
            working_directory: Working directory for command execution
            execution_timeout: Execution timeout (SSM parameter)

        Returns:
            str: Command ID if successful, None otherwise
        """
        try:
            # Ensure instance_ids and commands are lists
            if isinstance(instance_ids, str):
                instance_ids = [instance_ids]
            if isinstance(commands, str):
                commands = [commands]

            # Prepare parameters
            parameters = {'commands': commands}
            if working_directory:
                parameters['workingDirectory'] = [working_directory]
            if execution_timeout:
                parameters['executionTimeout'] = [execution_timeout]

            # Send command
            response = self.ssm_client.send_command(
                InstanceIds=instance_ids,
                DocumentName=document_name,
                Parameters=parameters,
                TimeoutSeconds=timeout_seconds
            )

            command_id = response['Command']['CommandId']
            logger.info(f"Command sent successfully. Command ID: {command_id}")
            return command_id

        except ClientError as e:
            logger.error(f"Error sending command: {e}")
            return None

    def get_command_output(self,
                          command_id: str,
                          instance_id: str,
                          wait_for_completion: bool = True,
                          max_wait_time: int = 300) -> Dict:
        """
        Get output of a command execution

        Args:
            command_id: Command ID returned by run_command
            instance_id: Instance ID where command was executed
            wait_for_completion: Whether to wait for command completion
            max_wait_time: Maximum time to wait for completion (seconds)

        Returns:
            Dict: Command output and metadata
        """
        try:
            if wait_for_completion:
                self._wait_for_command_completion(command_id, instance_id, max_wait_time)

            response = self.ssm_client.get_command_invocation(
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
                'execution_start_time': response.get('ExecutionStartDateTime'),
                'execution_end_time': response.get('ExecutionEndDateTime')
            }

        except ClientError as e:
            logger.error(f"Error getting command output: {e}")
            return {
                'error': str(e),
                'command_id': command_id,
                'instance_id': instance_id
            }

    def _wait_for_command_completion(self, command_id: str, instance_id: str, max_wait_time: int):
        """
        Wait for command completion

        Args:
            command_id: Command ID
            instance_id: Instance ID
            max_wait_time: Maximum wait time in seconds
        """
        start_time = time.time()

        while time.time() - start_time < max_wait_time:
            try:
                response = self.ssm_client.get_command_invocation(
                    CommandId=command_id,
                    InstanceId=instance_id
                )

                status = response.get('Status')
                if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                    logger.info(f"Command completed with status: {status}")
                    return

                logger.info(f"Command status: {status}. Waiting...")
                time.sleep(5)

            except ClientError as e:
                if 'InvocationDoesNotExist' in str(e):
                    logger.info("Command still initializing...")
                    time.sleep(5)
                    continue
                else:
                    raise e

        logger.warning(f"Command did not complete within {max_wait_time} seconds")

    def run_command_and_get_output(self,
                                  instance_ids: Union[str, List[str]],
                                  commands: Union[str, List[str]],
                                  **kwargs) -> List[Dict]:
        """
        Run command and wait for output (convenience method)

        Args:
            instance_ids: Single instance ID or list of instance IDs
            commands: Single command or list of commands
            **kwargs: Additional arguments for run_command

        Returns:
            List[Dict]: List of command outputs for each instance
        """
        if isinstance(instance_ids, str):
            instance_ids = [instance_ids]

        command_id = self.run_command(instance_ids, commands, **kwargs)
        if not command_id:
            return []

        results = []
        for instance_id in instance_ids:
            output = self.get_command_output(command_id, instance_id)
            results.append(output)

        return results

    def list_commands(self,
                     instance_id: Optional[str] = None,
                     max_results: int = 25) -> List[Dict]:
        """
        List recent commands

        Args:
            instance_id: Filter by instance ID
            max_results: Maximum number of results

        Returns:
            List[Dict]: List of commands
        """
        try:
            params = {'MaxResults': max_results}
            if instance_id:
                params['InstanceId'] = instance_id

            response = self.ssm_client.list_commands(**params)
            return response.get('Commands', [])

        except ClientError as e:
            logger.error(f"Error listing commands: {e}")
            return []

# Utility functions
def format_command_output(output: Dict) -> str:
    """Format command output for display"""
    if 'error' in output:
        return f"Error: {output['error']}"

    result = f"""
    Command ID: {output['command_id']}
    Instance ID: {output['instance_id']}
    Status: {output['status']}
    Response Code: {output['response_code']}

    Standard Output:
    {output['standard_output']}

    Standard Error:
    {output['standard_error']}
        """
    return result.strip()
