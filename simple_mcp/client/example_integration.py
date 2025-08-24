#!/usr/bin/env python3
"""
Example Integration: MCP Client + DynamoDB

This script demonstrates how to integrate the Terminal MCP client with DynamoDB
for persistent chat sessions. It shows how to:
1. Create a chat instance in DynamoDB
2. Connect to the MCP server
3. Process queries and store them in DynamoDB
4. Retrieve conversation history
5. Clean up resources
"""

import asyncio
import time
import json
from typing import Optional
from client import TerminalMCPClient
from dynamodb_client import DynamoDBClient

class IntegratedChatSession:
    """Integrated chat session with MCP and DynamoDB persistence"""
    
    def __init__(self, mcp_server_url: str, region: str = 'us-east-1'):
        self.mcp_server_url = mcp_server_url
        self.region = region
        self.mcp_client = TerminalMCPClient()
        self.db_client = DynamoDBClient(region_name=region)
        self.instance_id: Optional[str] = None
        
    async def initialize(self, system_prompt: str = None):
        """Initialize the chat session"""
        print("🚀 Initializing Integrated Chat Session")
        print("=" * 50)
        
        # Create unique instance ID
        self.instance_id = f"mcp-session-{int(time.time())}"
        print(f"Instance ID: {self.instance_id}")
        
        # Create DynamoDB instance
        default_prompt = "You are a helpful terminal assistant with access to file system and terminal commands."
        result = self.db_client.create_instance(
            self.instance_id, 
            system_prompt or default_prompt
        )
        
        if result.get('success'):
            print("✅ DynamoDB instance created successfully")
        else:
            print(f"❌ Failed to create DynamoDB instance: {result.get('error')}")
            return False
        
        # Connect to MCP server
        try:
            await self.mcp_client.connect_to_server(self.mcp_server_url)
            print("✅ Connected to MCP server")
            return True
        except Exception as e:
            print(f"❌ Failed to connect to MCP server: {str(e)}")
            return False
    
    async def process_query(self, query: str) -> str:
        """Process a query and store in DynamoDB"""
        if not self.instance_id:
            return "Error: Session not initialized"
        
        try:
            # Store user message
            user_result = self.db_client.add_message(
                self.instance_id, 'user', query
            )
            
            if not user_result.get('success'):
                print(f"Warning: Failed to store user message: {user_result.get('error')}")
            
            # Get AI response from MCP
            response = await self.mcp_client.process_query(query)
            
            # Store assistant response
            assistant_result = self.db_client.add_message(
                self.instance_id, 'assistant', response,
                model_id='us.anthropic.claude-opus-4-20250514-v1:0'
            )
            
            if not assistant_result.get('success'):
                print(f"Warning: Failed to store assistant message: {assistant_result.get('error')}")
            
            return response
            
        except Exception as e:
            error_msg = f"Error processing query: {str(e)}"
            print(f"❌ {error_msg}")
            return error_msg
    
    def get_conversation_history(self) -> list:
        """Get conversation history from DynamoDB"""
        if not self.instance_id:
            return []
        
        return self.db_client.get_conversation_history(self.instance_id)
    
    def get_session_stats(self) -> dict:
        """Get session statistics"""
        if not self.instance_id:
            return {}
        
        return self.db_client.get_instance_stats(self.instance_id)
    
    def display_conversation_history(self):
        """Display the conversation history"""
        messages = self.get_conversation_history()
        
        if not messages:
            print("No conversation history found.")
            return
        
        print(f"\n📚 Conversation History ({len(messages)} messages):")
        print("-" * 50)
        
        for i, msg in enumerate(messages, 1):
            role = msg['role'].upper()
            content = msg['content'][:100] + "..." if len(msg['content']) > 100 else msg['content']
            timestamp = msg['timestamp']
            
            print(f"{i:2d}. [{role}] {content}")
            print(f"    Timestamp: {timestamp}")
            print()
    
    def display_session_stats(self):
        """Display session statistics"""
        stats = self.get_session_stats()
        
        if not stats.get('success'):
            print("❌ Failed to get session statistics")
            return
        
        print(f"\n📊 Session Statistics:")
        print("-" * 30)
        print(f"Instance ID: {stats['instance_id']}")
        print(f"Total Messages: {stats['total_messages']}")
        print(f"User Messages: {stats['user_messages']}")
        print(f"Assistant Messages: {stats['assistant_messages']}")
        print(f"Estimated Tokens: {stats['estimated_tokens']}")
        print(f"Created: {stats['created_at']}")
        print(f"Last Updated: {stats['updated_at']}")
        print(f"Status: {stats['status']}")
    
    async def cleanup(self):
        """Clean up resources"""
        print("\n🧹 Cleaning up resources...")
        
        try:
            await self.mcp_client.cleanup()
            print("✅ MCP client cleaned up")
        except Exception as e:
            print(f"❌ Error cleaning up MCP client: {str(e)}")
    
    async def interactive_chat(self):
        """Run interactive chat loop"""
        print("\n💬 Starting Interactive Chat")
        print("Type 'quit' to exit, 'history' to see conversation, 'stats' for statistics")
        print("-" * 50)
        
        while True:
            try:
                query = input("\nQuery: ").strip()
                
                if query.lower() == 'quit':
                    break
                elif query.lower() == 'history':
                    self.display_conversation_history()
                    continue
                elif query.lower() == 'stats':
                    self.display_session_stats()
                    continue
                elif not query:
                    continue
                
                # Process the query
                response = await self.process_query(query)
                print(f"\nAssistant: {response}")
                
            except KeyboardInterrupt:
                print("\n\nInterrupted by user")
                break
            except Exception as e:
                print(f"\n❌ Error: {str(e)}")

async def main():
    """Main function"""
    print("🎯 MCP + DynamoDB Integration Example")
    print("=" * 50)
    
    # Configuration
    mcp_server_url = "http://localhost:8080/sse"
    region = "us-east-1"
    
    # Create integrated chat session
    session = IntegratedChatSession(mcp_server_url, region)
    
    try:
        # Initialize session
        if not await session.initialize():
            print("❌ Failed to initialize session")
            return
        
        # Run interactive chat
        await session.interactive_chat()
        
        # Display final statistics
        session.display_session_stats()
        
    except Exception as e:
        print(f"❌ Error in main: {str(e)}")
    
    finally:
        # Cleanup
        await session.cleanup()
        print("\n👋 Session ended")

def run_demo_queries():
    """Run a series of demo queries to test the integration"""
    async def demo():
        session = IntegratedChatSession("http://localhost:8080/sse")
        
        if not await session.initialize("You are a helpful assistant. Keep responses concise."):
            return
        
        # Demo queries
        demo_queries = [
            "What is the current directory?",
            "List the files in the current directory",
            "Create a test file called demo.txt",
            "Show me the contents of demo.txt",
            "Delete the demo.txt file"
        ]
        
        print("\n🧪 Running Demo Queries")
        print("=" * 30)
        
        for i, query in enumerate(demo_queries, 1):
            print(f"\n{i}. Query: {query}")
            response = await session.process_query(query)
            print(f"Response: {response}")
            await asyncio.sleep(1)  # Small delay between queries
        
        # Show results
        session.display_conversation_history()
        session.display_session_stats()
        
        await session.cleanup()
    
    return demo

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        # Run demo mode
        asyncio.run(run_demo_queries()())
    else:
        # Run interactive mode
        asyncio.run(main()) 