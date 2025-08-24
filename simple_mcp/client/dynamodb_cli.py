#!/usr/bin/env python3
"""
DynamoDB CLI Tool for Terminal MCP Chat Management

This tool provides a command-line interface to manage chat instances and messages
stored in DynamoDB tables.
"""

import argparse
import json
import sys
from typing import Optional
from dynamodb_client import DynamoDBClient

def print_json(data: dict, pretty: bool = True):
    """Print data as JSON"""
    if pretty:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(json.dumps(data, default=str))

def create_instance(args):
    """Create a new chat instance"""
    client = DynamoDBClient(region_name=args.region)
    result = client.create_instance(args.instance_id, args.system_prompt)
    print_json(result, args.pretty)

def get_instance(args):
    """Get instance details"""
    client = DynamoDBClient(region_name=args.region)
    instance = client.get_instance(args.instance_id)
    if instance:
        print_json({'success': True, 'data': instance}, args.pretty)
    else:
        print_json({'success': False, 'error': 'Instance not found'}, args.pretty)

def list_instances(args):
    """List all instances"""
    client = DynamoDBClient(region_name=args.region)
    result = client.list_instances(args.status)
    print_json(result, args.pretty)

def add_message(args):
    """Add a message to an instance"""
    client = DynamoDBClient(region_name=args.region)
    result = client.add_message(args.instance_id, args.role, args.content, args.model_id)
    print_json(result, args.pretty)

def get_history(args):
    """Get conversation history"""
    client = DynamoDBClient(region_name=args.region)
    messages = client.get_conversation_history(args.instance_id)
    print_json({'success': True, 'messages': messages}, args.pretty)

def delete_instance(args):
    """Delete an instance and all its messages"""
    client = DynamoDBClient(region_name=args.region)
    result = client.delete_instance(args.instance_id)
    print_json(result, args.pretty)

def update_status(args):
    """Update instance status"""
    client = DynamoDBClient(region_name=args.region)
    result = client.update_instance_status(args.instance_id, args.status)
    print_json(result, args.pretty)

def get_stats(args):
    """Get instance statistics"""
    client = DynamoDBClient(region_name=args.region)
    result = client.get_instance_stats(args.instance_id)
    print_json(result, args.pretty)

def main():
    parser = argparse.ArgumentParser(
        description='DynamoDB CLI Tool for Terminal MCP Chat Management',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create a new instance
  python dynamodb_cli.py create-instance my-instance-123 --system-prompt "You are a helpful assistant"

  # List all active instances
  python dynamodb_cli.py list-instances

  # Add a user message
  python dynamodb_cli.py add-message my-instance-123 user "Hello, how are you?"

  # Get conversation history
  python dynamodb_cli.py get-history my-instance-123

  # Get instance statistics
  python dynamodb_cli.py get-stats my-instance-123
        """
    )
    
    parser.add_argument('--region', default='us-east-1', help='AWS region (default: us-east-1)')
    parser.add_argument('--pretty', action='store_true', help='Pretty print JSON output')
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Create instance command
    create_parser = subparsers.add_parser('create-instance', help='Create a new chat instance')
    create_parser.add_argument('instance_id', help='Unique instance ID')
    create_parser.add_argument('--system-prompt', help='System prompt for the conversation')
    create_parser.set_defaults(func=create_instance)
    
    # Get instance command
    get_parser = subparsers.add_parser('get-instance', help='Get instance details')
    get_parser.add_argument('instance_id', help='Instance ID')
    get_parser.set_defaults(func=get_instance)
    
    # List instances command
    list_parser = subparsers.add_parser('list-instances', help='List all instances')
    list_parser.add_argument('--status', default='active', choices=['active', 'inactive', 'archived'], 
                           help='Filter by status (default: active)')
    list_parser.set_defaults(func=list_instances)
    
    # Add message command
    add_msg_parser = subparsers.add_parser('add-message', help='Add a message to an instance')
    add_msg_parser.add_argument('instance_id', help='Instance ID')
    add_msg_parser.add_argument('role', choices=['user', 'assistant'], help='Message role')
    add_msg_parser.add_argument('content', help='Message content')
    add_msg_parser.add_argument('--model-id', help='Model ID (for assistant messages)')
    add_msg_parser.set_defaults(func=add_message)
    
    # Get history command
    history_parser = subparsers.add_parser('get-history', help='Get conversation history')
    history_parser.add_argument('instance_id', help='Instance ID')
    history_parser.set_defaults(func=get_history)
    
    # Delete instance command
    delete_parser = subparsers.add_parser('delete-instance', help='Delete an instance and all its messages')
    delete_parser.add_argument('instance_id', help='Instance ID')
    delete_parser.set_defaults(func=delete_instance)
    
    # Update status command
    status_parser = subparsers.add_parser('update-status', help='Update instance status')
    status_parser.add_argument('instance_id', help='Instance ID')
    status_parser.add_argument('status', choices=['active', 'inactive', 'archived'], help='New status')
    status_parser.set_defaults(func=update_status)
    
    # Get stats command
    stats_parser = subparsers.add_parser('get-stats', help='Get instance statistics')
    stats_parser.add_argument('instance_id', help='Instance ID')
    stats_parser.set_defaults(func=get_stats)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print_json({'success': False, 'error': str(e)}, args.pretty)
        sys.exit(1)

if __name__ == '__main__':
    main() 