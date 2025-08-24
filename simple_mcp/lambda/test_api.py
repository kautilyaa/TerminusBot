import requests
import json

# Configuration
# API_ENDPOINT = "https://your-api-id.execute-api.us-east-1.amazonaws.com/prod/execute"
API_ENDPOINT = "https://xqmd1x0yrg.execute-api.us-east-1.amazonaws.com/deployed"
API_KEY = "your-api-key"
MCP_SERVER_URL = "http://your-mcp-server:8080/sse"

# Example queries
queries = [
    "List all files in the current directory",
    "Show system information",
    "Create a file called test.txt with content 'Hello from Lambda'",
    "Read the contents of test.txt"
]

for query in queries:
    print(f"\nQuery: {query}")
    print("-" * 50)
    
    response = requests.post(
        API_ENDPOINT,
        headers={
            # "x-api-key": API_KEY,
            "Content-Type": "application/json"
        },
        json={
            "query": query,
            "server_url": MCP_SERVER_URL
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        print(result)
    #     print(f"Success: {result['success']}")
    #     print(f"Response: {result['result']['response']}")
        
    #     if result['result'].get('tool_calls'):
    #         print("\nTool Calls:")
    #         for call in result['result']['tool_calls']:
    #             print(f"  - {call['tool']}: {call['inputs']}")
    # else:
    #     print(f"Error: {response.status_code}")
    #     print(response.text)