import requests
import json

def call_terminal_assistant(query, server_url):
    # Lambda function endpoint (API Gateway URL)
    # lambda_url = "https://siyopweqfjqc6hc3dhwqpemlsu0dsqlv.lambda-url.us-east-1.on.aws/"
    lambda_url = "https://xqmd1x0yrg.execute-api.us-east-1.amazonaws.com/deployed"
    # Request payload
    payload = {
        "body":{
        "query": query,
        "server_url": server_url
    }}

    # Headers
    headers = {
        "Content-Type": "application/json"
    }

    # Make the POST request
    try:
        response = requests.post(
            lambda_url,
            headers=headers,
            data=json.dumps(payload)
        )

        # Check if request was successful
        if response.status_code == 200:
            result = response.json()
            print("Query processed successfully!")
            print(f"Response: {result['result']['response']}")

            # Print tool calls if any
            if result['result']['tool_calls']:
                print("\\nTool calls:")
                for i, tool_call in enumerate(result['result']['tool_calls']):
                    print(f"\\nTool Call {i+1}:")
                    print(f"Tool: {tool_call['tool']}")
                    print(f"Inputs: {tool_call['inputs']}")
                    print(f"Result: {tool_call['result'][:200]}..." if len(tool_call['result']) > 200 else tool_call['result'])

            return result
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
            return None

    except Exception as e:
        print(f"Exception occurred: {str(e)}")
        return None

# Example usage
if __name__ == "__main__":
    result = call_terminal_assistant(
        query="Show me the current directory contents and system information",
        server_url="http://13.222.180.210:8000/sse/"
    )

    # Save full result to file for detailed inspection
    if result:
        with open("terminal_assistant_result.json", "w") as f:
            json.dump(result, f, indent=2)
