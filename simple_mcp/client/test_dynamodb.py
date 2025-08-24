#!/usr/bin/env python3
"""
Test script for DynamoDB client functionality

This script demonstrates the basic operations available in the DynamoDB client.
Run this script to test the DynamoDB integration.
"""

import json
import uuid
from datetime import datetime
from dynamodb_client import DynamoDBClient

def print_section(title):
    """Print a section header"""
    print(f"\n{'='*50}")
    print(f" {title}")
    print(f"{'='*50}")

def print_result(operation, result):
    """Print operation result"""
    print(f"\n{operation}:")
    if result.get('success', False):
        print("✅ Success")
        if 'data' in result:
            print(f"Data: {json.dumps(result['data'], indent=2, default=str)}")
        elif 'messages' in result:
            print(f"Messages: {len(result['messages'])} found")
        elif 'instances' in result:
            print(f"Instances: {len(result['instances'])} found")
        else:
            print(f"Result: {json.dumps(result, indent=2, default=str)}")
    else:
        print("❌ Failed")
        print(f"Error: {result.get('error', 'Unknown error')}")

def test_dynamodb_client():
    """Test the DynamoDB client functionality"""
    
    # Initialize client
    print_section("Initializing DynamoDB Client")
    client = DynamoDBClient(region_name='us-east-1')
    print("✅ DynamoDB client initialized")
    
    # Generate a unique instance ID for testing
    test_instance_id = f"test-instance-{uuid.uuid4().hex[:8]}"
    print(f"Test instance ID: {test_instance_id}")
    
    # Test 1: Create instance
    print_section("Test 1: Create Instance")
    create_result = client.create_instance(
        instance_id=test_instance_id,
        system_prompt="You are a helpful test assistant for demonstrating DynamoDB functionality."
    )
    print_result("Create Instance", create_result)
    
    # Test 2: Get instance
    print_section("Test 2: Get Instance")
    get_result = client.get_instance(test_instance_id)
    if get_result:
        print_result("Get Instance", {'success': True, 'data': get_result})
    else:
        print_result("Get Instance", {'success': False, 'error': 'Instance not found'})
    
    # Test 3: Add user message
    print_section("Test 3: Add User Message")
    user_msg_result = client.add_message(
        instance_id=test_instance_id,
        role='user',
        content="Hello! This is a test message to demonstrate the DynamoDB client."
    )
    print_result("Add User Message", user_msg_result)
    
    # Test 4: Add assistant message
    print_section("Test 4: Add Assistant Message")
    assistant_msg_result = client.add_message(
        instance_id=test_instance_id,
        role='assistant',
        content="Hello! I'm the test assistant. I can help you with various tasks and demonstrate the DynamoDB integration.",
        model_id='us.anthropic.claude-opus-4-20250514-v1:0'
    )
    print_result("Add Assistant Message", assistant_msg_result)
    
    # Test 5: Get conversation history
    print_section("Test 5: Get Conversation History")
    history = client.get_conversation_history(test_instance_id)
    print_result("Get Conversation History", {
        'success': True,
        'messages': history,
        'count': len(history)
    })
    
    # Test 6: Get instance statistics
    print_section("Test 6: Get Instance Statistics")
    stats_result = client.get_instance_stats(test_instance_id)
    print_result("Get Instance Statistics", stats_result)
    
    # Test 7: List instances
    print_section("Test 7: List Instances")
    list_result = client.list_instances(status='active')
    print_result("List Instances", list_result)
    
    # Test 8: Update instance status
    print_section("Test 8: Update Instance Status")
    update_result = client.update_instance_status(test_instance_id, 'inactive')
    print_result("Update Instance Status", update_result)
    
    # Test 9: List instances with inactive status
    print_section("Test 9: List Inactive Instances")
    inactive_list_result = client.list_instances(status='inactive')
    print_result("List Inactive Instances", inactive_list_result)
    
    # Test 10: Reactivate instance
    print_section("Test 10: Reactivate Instance")
    reactivate_result = client.update_instance_status(test_instance_id, 'active')
    print_result("Reactivate Instance", reactivate_result)
    
    # Test 11: Add more messages to test conversation
    print_section("Test 11: Add More Messages")
    messages = [
        ("user", "Can you help me understand how DynamoDB works?"),
        ("assistant", "Of course! DynamoDB is a fully managed NoSQL database service provided by AWS. It offers seamless scalability and high performance for applications that need consistent, single-digit millisecond latency at any scale."),
        ("user", "What are the key features of DynamoDB?"),
        ("assistant", "DynamoDB's key features include: 1) Fully managed service with automatic scaling, 2) Built-in security with encryption at rest and in transit, 3) Global tables for multi-region replication, 4) Point-in-time recovery, 5) On-demand and provisioned capacity modes, and 6) Integration with other AWS services.")
    ]
    
    for role, content in messages:
        result = client.add_message(
            instance_id=test_instance_id,
            role=role,
            content=content,
            model_id='us.anthropic.claude-opus-4-20250514-v1:0' if role == 'assistant' else None
        )
        print_result(f"Add {role.title()} Message", result)
    
    # Test 12: Get final conversation history
    print_section("Test 12: Final Conversation History")
    final_history = client.get_conversation_history(test_instance_id)
    print(f"Total messages: {len(final_history)}")
    for i, msg in enumerate(final_history, 1):
        print(f"{i}. [{msg['role'].upper()}] {msg['content'][:100]}...")
    
    # Test 13: Get final statistics
    print_section("Test 13: Final Statistics")
    final_stats = client.get_instance_stats(test_instance_id)
    print_result("Final Statistics", final_stats)
    
    # Test 14: Cleanup - Delete instance
    print_section("Test 14: Cleanup - Delete Instance")
    delete_result = client.delete_instance(test_instance_id)
    print_result("Delete Instance", delete_result)
    
    # Test 15: Verify deletion
    print_section("Test 15: Verify Deletion")
    verify_result = client.get_instance(test_instance_id)
    if verify_result is None:
        print_result("Verify Deletion", {'success': True, 'message': 'Instance successfully deleted'})
    else:
        print_result("Verify Deletion", {'success': False, 'error': 'Instance still exists'})

def main():
    """Main function"""
    print("🚀 Starting DynamoDB Client Test Suite")
    print(f"Timestamp: {datetime.now().isoformat()}")
    
    try:
        test_dynamodb_client()
        print_section("Test Suite Completed")
        print("✅ All tests completed successfully!")
        
    except Exception as e:
        print_section("Test Suite Failed")
        print(f"❌ Error during testing: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n📝 Note: This test script creates and deletes test data.")
    print("   Make sure you have proper AWS credentials configured.")
    print("   The test instance will be automatically cleaned up.")

if __name__ == "__main__":
    main() 