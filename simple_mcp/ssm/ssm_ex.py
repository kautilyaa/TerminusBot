# Example usage script
import os
from ssm_class import SSMManager, format_command_output
# Load environment variables
# load_dotenv()

def main():
    # Initialize SSM Manager
    ssm = SSMManager(region_name='us-east-1')

    # Example 1: Get managed instances
    print("=== Managed Instances ===")
    instances = ssm.get_managed_instances()
    for instance in instances:
        print(f"Instance ID: {instance['InstanceId']}, "
              f"Platform: {instance.get('PlatformName', 'Unknown')}, "
              f"Status: {instance.get('PingStatus', 'Unknown')}")

    if not instances:
        print("No managed instances found!")
        return

    # Use the first available instance for examples
    instance_id = instances[0]['InstanceId']
    print(f"\\nUsing instance: {instance_id}")

    # Example 2: Run a simple command
    print("\\n=== Running Simple Command ===")
    results = ssm.run_command_and_get_output(
        instance_ids=instance_id,
        commands="echo 'Hello from SSM!'"
    )

    for result in results:
        print(format_command_output(result))

    # Example 3: Run multiple commands
    print("\\n=== Running Multiple Commands ===")
    commands = [
        "whoami",
        "pwd",
        "ls -la /tmp",
        "df -h"
    ]

    results = ssm.run_command_and_get_output(
        instance_ids=instance_id,
        commands=commands
    )

    for result in results:
        print(format_command_output(result))

    # Example 4: Run command on multiple instances (if available)
    if len(instances) > 1:
        print("\\n=== Running Command on Multiple Instances ===")
        instance_ids = [inst['InstanceId'] for inst in instances[:2]]

        results = ssm.run_command_and_get_output(
            instance_ids=instance_ids,
            commands="hostname && uptime"
        )

        for result in results:
            print(format_command_output(result))

    # Example 5: Advanced command with error handling
    print("\\n=== Command with Error Handling ===")
    results = ssm.run_command_and_get_output(
        instance_ids=instance_id,
        commands=[
            "echo 'Starting process...'",
            "ls /nonexistent_directory || echo 'Directory not found'",
            "echo 'Process completed'"
        ]
    )

    for result in results:
        print(format_command_output(result))
        if result['status'] != 'Success':
            print(f"Command failed with status: {result['status']}")

if __name__ == "__main__":
    main()
