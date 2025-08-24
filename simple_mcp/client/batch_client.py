#!/usr/bin/env python3
"""
Batch Client for DynamoDB Operations

This module provides batch processing capabilities for DynamoDB operations,
allowing efficient processing of multiple operations in a single batch.
"""

import asyncio
import time
from typing import List, Dict, Any, Optional
from dynamodb_client import DynamoDBClient

class BatchClient:
    """Batch client for processing multiple DynamoDB operations"""
    
    def __init__(self, region_name: str = 'us-east-1', max_batch_size: int = 25):
        """
        Initialize batch client
        
        Args:
            region_name: AWS region name
            max_batch_size: Maximum number of operations per batch (DynamoDB limit is 25)
        """
        self.db_client = DynamoDBClient(region_name=region_name)
        self.max_batch_size = max_batch_size
    
    def process_operations(self, operations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process a list of operations in batches
        
        Args:
            operations: List of operation dictionaries
            
        Returns:
            List of results for each operation
        """
        results = []
        
        # Process operations in batches
        for i in range(0, len(operations), self.max_batch_size):
            batch = operations[i:i + self.max_batch_size]
            batch_results = self._process_batch(batch)
            results.extend(batch_results)
        
        return results
    
    def _process_batch(self, batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process a single batch of operations
        
        Args:
            batch: List of operations in the batch
            
        Returns:
            List of results for the batch
        """
        results = []
        
        for operation in batch:
            try:
                result = self._execute_operation(operation)
                results.append({
                    'operation': operation,
                    'success': True,
                    'result': result
                })
            except Exception as e:
                results.append({
                    'operation': operation,
                    'success': False,
                    'error': str(e)
                })
        
        return results
    
    def _execute_operation(self, operation: Dict[str, Any]) -> Any:
        """
        Execute a single operation
        
        Args:
            operation: Operation dictionary
            
        Returns:
            Operation result
        """
        op_type = operation.get('type')
        
        if op_type == 'create_instance':
            return self.db_client.create_instance(
                operation['instance_id'],
                operation.get('system_prompt')
            )
        
        elif op_type == 'get_instance':
            return self.db_client.get_instance(operation['instance_id'])
        
        elif op_type == 'add_message':
            return self.db_client.add_message(
                operation['instance_id'],
                operation['role'],
                operation['content'],
                operation.get('model_id')
            )
        
        elif op_type == 'get_conversation_history':
            return self.db_client.get_conversation_history(operation['instance_id'])
        
        elif op_type == 'get_instance_stats':
            return self.db_client.get_instance_stats(operation['instance_id'])
        
        elif op_type == 'update_instance_status':
            return self.db_client.update_instance_status(
                operation['instance_id'],
                operation['status']
            )
        
        elif op_type == 'delete_instance':
            return self.db_client.delete_instance(operation['instance_id'])
        
        elif op_type == 'list_instances':
            return self.db_client.list_instances(operation.get('status', 'active'))
        
        else:
            raise ValueError(f"Unknown operation type: {op_type}")

class AsyncBatchClient:
    """Asynchronous batch client for processing operations with concurrency"""
    
    def __init__(self, region_name: str = 'us-east-1', max_concurrent: int = 10):
        """
        Initialize async batch client
        
        Args:
            region_name: AWS region name
            max_concurrent: Maximum number of concurrent operations
        """
        self.db_client = DynamoDBClient(region_name=region_name)
        self.max_concurrent = max_concurrent
    
    async def process_operations_async(self, operations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process operations asynchronously with concurrency control
        
        Args:
            operations: List of operation dictionaries
            
        Returns:
            List of results for each operation
        """
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def process_operation(operation):
            async with semaphore:
                return await self._execute_operation_async(operation)
        
        tasks = [process_operation(op) for op in operations]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Convert exceptions to error results
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    'operation': operations[i],
                    'success': False,
                    'error': str(result)
                })
            else:
                processed_results.append({
                    'operation': operations[i],
                    'success': True,
                    'result': result
                })
        
        return processed_results
    
    async def _execute_operation_async(self, operation: Dict[str, Any]) -> Any:
        """
        Execute a single operation asynchronously
        
        Args:
            operation: Operation dictionary
            
        Returns:
            Operation result
        """
        # For now, we'll run the synchronous operation in a thread pool
        # In a real implementation, you might want to use async AWS SDK
        loop = asyncio.get_event_loop()
        
        return await loop.run_in_executor(
            None, 
            self._execute_operation_sync, 
            operation
        )
    
    def _execute_operation_sync(self, operation: Dict[str, Any]) -> Any:
        """
        Execute a single operation synchronously (same as BatchClient)
        
        Args:
            operation: Operation dictionary
            
        Returns:
            Operation result
        """
        op_type = operation.get('type')
        
        if op_type == 'create_instance':
            return self.db_client.create_instance(
                operation['instance_id'],
                operation.get('system_prompt')
            )
        
        elif op_type == 'get_instance':
            return self.db_client.get_instance(operation['instance_id'])
        
        elif op_type == 'add_message':
            return self.db_client.add_message(
                operation['instance_id'],
                operation['role'],
                operation['content'],
                operation.get('model_id')
            )
        
        elif op_type == 'get_conversation_history':
            return self.db_client.get_conversation_history(operation['instance_id'])
        
        elif op_type == 'get_instance_stats':
            return self.db_client.get_instance_stats(operation['instance_id'])
        
        elif op_type == 'update_instance_status':
            return self.db_client.update_instance_status(
                operation['instance_id'],
                operation['status']
            )
        
        elif op_type == 'delete_instance':
            return self.db_client.delete_instance(operation['instance_id'])
        
        elif op_type == 'list_instances':
            return self.db_client.list_instances(operation.get('status', 'active'))
        
        else:
            raise ValueError(f"Unknown operation type: {op_type}")

def create_sample_operations() -> List[Dict[str, Any]]:
    """Create sample operations for testing"""
    import uuid
    
    base_id = str(uuid.uuid4())[:8]
    
    return [
        {
            'type': 'create_instance',
            'instance_id': f'batch-{base_id}-1',
            'system_prompt': 'You are Assistant 1'
        },
        {
            'type': 'create_instance',
            'instance_id': f'batch-{base_id}-2',
            'system_prompt': 'You are Assistant 2'
        },
        {
            'type': 'add_message',
            'instance_id': f'batch-{base_id}-1',
            'role': 'user',
            'content': 'Hello from batch 1'
        },
        {
            'type': 'add_message',
            'instance_id': f'batch-{base_id}-2',
            'role': 'user',
            'content': 'Hello from batch 2'
        },
        {
            'type': 'add_message',
            'instance_id': f'batch-{base_id}-1',
            'role': 'assistant',
            'content': 'Hi there! I am Assistant 1.',
            'model_id': 'claude-opus'
        },
        {
            'type': 'add_message',
            'instance_id': f'batch-{base_id}-2',
            'role': 'assistant',
            'content': 'Hello! I am Assistant 2.',
            'model_id': 'claude-opus'
        }
    ]

def main():
    """Main function for testing batch operations"""
    print("🧪 Testing Batch Client")
    print("=" * 30)
    
    # Create sample operations
    operations = create_sample_operations()
    
    print(f"Created {len(operations)} sample operations")
    
    # Test synchronous batch processing
    print("\n📦 Testing Synchronous Batch Processing")
    batch_client = BatchClient()
    
    start_time = time.time()
    results = batch_client.process_operations(operations)
    end_time = time.time()
    
    print(f"Processed {len(results)} operations in {end_time - start_time:.2f} seconds")
    
    # Display results
    successful = sum(1 for r in results if r['success'])
    failed = len(results) - successful
    
    print(f"✅ Successful: {successful}")
    print(f"❌ Failed: {failed}")
    
    # Test asynchronous batch processing
    async def test_async():
        print("\n⚡ Testing Asynchronous Batch Processing")
        async_batch_client = AsyncBatchClient()
        
        start_time = time.time()
        results = await async_batch_client.process_operations_async(operations)
        end_time = time.time()
        
        print(f"Processed {len(results)} operations in {end_time - start_time:.2f} seconds")
        
        successful = sum(1 for r in results if r['success'])
        failed = len(results) - successful
        
        print(f"✅ Successful: {successful}")
        print(f"❌ Failed: {failed}")
    
    # Run async test
    asyncio.run(test_async())
    
    # Cleanup test instances
    print("\n🧹 Cleaning up test instances...")
    cleanup_operations = []
    for op in operations:
        if op['type'] == 'create_instance':
            cleanup_operations.append({
                'type': 'delete_instance',
                'instance_id': op['instance_id']
            })
    
    if cleanup_operations:
        cleanup_results = batch_client.process_operations(cleanup_operations)
        cleaned = sum(1 for r in cleanup_results if r['success'])
        print(f"Cleaned up {cleaned} test instances")

if __name__ == "__main__":
    main()
