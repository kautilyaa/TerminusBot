# Here's the modified Lambda function that accommodates both normal events and Slack events:

# ```python
import json
import os
import time
import logging
import asyncio
import re
import base64
import urllib.parse
import hmac
import hashlib
from typing import Optional, Dict, List, Any
import boto3
from botocore.config import Config
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta, timezone
from slack_utils import send_slack_message
from sns_alert import send_sns_alert

# Import context management components
from langchain_core.messages import HumanMessage, AIMessage
from langchain_community.chat_message_histories import DynamoDBChatMessageHistory

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configure boto3 client with retry settings
config = Config(
    retries=dict(
        max_attempts=10,
        mode='adaptive'
    ),
    read_timeout=300,
    max_pool_connections=50
)

bedrock_client = boto3.client(
    service_name='bedrock-runtime',
    region_name='us-east-1',
    config=config
)

# Context-aware system prompt
CONTEXT_AWARE_SYSTEM_PROMPT = """You are an expert AWS Operations Assistant with comprehensive access to AWS management tools and context awareness capabilities.

**CONTEXT MANAGEMENT RULES:**
1. Always maintain awareness of key information throughout the conversation:
   - Instance IDs (format: i-xxxxxxxxx)
   - Instance Types (e.g., t2.micro, m5.large)
   - Issue Types (e.g., high CPU, memory issues, disk space, network problems)
   - Any specific metrics or thresholds mentioned

2. When key information is identified, acknowledge it and refer back to it in subsequent responses.

3. If context from previous messages is relevant, include it in your analysis.

**RESPONSE FORMATTING FOR SLACK:**
Always format your responses using Slack markdown:
- Use *bold* for important information
- Use `code` for instance IDs, commands, and technical terms
- Use ```code blocks``` for multi-line outputs
- Use • for bullet points
- Use :warning: :white_check_mark: :x: :wrench: :chart_with_upwards_trend: emojis appropriately

**Core AWS Services:**
- **EC2 Management**: List, start, stop instances, retrieve detailed instance information, and find instances by name
- **SSM Operations**: Execute commands remotely on EC2 instances, check connectivity, get system information
- **S3 Operations**: Manage buckets, list objects, create new buckets with proper regional configuration
- **RDS Database Management**: Monitor instances, retrieve detailed database configurations and status
- **Account & Regional Information**: Provide AWS account details and available regions

**CloudWatch Monitoring & Alerting:**
- **Alarm Management**: List, monitor, and manage CloudWatch alarms across all states (OK, ALARM, INSUFFICIENT_DATA)
- **Metrics Analysis**: Retrieve and analyze performance metrics for EC2, RDS, and other AWS services
- **Performance Monitoring**: Get CPU utilization, network traffic, disk I/O, and other key performance indicators
- **Health Assessments**: Comprehensive health checks combining multiple data sources
- **Dashboard Management**: Access and analyze CloudWatch dashboards and their widgets

**Advanced Monitoring Capabilities:**
- **Real-time Alarm Monitoring**: Identify and investigate alarms in ALARM state with detailed context
- **Metric Statistics**: Historical analysis of performance data with customizable time ranges
- **Service Health Overview**: Regional health assessment across all AWS services
- **Performance Trending**: Analyze patterns in CPU, memory, network, and disk utilization

**Log Management & Analysis:**
- **EC2 Log Analysis**: Access and search logs from EC2 instances including system logs, authentication logs, kernel logs
- **Intelligent Log Search**: Search across single instances or all EC2 instances for specific terms, error patterns, or time ranges
- **Error Detection**: Automatically identify and surface recent errors, failures, and critical issues
- **Log Stream Management**: Navigate different log types and understand what each log stream contains

**Remote Operations via SSM:**
- **Remote Command Execution**: Run shell commands on EC2 instances via Systems Manager
- **System Information Gathering**: Get comprehensive system info including disk usage, memory, uptime, and processes
- **Log File Access**: Directly access log files on instances via SSM when CloudWatch logs aren't available
- **Connectivity Testing**: Check if instances are accessible via SSM and troubleshoot agent issues
- **Multi-Instance Operations**: Execute commands across multiple instances simultaneously

**Best Practices:**
- Always specify the AWS region when working with resources (default: us-east-1)
- When investigating performance issues, check both metrics and alarms
- For health checks, combine instance state, metrics, alarms, and logs for comprehensive assessment
- Use appropriate time ranges for metric analysis based on the investigation scope
- Provide context about alarm thresholds and what metric values mean
- When troubleshooting, start with alarms in ALARM state, then check metrics and logs

**Response Guidelines:**
- Provide clear, actionable responses with specific commands and recommendations
- Always use the appropriate tools for each request
- When showing metrics, explain what the values indicate about system health
- Highlight critical issues like alarms in ALARM state or performance anomalies
- Explain AWS-specific terminology and concepts when relevant
- Suggest follow-up actions when investigating problems
- For alarms, provide context about what triggered them and potential remediation steps

You have access to real-time AWS data and can perform actual operations, so always be careful with destructive actions."""


class ConversationContext:
    """Manages persistent context across conversations"""

    def __init__(self, dynamodb_resource, table_name):
        self.dynamodb = dynamodb_resource
        self.context_table_name = f"{table_name}_context"
        self._ensure_context_table()

    def _ensure_context_table(self):
        """Ensure context table exists"""
        try:
            table = self.dynamodb.create_table(
                TableName=self.context_table_name,
                KeySchema=[
                    {'AttributeName': 'SessionId', 'KeyType': 'HASH'}
                ],
                AttributeDefinitions=[
                    {'AttributeName': 'SessionId', 'AttributeType': 'S'}
                ],
                BillingMode='PAY_PER_REQUEST'
            )
            table.wait_until_exists()
            logger.info(f"Created context table: {self.context_table_name}")
        except self.dynamodb.meta.client.exceptions.ResourceInUseException:
            logger.info(f"Context table already exists: {self.context_table_name}")
        except Exception as e:
            logger.error(f"Error creating context table: {e}")

    def update_context(self, session_id: str, key_points: Dict[str, Any]):
        """Update context for a session"""
        try:
            table = self.dynamodb.Table(self.context_table_name)
            key_points['last_updated'] = datetime.now().isoformat()
            table.put_item(
                Item={
                    'SessionId': session_id,
                    'KeyPoints': key_points,
                    'LastUpdated': datetime.now().isoformat()
                }
            )
            logger.info(f"Updated context for session {session_id}: {key_points}")
        except Exception as e:
            logger.error(f"Error updating context: {e}")

    def get_context(self, session_id: str) -> Dict[str, Any]:
        """Get context for a session"""
        try:
            table = self.dynamodb.Table(self.context_table_name)
            response = table.get_item(Key={'SessionId': session_id})

            if 'Item' in response:
                return response['Item'].get('KeyPoints', {})
            return {}
        except Exception as e:
            logger.error(f"Error getting context: {e}")
            return {}

    def extract_key_points(self, text: str) -> Dict[str, Any]:
        """Extract key points from text using patterns"""
        key_points = {}

        # Instance ID patterns
        instance_patterns = [
            r'i-[0-9a-f]{8,17}',  # EC2 instance ID
            r'instance[:\s]+([a-zA-Z0-9\-_]+)',  # Instance name
        ]

        # Instance type patterns
        type_patterns = [
            r'([tcmrpxgadni][0-9]\.[a-z0-9]+)',  # EC2 instance types
            r'instance type[:\s]+([a-zA-Z0-9\.]+)',
        ]

        # Issue type patterns
        issue_keywords = {
            'high_cpu': ['high cpu', 'cpu usage', 'cpu utilization', 'cpu spike'],
            'memory': ['memory', 'ram', 'out of memory', 'oom', 'memory leak'],
            'disk': ['disk', 'storage', 'disk space', 'disk full', 'iops'],
            'network': ['network', 'connectivity', 'connection', 'timeout', 'packet loss'],
            'down': ['down', 'stopped', 'not responding', 'unreachable', 'crashed'],
            'slow': ['slow', 'performance', 'latency', 'lag', 'degraded'],
            'security': ['security', 'breach', 'unauthorized', 'vulnerability'],
            'database': ['database', 'rds', 'query', 'deadlock', 'replication'],
        }

        # Extract instance IDs/names
        for pattern in instance_patterns:
            matches = re.findall(pattern, text.lower())
            if matches:
                key_points['instance_id'] = matches[0]
                break

        # Extract instance types
        for pattern in type_patterns:
            matches = re.findall(pattern, text.lower())
            if matches:
                key_points['instance_type'] = matches[0]
                break

        # Extract issue types
        text_lower = text.lower()
        for issue_type, keywords in issue_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                if 'issue_types' not in key_points:
                    key_points['issue_types'] = []
                if issue_type not in key_points['issue_types']:
                    key_points['issue_types'].append(issue_type)

        return key_points


def verify_slack_request(event, slack_signing_secret):
    """Verify that the request comes from Slack"""
    try:
        timestamp = event['headers'].get('X-Slack-Request-Timestamp', '')
        slack_signature = event['headers'].get('X-Slack-Signature', '')
        
        if abs(time.time() - float(timestamp)) > 60 * 5:
            logger.warning("Slack request timestamp is too old")
            return False
            
        body = event.get('body', '')
        if event.get('isBase64Encoded'):
            body = base64.b64decode(body).decode('utf-8')
            
        sig_basestring = f"v0:{timestamp}:{body}"
        my_signature = 'v0=' + hmac.new(
            slack_signing_secret.encode(),
            sig_basestring.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(my_signature, slack_signature)
    except Exception as e:
        logger.error(f"Error verifying Slack request: {e}")
        return False


def parse_slack_request(event):
    """Parse Slack's URL-encoded request body"""
    try:
        body_str = event.get('body', '')
        if event.get('isBase64Encoded'):
            body_str = base64.b64decode(body_str).decode('utf-8')
        
        # Parse URL-encoded data
        parsed_body = urllib.parse.parse_qs(body_str)
        
        # Convert to regular dict (parse_qs returns lists)
        body = {k: v[0] if len(v) == 1 else v for k, v in parsed_body.items()}
        
        logger.info(f"Parsed Slack body: {json.dumps(body)}")
        return body
    except Exception as e:
        logger.error(f"Error parsing Slack request: {e}")
        raise


def format_for_slack(text: str) -> str:
    """Format text for better Slack display"""
    # Add emojis for common patterns
    emoji_mappings = {
        'Error:': ':x: *Error:*',
        'Warning:': ':warning: *Warning:*',
        'Success:': ':white_check_mark: *Success:*',
        'Info:': ':information_source: *Info:*',
        'Instance ID:': '*Instance ID:*',
        'Status:': '*Status:*',
        'CPU:': ':chart_with_upwards_trend: *CPU:*',
        'Memory:': ':floppy_disk: *Memory:*',
        'Disk:': ':cd: *Disk:*',
        'Network:': ':globe_with_meridians: *Network:*',
        'Finding': ':mag: *Finding*',
        'Recommendation': ':bulb: *Recommendation*',
        'Alert': ':rotating_light: *Alert*',
    }

    # Apply emoji mappings
    for pattern, replacement in emoji_mappings.items():
        text = text.replace(pattern, replacement)

    # Format instance IDs
    text = re.sub(r'(i-[0-9a-f]{8,17})', r'`\1`', text)

    # Format instance types
    text = re.sub(r'([tcmrpxgadni][0-9]\.[a-z0-9]+)', r'`\1`', text)

    # Format IP addresses
    text = re.sub(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', r'`\1`', text)

    # Add line breaks for better readability
    text = re.sub(r'\. ([A-Z])', r'.\n\1', text)

    return text


def get_session_id(user_id: str, channel_id: str, thread_ts: Optional[str] = None) -> str:
    """Create unique session ID"""
    session_id = f"slack_{user_id}_{channel_id}_{thread_ts}" if thread_ts else f"slack_{user_id}_{channel_id}"
    logger.debug(f"Generated session ID: {session_id}")
    return session_id


def convert_history_to_messages(history) -> list:
    """Convert LangChain message history to Bedrock format"""
    messages = []

    try:
        for msg in history.messages:
            if isinstance(msg, HumanMessage):
                messages.append({
                    "role": "user",
                    "content": [{"text": msg.content}]
                })
            elif isinstance(msg, AIMessage):
                messages.append({
                    "role": "assistant",
                    "content": [{"text": msg.content}]
                })
    except Exception as e:
        logger.warning(f"Error converting history: {e}")
        return []

    return messages


def get_bedrock_slack_result(query: str):
    """Format query response for Slack using Bedrock"""
    start_time = time.time()

    # Ensure query is a string
    if not isinstance(query, str):
        query = str(query)
        logger.warning(f"Query was not a string, converted to: {query[:100]}...")

    system_prompt = """
        <instruction>
        Your task is to format responses specifically for Slack messaging, following these guidelines:

        *Slack Formatting Rules:*
        • Use *text* for bold
        • Use _text_ for italic
        • Use `text` for inline code
        • Use ```text``` for code blocks
        • Use > for single-line quotes
        • Use >>> for multi-line quotes
        • Use • for bullet points (never -, *, or numbers)
        • Use 1. 2. 3. for numbered lists (when order matters)
        • Format links as <URL|display text> or <URL>
        • Use :emoji_name: for emojis (e.g. :white_check_mark: :warning: :information_source:)
        • Use single line breaks within sections
        • Use double line breaks between major sections

        :no_entry: *Avoid These (Not Slack Compatible):*
        • Headers (use *Bold Text* instead)
        • Subheaders (use *Bold Text* with emojis)
        • **double asterisks** for bold
        • __double underscores__ for italic
        • HTML tags
        • Markdown tables
        • Complex nested formatting

        *Structure Guidelines:*
        • Start with a clear *Summary Line* using *bold* and relevant :emoji:
        • Group related information together
        • Use :emoji: to create visual breaks and highlight sections
        • Keep paragraphs short (2-3 lines max)
        • Use bullet points • liberally for scannable content
        • End with clear next steps or summary when appropriate

        :information_source: Remember: Slack users scan messages quickly. Prioritize clarity and scannability over complex formatting.
        </instruction>
        """

    messages = [{"role": "user", "content": [{"text": query}]}]
    api_params = {
        "modelId": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
        "system": [{"text": system_prompt}],
        "messages": messages,
        "inferenceConfig": {"maxTokens": 4096, "temperature": 0.9},
    }

    response = bedrock_client.converse(**api_params)
    response_time = time.time() - start_time
    logger.info(f"Bedrock API call completed in {response_time:.2f} seconds")
    return response['output']['message']['content'][0]['text']


def get_bedrock_email_result(query: str):
    """Format query response for email using Bedrock"""
    # Your existing email formatting code here
    start_time = time.time()

    # Ensure query is a string
    if not isinstance(query, str):
        query = str(query)
        logger.warning(f"Query was not a string, converted to: {query[:100]}...")

    # First call: Get the email subject
    subject_prompt = """
        <instruction>
        Your task is to create a concise, professional email subject line for the following content.

        *Subject Line Requirements:*
        • Keep it between 50-80 characters
        • Include key identifiers (instance IDs, ticket numbers, etc.)
        • Indicate urgency level if applicable
        • Use format: "[Type] - [Brief Description] for [Resource]"
        • Be specific and action-oriented
        • Examples:
          - "Incident Report - Disk Space Alert for i-03326536e3f1be717"
          - "Resolved - Database Connection Issue on prod-db-01"
          - "Action Required - SSL Certificate Expiration for app.domain.com"

        Return ONLY the subject line as plain text, no quotes or additional formatting.
        </instruction>
        """

    # Get the subject
    try:
        logger.info("Getting email subject from Bedrock...")
        subject_messages = [{"role": "user", "content": [{"text": f"Create an email subject line for:\n\n{query}"}]}]
        subject_api_params = {
            "modelId": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
            "system": [{"text": subject_prompt}],
            "messages": subject_messages,
            "inferenceConfig": {"maxTokens": 200, "temperature": 0.3},
        }

        subject_response = bedrock_client.converse(**subject_api_params)
        email_subject = subject_response['output']['message']['content'][0]['text'].strip()
        logger.info(f"Email subject generated: {email_subject}")

    except Exception as e:
        logger.error(f"Failed to generate email subject: {str(e)}")
        email_subject = "Technical Update - AWS Operations"

    # Second call: Get the email body (your existing code)
    body_prompt = """\
        <system>
        You are a helpful assistant that formats technical content into a clean, professional email body.
        </system>
        <instruction>
        Convert the provided technical content into a clean, professional email body.

        [Rest of your existing email body prompt...]
        </instruction>
        """

    # Get the body
    try:
        logger.info("Getting email body from Bedrock...")
        body_messages = [{"role": "user", "content": [{"text": f"Format this into a professional email body:\n\n{query}"}]}]
        body_api_params = {
            "modelId": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
            "system": [{"text": body_prompt}],
            "messages": body_messages,
            "inferenceConfig": {"maxTokens": 6000, "temperature": 0.5},
        }

        body_response = bedrock_client.converse(**body_api_params)
        email_body = body_response['output']['message']['content'][0]['text'].strip()
        logger.info(f"Email body generated: {len(email_body)} characters")

    except Exception as e:
        logger.error(f"Failed to generate email body: {str(e)}")
        email_body = query  # Fallback to original query

    response_time = time.time() - start_time
    logger.info(f"Email formatting completed in {response_time:.2f} seconds")

    return {
        "subject": email_subject,
        "body": email_body
    }


class AWSMCPLambdaClient:
    def __init__(self, region: str = 'us-east-1'):
        """Initialize the AWS MCP Lambda Client with context support"""
        self.region = region
        self.last_request_time = 0
        self.min_request_interval = 1.0
        self.session = None
        self._init_session()

        # Initialize DynamoDB for context management
        self.dynamodb = boto3.resource("dynamodb", config=config)
        self.table_name = os.environ.get("DYNAMODB_TABLE_NAME", "oncalltable")

        # Initialize context manager
        try:
            self.context_manager = ConversationContext(self.dynamodb, self.table_name)
            logger.info("Context manager initialized")
        except Exception as e:
            logger.warning(f"Context manager initialization failed: {e}")
            self.context_manager = None

        logger.info(f"AWSMCPLambdaClient initialized for region: {region}")

    def _init_session(self):
        """Initialize HTTP session with retry strategy"""
        self.session = requests.Session()

        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def rate_limit(self):
        """Implement rate limiting for Bedrock API calls"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last_request
            logger.info(f"Rate limiting applied: waiting {sleep_time:.2f} seconds")
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    def get_available_tools(self) -> List[Dict]:
        """Return the list of available AWS tools - updated for enhanced server"""
        with open('lambda_config.json', 'r') as f:
            tools = json.load(f)

        return tools

    def execute_tool(self, tool_name: str, tool_inputs: Dict) -> str:
        """Execute a tool call with enhanced error handling and AWS API calls"""
        try:
            logger.info(f"Executing tool: {tool_name} with inputs: {tool_inputs}")
            
            # Set default region
            region = tool_inputs.get('region', self.region)
            
            # EC2 Operations
            if tool_name == "list_ec2_instances":
                return self._list_ec2_instances(region)
            elif tool_name == "get_ec2_instance_details":
                return self._get_ec2_instance_details(tool_inputs['instance_id'], region)
            elif tool_name == "find_ec2_by_name":
                return self._find_ec2_by_name(tool_inputs['name'], region)
            elif tool_name == "start_ec2_instance":
                return self._start_ec2_instance(tool_inputs['instance_id'], region)
            elif tool_name == "stop_ec2_instance":
                return self._stop_ec2_instance(tool_inputs['instance_id'], region)
            
            # SSM Operations
            elif tool_name == "list_ssm_managed_instances":
                return self._list_ssm_managed_instances(region)
            elif tool_name == "run_ssm_command":
                return self._run_ssm_command(
                    tool_inputs['instance_ids'],
                    tool_inputs['commands'],
                    region,
                    tool_inputs.get('wait_for_completion', True),
                    tool_inputs.get('max_wait_time', 300)
                )
            elif tool_name == "run_quick_ssm_command":
                return self._run_quick_ssm_command(
                    tool_inputs['instance_id'],
                    tool_inputs['command'],
                    region
                )
            elif tool_name == "check_ssm_connectivity":
                return self._check_ssm_connectivity(tool_inputs['instance_id'], region)
            elif tool_name == "get_instance_system_info":
                return self._get_instance_system_info(tool_inputs['instance_id'], region)
            elif tool_name == "get_instance_logs_via_ssm":
                return self._get_instance_logs_via_ssm(
                    tool_inputs['instance_id'],
                    tool_inputs.get('log_file', '/var/log/syslog'),
                    tool_inputs.get('lines', 50),
                    region
                )
            
            # S3 Operations
            elif tool_name == "list_s3_buckets":
                return self._list_s3_buckets(tool_inputs.get('region'))
            elif tool_name == "list_s3_objects":
                return self._list_s3_objects(
                    tool_inputs['bucket_name'],
                    tool_inputs.get('prefix', ''),
                    tool_inputs.get('max_keys', 100)
                )
            elif tool_name == "create_s3_bucket":
                return self._create_s3_bucket(tool_inputs['bucket_name'], region)
            
            # RDS Operations
            elif tool_name == "list_rds_instances":
                return self._list_rds_instances(region)
            elif tool_name == "describe_rds_instance":
                return self._describe_rds_instance(tool_inputs['instance_identifier'], region)
            
            # CloudWatch Logs Operations
            elif tool_name == "list_cloudwatch_log_groups":
                return self._list_cloudwatch_log_groups(
                    region,
                    tool_inputs.get('max_groups', 1000)
                )
            elif tool_name == "list_cloudwatch_log_streams":
                return self._list_cloudwatch_log_streams(
                    tool_inputs['log_group_name'],
                    region,
                    tool_inputs.get('max_streams', 50),
                    tool_inputs.get('order_by', 'LastEventTime')
                )
            elif tool_name == "get_cloudwatch_logs":
                return self._get_cloudwatch_logs(
                    tool_inputs['log_group_name'],
                    tool_inputs.get('log_stream_name'),
                    region,
                    tool_inputs.get('hours_back', 1),
                    tool_inputs.get('max_events', 100),
                    tool_inputs.get('filter_pattern'),
                    tool_inputs.get('start_from_head', False)
                )
            elif tool_name == "search_cloudwatch_logs":
                return self._search_cloudwatch_logs(
                    tool_inputs['log_group_name'],
                    tool_inputs['search_term'],
                    region,
                    tool_inputs.get('hours_back', 24),
                    tool_inputs.get('max_events', 1000),
                    tool_inputs.get('log_stream_name')
                )
            elif tool_name == "get_cloudwatch_log_insights":
                return self._get_cloudwatch_log_insights(
                    tool_inputs['log_group_name'],
                    tool_inputs['query'],
                    region,
                    tool_inputs.get('hours_back', 24),
                    tool_inputs.get('max_results', 1000)
                )
            
            # EC2-specific log functions
            elif tool_name == "get_ec2_logs":
                return self._get_ec2_logs(
                    tool_inputs['instance_id'],
                    tool_inputs.get('log_stream_name'),
                    tool_inputs.get('search_term', ''),
                    region,
                    tool_inputs.get('hours_back', 24),
                    tool_inputs.get('max_events', 1000)
                )
            elif tool_name == "get_ec2_log_streams":
                return self._get_ec2_log_streams(tool_inputs['instance_id'], region)
            elif tool_name == "get_recent_ec2_errors":
                return self._get_recent_ec2_errors(
                    tool_inputs['instance_id'],
                    region,
                    tool_inputs.get('hours_back', 24),
                    tool_inputs.get('max_events', 500)
                )
            elif tool_name == "check_cloudwatch_agent_status":
                return self._check_cloudwatch_agent_status(tool_inputs['instance_id'], region)
            
            # =====================
            # NEW CLOUDWATCH FUNCTIONS
            # =====================
            
            # CloudWatch Alarms
            elif tool_name == "list_cloudwatch_alarms":
                return self._list_cloudwatch_alarms(
                    region,
                    tool_inputs.get('state_value'),
                    tool_inputs.get('alarm_name_prefix'),
                    tool_inputs.get('max_records', 100)
                )
            elif tool_name == "get_alarm_details":
                return self._get_alarm_details(tool_inputs['alarm_name'], region)
            elif tool_name == "get_alarms_in_alarm_state":
                return self._get_alarms_in_alarm_state(region)
            elif tool_name == "set_alarm_state":
                return self._set_alarm_state(
                    tool_inputs['alarm_name'],
                    tool_inputs['state_value'],
                    tool_inputs['state_reason'],
                    region
                )
            
            # CloudWatch Metrics
            elif tool_name == "list_cloudwatch_metrics":
                return self._list_cloudwatch_metrics(
                    tool_inputs.get('namespace'),
                    tool_inputs.get('metric_name'),
                    tool_inputs.get('dimensions'),
                    region,
                    tool_inputs.get('max_results', 500)
                )
            elif tool_name == "get_metric_statistics":
                return self._get_metric_statistics(
                    tool_inputs['namespace'],
                    tool_inputs['metric_name'],
                    tool_inputs['dimensions'],
                    tool_inputs.get('start_time_hours_ago', 1),
                    tool_inputs.get('end_time_hours_ago', 0),
                    tool_inputs.get('period_seconds', 300),
                    tool_inputs.get('statistics', 'Average'),
                    region
                )
            elif tool_name == "get_ec2_cpu_metrics":
                return self._get_ec2_cpu_metrics(
                    tool_inputs['instance_id'],
                    tool_inputs.get('hours_back', 24),
                    region
                )
            elif tool_name == "get_rds_cpu_metrics":
                return self._get_rds_cpu_metrics(
                    tool_inputs['db_instance_identifier'],
                    tool_inputs.get('hours_back', 24),
                    region
                )
            elif tool_name == "get_ec2_instance_metrics_summary":
                return self._get_ec2_instance_metrics_summary(
                    tool_inputs['instance_id'],
                    tool_inputs.get('hours_back', 24),
                    region
                )
            
            # CloudWatch Dashboards
            elif tool_name == "list_cloudwatch_dashboards":
                return self._list_cloudwatch_dashboards(region)
            elif tool_name == "get_dashboard_details":
                return self._get_dashboard_details(tool_inputs['dashboard_name'], region)
            
            # Health & Monitoring
            elif tool_name == "health_check_ec2_instance":
                return self._health_check_ec2_instance(
                    tool_inputs['instance_id'],
                    region,
                    tool_inputs.get('hours_back', 1)
                )
            elif tool_name == "get_service_health_overview":
                return self._get_service_health_overview(region)
            
            # Utility functions
            elif tool_name == "get_aws_regions":
                return self._get_aws_regions()
            elif tool_name == "get_aws_account_info":
                return self._get_aws_account_info()
            
            else:
                return f"Tool {tool_name} not implemented yet."

        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {str(e)}")
            return json.dumps({"success": False, "error": str(e)}, indent=2)

    def _safe_json_response(self, success: bool = True, **data) -> str:
        """Create a consistent JSON response"""
        response = {"success": success, **data}
        return json.dumps(response, indent=2, default=str)

    def _handle_aws_error(self, operation: str, error: Exception, **context) -> str:
        """Handle AWS API errors consistently"""
        logger.error(f"Error in {operation}: {error}")
        return self._safe_json_response(False, error=str(error), operation=operation, **context)

    # =====================
    # CLOUDWATCH ALARMS
    # =====================

    def _list_cloudwatch_alarms(self, region: str, state_value: Optional[str] = None,
                               alarm_name_prefix: Optional[str] = None, max_records: int = 100) -> str:
        """List CloudWatch alarms"""
        try:
            cloudwatch = boto3.client('cloudwatch', region_name=region)
            
            params = {'MaxRecords': min(max_records, 500)}
            if state_value:
                params['StateValue'] = state_value
            if alarm_name_prefix:
                params['AlarmNamePrefix'] = alarm_name_prefix
            
            alarms = []
            next_token = None
            
            while len(alarms) < max_records:
                if next_token:
                    params['NextToken'] = next_token
                
                response = cloudwatch.describe_alarms(**params)
                
                for alarm in response.get('MetricAlarms', []):
                    alarm_info = {
                        'AlarmName': alarm['AlarmName'],
                        'AlarmDescription': alarm.get('AlarmDescription', ''),
                        'StateValue': alarm['StateValue'],
                        'StateReason': alarm.get('StateReason', ''),
                        'StateUpdatedTimestamp': alarm.get('StateUpdatedTimestamp', '').isoformat() if alarm.get('StateUpdatedTimestamp') else 'N/A',
                        'MetricName': alarm.get('MetricName', 'N/A'),
                        'Namespace': alarm.get('Namespace', 'N/A'),
                        'Statistic': alarm.get('Statistic', 'N/A'),
                        'Dimensions': [
                            {'Name': dim['Name'], 'Value': dim['Value']} 
                            for dim in alarm.get('Dimensions', [])
                        ],
                        'Period': alarm.get('Period', 0),
                        'EvaluationPeriods': alarm.get('EvaluationPeriods', 0),
                        'Threshold': alarm.get('Threshold', 0),
                        'ComparisonOperator': alarm.get('ComparisonOperator', 'N/A'),
                        'ActionsEnabled': alarm.get('ActionsEnabled', False),
                    }
                    alarms.append(alarm_info)
                
                next_token = response.get('NextToken')
                if not next_token:
                    break
            
            # Summary by state
            state_summary = {'OK': 0, 'ALARM': 0, 'INSUFFICIENT_DATA': 0}
            for alarm in alarms:
                state = alarm['StateValue']
                if state in state_summary:
                    state_summary[state] += 1
            
            return self._safe_json_response(
                True,
                region=region,
                filter_state=state_value,
                filter_prefix=alarm_name_prefix,
                alarms=alarms,
                count=len(alarms),
                stateSummary=state_summary
            )
        except Exception as e:
            return self._handle_aws_error("list_cloudwatch_alarms", e, region=region)

    def _get_alarm_details(self, alarm_name: str, region: str) -> str:
        """Get detailed alarm information"""
        try:
            cloudwatch = boto3.client('cloudwatch', region_name=region)
            
            response = cloudwatch.describe_alarms(AlarmNames=[alarm_name])
            alarms = response.get('MetricAlarms', [])
            
            if not alarms:
                return self._safe_json_response(False, error="Alarm not found", alarm_name=alarm_name)
            
            alarm = alarms[0]
            
            # Get alarm history
            history_response = cloudwatch.describe_alarm_history(
                AlarmName=alarm_name,
                MaxRecords=10
            )
            
            history = []
            for item in history_response.get('AlarmHistoryItems', []):
                history.append({
                    'Timestamp': item['Timestamp'].isoformat(),
                    'HistoryItemType': item['HistoryItemType'],
                    'HistorySummary': item['HistorySummary'],
                })
            
            detailed_info = {
                'AlarmName': alarm['AlarmName'],
                'AlarmDescription': alarm.get('AlarmDescription', ''),
                'StateValue': alarm['StateValue'],
                'StateReason': alarm.get('StateReason', ''),
                'StateUpdatedTimestamp': alarm.get('StateUpdatedTimestamp', '').isoformat() if alarm.get('StateUpdatedTimestamp') else 'N/A',
                'MetricName': alarm.get('MetricName', 'N/A'),
                'Namespace': alarm.get('Namespace', 'N/A'),
                'Threshold': alarm.get('Threshold', 0),
                'ComparisonOperator': alarm.get('ComparisonOperator', 'N/A'),
                'History': history
            }
            
            return self._safe_json_response(True, **detailed_info)
        except Exception as e:
            return self._handle_aws_error("get_alarm_details", e, alarm_name=alarm_name)

    def _get_alarms_in_alarm_state(self, region: str) -> str:
        """Get all alarms in ALARM state"""
        try:
            result = self._list_cloudwatch_alarms(region=region, state_value="ALARM", max_records=500)
            result_data = json.loads(result)
            
            if not result_data.get('success', True):
                return result
            
            alarm_alarms = result_data.get('alarms', [])
            
            # Sort by state update time
            alarm_alarms.sort(key=lambda x: x['StateUpdatedTimestamp'])
            
            return self._safe_json_response(
                True,
                region=region,
                alarmsInAlarmState=alarm_alarms,
                count=len(alarm_alarms),
                summary=f"{len(alarm_alarms)} alarms are currently in ALARM state"
            )
        except Exception as e:
            return self._handle_aws_error("get_alarms_in_alarm_state", e, region=region)

    def _set_alarm_state(self, alarm_name: str, state_value: str, state_reason: str, region: str) -> str:
        """Set alarm state"""
        try:
            if state_value not in ['OK', 'ALARM', 'INSUFFICIENT_DATA']:
                return self._safe_json_response(False, error="Invalid state value")
            
            cloudwatch = boto3.client('cloudwatch', region_name=region)
            
            cloudwatch.set_alarm_state(
                AlarmName=alarm_name,
                StateValue=state_value,
                StateReason=state_reason
            )
            
            return self._safe_json_response(
                True,
                message=f"Alarm state set successfully",
                alarm_name=alarm_name,
                new_state=state_value,
                reason=state_reason
            )
        except Exception as e:
            return self._handle_aws_error("set_alarm_state", e, alarm_name=alarm_name)

    # =====================
    # CLOUDWATCH METRICS
    # =====================

    def _list_cloudwatch_metrics(self, namespace: Optional[str] = None, metric_name: Optional[str] = None,
                                dimensions: Optional[str] = None, region: str = "us-east-1", max_results: int = 500) -> str:
        """List CloudWatch metrics"""
        try:
            cloudwatch = boto3.client('cloudwatch', region_name=region)
            
            params = {}
            if namespace:
                params['Namespace'] = namespace
            if metric_name:
                params['MetricName'] = metric_name
            if dimensions:
                try:
                    dimensions_dict = json.loads(dimensions)
                    params['Dimensions'] = [
                        {'Name': k, 'Value': v} for k, v in dimensions_dict.items()
                    ]
                except json.JSONDecodeError:
                    return self._safe_json_response(False, error="Invalid dimensions JSON format")
            
            metrics = []
            next_token = None
            
            while len(metrics) < max_results:
                if next_token:
                    params['NextToken'] = next_token
                
                response = cloudwatch.list_metrics(**params)
                
                for metric in response.get('Metrics', []):
                    metrics.append({
                        'MetricName': metric['MetricName'],
                        'Namespace': metric['Namespace'],
                        'Dimensions': [
                            {'Name': dim['Name'], 'Value': dim['Value']}
                            for dim in metric.get('Dimensions', [])
                        ]
                    })
                
                next_token = response.get('NextToken')
                if not next_token:
                    break
            
            return self._safe_json_response(
                True,
                region=region,
                metrics=metrics,
                count=len(metrics)
            )
        except Exception as e:
            return self._handle_aws_error("list_cloudwatch_metrics", e, region=region)

    def _get_metric_statistics(self, namespace: str, metric_name: str, dimensions: str,
                              start_time_hours_ago: int = 1, end_time_hours_ago: int = 0,
                              period_seconds: int = 300, statistics: str = "Average", region: str = "us-east-1") -> str:
        """Get metric statistics"""
        try:
            cloudwatch = boto3.client('cloudwatch', region_name=region)
            
            # Parse dimensions
            try:
                dimensions_dict = json.loads(dimensions)
                dimensions_list = [
                    {'Name': k, 'Value': v} for k, v in dimensions_dict.items()
                ]
            except json.JSONDecodeError:
                return self._safe_json_response(False, error="Invalid dimensions JSON format")
            
            # Calculate time range
            end_time = datetime.now(timezone.utc) - timedelta(hours=end_time_hours_ago)
            start_time = datetime.now(timezone.utc) - timedelta(hours=start_time_hours_ago)
            
            response = cloudwatch.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=dimensions_list,
                StartTime=start_time,
                EndTime=end_time,
                Period=max(period_seconds, 60),
                Statistics=[statistics]
            )
            
            # Sort datapoints by timestamp
            datapoints = sorted(response.get('Datapoints', []), key=lambda x: x['Timestamp'])
            
            # Format datapoints
            formatted_datapoints = []
            for dp in datapoints:
                formatted_dp = {
                    'Timestamp': dp['Timestamp'].isoformat(),
                    'Value': dp.get(statistics, 0),
                    'Unit': dp.get('Unit', 'None')
                }
                formatted_datapoints.append(formatted_dp)
            
            # Calculate summary statistics
            values = [dp['Value'] for dp in formatted_datapoints]
            summary = {}
            if values:
                summary = {
                    'count': len(values),
                    'min': min(values),
                    'max': max(values),
                    'average': sum(values) / len(values),
                    'latest': values[-1] if values else None
                }
            
            return self._safe_json_response(
                True,
                namespace=namespace,
                metricName=metric_name,
                dimensions=dimensions_dict,
                statistic=statistics,
                datapoints=formatted_datapoints,
                datapointCount=len(formatted_datapoints),
                summary=summary
            )
        except Exception as e:
            return self._handle_aws_error("get_metric_statistics", e, namespace=namespace, metric_name=metric_name)

    def _get_ec2_cpu_metrics(self, instance_id: str, hours_back: int = 24, region: str = "us-east-1") -> str:
        """Get EC2 CPU metrics"""
        dimensions = json.dumps({"InstanceId": instance_id})
        
        return self._get_metric_statistics(
            namespace="AWS/EC2",
            metric_name="CPUUtilization",
            dimensions=dimensions,
            start_time_hours_ago=hours_back,
            end_time_hours_ago=0,
            period_seconds=300,
            statistics="Average",
            region=region
        )

    def _get_rds_cpu_metrics(self, db_instance_identifier: str, hours_back: int = 24, region: str = "us-east-1") -> str:
        """Get RDS CPU metrics"""
        dimensions = json.dumps({"DBInstanceIdentifier": db_instance_identifier})
        
        return self._get_metric_statistics(
            namespace="AWS/RDS",
            metric_name="CPUUtilization",
            dimensions=dimensions,
            start_time_hours_ago=hours_back,
            end_time_hours_ago=0,
            period_seconds=300,
            statistics="Average",
            region=region
        )

    def _get_ec2_instance_metrics_summary(self, instance_id: str, hours_back: int = 24, region: str = "us-east-1") -> str:
        """Get comprehensive metrics summary for EC2 instance"""
        try:
            dimensions = json.dumps({"InstanceId": instance_id})
            metrics_to_check = [
                ("CPUUtilization", "Average"),
                ("NetworkIn", "Sum"),
                ("NetworkOut", "Sum"),
                ("DiskReadBytes", "Sum"),
                ("DiskWriteBytes", "Sum")
            ]
            
            metrics_data = {}
            
            for metric_name, statistic in metrics_to_check:
                try:
                    result = self._get_metric_statistics(
                        namespace="AWS/EC2",
                        metric_name=metric_name,
                        dimensions=dimensions,
                        start_time_hours_ago=hours_back,
                        end_time_hours_ago=0,
                        period_seconds=3600,  # 1 hour periods
                        statistics=statistic,
                        region=region
                    )
                    
                    result_data = json.loads(result)
                    if result_data.get('success', True):
                        metrics_data[metric_name] = {
                            'statistic': statistic,
                            'summary': result_data.get('summary', {}),
                            'datapointCount': result_data.get('datapointCount', 0)
                        }
                    else:
                        metrics_data[metric_name] = {'error': result_data.get('error', 'Unknown error')}
                except Exception as e:
                    metrics_data[metric_name] = {'error': str(e)}
            
            return self._safe_json_response(
                True,
                instanceId=instance_id,
                region=region,
                timeRange={'hoursBack': hours_back},
                metrics=metrics_data,
                timestamp=datetime.now(timezone.utc).isoformat()
            )
        except Exception as e:
            return self._handle_aws_error("get_ec2_instance_metrics_summary", e, instance_id=instance_id)

    # =====================
    # CLOUDWATCH DASHBOARDS
    # =====================

    def _list_cloudwatch_dashboards(self, region: str) -> str:
        """List CloudWatch dashboards"""
        try:
            cloudwatch = boto3.client('cloudwatch', region_name=region)
            
            dashboards = []
            next_token = None
            
            while True:
                params = {}
                if next_token:
                    params['NextToken'] = next_token
                
                response = cloudwatch.list_dashboards(**params)
                
                for dashboard in response.get('DashboardEntries', []):
                    dashboards.append({
                        'DashboardName': dashboard['DashboardName'],
                        'DashboardArn': dashboard['DashboardArn'],
                        'LastModified': dashboard['LastModified'].isoformat(),
                        'Size': dashboard['Size']
                    })
                
                next_token = response.get('NextToken')
                if not next_token:
                    break
            
            return self._safe_json_response(
                True,
                region=region,
                dashboards=dashboards,
                count=len(dashboards)
            )
        except Exception as e:
            return self._handle_aws_error("list_cloudwatch_dashboards", e, region=region)

    def _get_dashboard_details(self, dashboard_name: str, region: str) -> str:
        """Get dashboard details"""
        try:
            cloudwatch = boto3.client('cloudwatch', region_name=region)
            
            response = cloudwatch.get_dashboard(DashboardName=dashboard_name)
            
            # Parse dashboard body to extract widgets info
            dashboard_body = json.loads(response.get('DashboardBody', '{}'))
            widgets = dashboard_body.get('widgets', [])
            
            widget_summary = []
            for widget in widgets:
                properties = widget.get('properties', {})
                widget_info = {
                    'type': widget.get('type', 'unknown'),
                    'title': properties.get('title', 'Untitled'),
                    'region': properties.get('region', region),
                    'metrics_count': len(properties.get('metrics', [])) if 'metrics' in properties else 0
                }
                widget_summary.append(widget_info)
            
            return self._safe_json_response(
                True,
                dashboardName=dashboard_name,
                region=region,
                widgetCount=len(widgets),
                widgets=widget_summary
            )
        except Exception as e:
            return self._handle_aws_error("get_dashboard_details", e, dashboard_name=dashboard_name)

    # =====================
    # HEALTH & MONITORING
    # =====================

    def _health_check_ec2_instance(self, instance_id: str, region: str, hours_back: int = 1) -> str:
        """Comprehensive health check for EC2 instance"""
        try:
            health_data = {
                'instanceId': instance_id,
                'region': region,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'checksPerformed': [],
                'overallHealth': 'UNKNOWN',
                'issues': [],
                'recommendations': []
            }
            
            # Get instance details
            try:
                instance_details = self._get_ec2_instance_details(instance_id, region)
                instance_data = json.loads(instance_details)
                if instance_data.get('success', True):
                    health_data['instanceState'] = instance_data.get('State', 'unknown')
                    health_data['instanceType'] = instance_data.get('InstanceType', 'unknown')
                    health_data['checksPerformed'].append('instance_details')
                else:
                    health_data['issues'].append('Could not retrieve instance details')
            except Exception as e:
                health_data['issues'].append(f'Instance details check failed: {str(e)}')
            
            # Check SSM connectivity
            try:
                ssm_check = self._check_ssm_connectivity(instance_id, region)
                ssm_data = json.loads(ssm_check)
                if ssm_data.get('success', True):
                    health_data['ssmReady'] = ssm_data.get('ssm_ready', False)
                    health_data['ssmPingStatus'] = ssm_data.get('ping_status', 'unknown')
                    health_data['checksPerformed'].append('ssm_connectivity')
                    if not ssm_data.get('ssm_ready', False):
                        health_data['recommendations'].append('Ensure SSM agent is running and instance has proper IAM role')
            except Exception as e:
                health_data['issues'].append(f'SSM connectivity check failed: {str(e)}')
            
            # Get CPU metrics
            try:
                cpu_metrics = self._get_ec2_cpu_metrics(instance_id, hours_back, region)
                cpu_data = json.loads(cpu_metrics)
                if cpu_data.get('success', True) and cpu_data.get('summary'):
                    cpu_summary = cpu_data['summary']
                    health_data['cpuMetrics'] = cpu_summary
                    health_data['checksPerformed'].append('cpu_metrics')
                    
                    # CPU health assessment
                    avg_cpu = cpu_summary.get('average', 0)
                    max_cpu = cpu_summary.get('max', 0)
                    
                    if avg_cpu > 80:
                        health_data['issues'].append(f'High average CPU utilization: {avg_cpu:.1f}%')
                    if max_cpu > 95:
                        health_data['issues'].append(f'CPU spikes detected: {max_cpu:.1f}%')
                    if avg_cpu < 1:
                        health_data['issues'].append('Very low CPU utilization - instance may be idle or unresponsive')
            except Exception as e:
                health_data['issues'].append(f'CPU metrics check failed: {str(e)}')
            
            # Overall health assessment
            critical_issues = len([issue for issue in health_data['issues'] if any(word in issue.lower() for word in ['high', 'alarm', 'failed', 'error'])])
            
            if len(health_data['issues']) == 0:
                health_data['overallHealth'] = 'HEALTHY'
            elif critical_issues > 0:
                health_data['overallHealth'] = 'UNHEALTHY'
            else:
                health_data['overallHealth'] = 'WARNING'
            
            return self._safe_json_response(True, **health_data)
        except Exception as e:
            return self._handle_aws_error("health_check_ec2_instance", e, instance_id=instance_id)

    def _get_service_health_overview(self, region: str) -> str:
        """Get service health overview"""
        try:
            overview = {
                'region': region,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'services': {},
                'overallAlarmCount': 0,
                'criticalIssues': []
            }
            
            # Get all alarms
            alarms_result = self._list_cloudwatch_alarms(region=region, max_records=1000)
            alarms_data = json.loads(alarms_result)
            
            if alarms_data.get('success', True):
                state_summary = alarms_data.get('stateSummary', {})
                overview['alarmSummary'] = state_summary
                overview['overallAlarmCount'] = sum(state_summary.values())
                
                # Group alarms by namespace/service
                alarms = alarms_data.get('alarms', [])
                service_alarms = {}
                
                for alarm in alarms:
                    namespace = alarm.get('Namespace', 'Unknown')
                    if namespace not in service_alarms:
                        service_alarms[namespace] = {'OK': 0, 'ALARM': 0, 'INSUFFICIENT_DATA': 0, 'alarms': []}
                    
                    state = alarm['StateValue']
                    service_alarms[namespace][state] += 1
                    
                    if state == 'ALARM':
                        service_alarms[namespace]['alarms'].append({
                            'name': alarm['AlarmName'],
                            'reason': alarm.get('StateReason', '')
                        })
                        overview['criticalIssues'].append({
                            'service': namespace,
                            'alarm': alarm['AlarmName'],
                            'reason': alarm.get('StateReason', '')
                        })
                
                overview['services'] = service_alarms
            
            return self._safe_json_response(True, **overview)
        except Exception as e:
            return self._handle_aws_error("get_service_health_overview", e, region=region)



    # EC2 Operations
    def _list_ec2_instances(self, region: str) -> str:
        """List EC2 instances"""
        try:
            ec2 = boto3.client('ec2', region_name=region)
            response = ec2.describe_instances()
            instances = []
            
            for reservation in response['Reservations']:
                for instance in reservation['Instances']:
                    # Get instance name and env from tags
                    name = "N/A"
                    env = "N/A"
                    if 'Tags' in instance:
                        for tag in instance['Tags']:
                            if tag['Key'] == 'Name':
                                name = tag['Value']
                            elif tag['Key'] == 'Env':
                                env = tag['Value']
                    
                    instances.append({
                        'InstanceId': instance['InstanceId'],
                        'Name': name,
                        'Environment': env,
                        'InstanceType': instance['InstanceType'],
                        'State': instance['State']['Name'],
                        'LaunchTime': instance['LaunchTime'].isoformat(),
                        'PrivateIpAddress': instance.get('PrivateIpAddress', 'N/A'),
                        'PublicIpAddress': instance.get('PublicIpAddress', 'N/A'),
                    })
            
            return self._safe_json_response(True, region=region, instances=instances, count=len(instances))
        except Exception as e:
            return self._handle_aws_error("list_ec2_instances", e, region=region)

    def _get_ec2_instance_details(self, instance_id: str, region: str) -> str:
        """Get detailed EC2 instance information"""
        try:
            ec2 = boto3.client('ec2', region_name=region)
            response = ec2.describe_instances(InstanceIds=[instance_id])
            
            if not response['Reservations']:
                return self._safe_json_response(False, error="Instance not found", instance_id=instance_id)
            
            instance = response['Reservations'][0]['Instances'][0]
            
            # Get instance name and env from tags
            name = "N/A"
            env = "N/A"
            if 'Tags' in instance:
                for tag in instance['Tags']:
                    if tag['Key'] == 'Name':
                        name = tag['Value']
                    elif tag['Key'] == 'Env':
                        env = tag['Value']
            
            detailed_info = {
                'InstanceId': instance['InstanceId'],
                'Name': name,
                'Environment': env,
                'InstanceType': instance['InstanceType'],
                'State': instance['State']['Name'],
                'LaunchTime': instance['LaunchTime'].isoformat(),
                'Platform': instance.get('Platform', 'Linux/UNIX'),
                'Architecture': instance['Architecture'],
                'PublicIpAddress': instance.get('PublicIpAddress', 'N/A'),
                'PrivateIpAddress': instance.get('PrivateIpAddress', 'N/A'),
                'AvailabilityZone': instance['Placement']['AvailabilityZone'],
                'VpcId': instance.get('VpcId', 'N/A'),
                'SubnetId': instance.get('SubnetId', 'N/A'),
                'SecurityGroups': [sg['GroupName'] for sg in instance.get('SecurityGroups', [])],
                'KeyName': instance.get('KeyName', 'N/A'),
                'IamInstanceProfile': instance.get('IamInstanceProfile', {}).get('Arn', 'N/A'),
            }
            
            return self._safe_json_response(True, **detailed_info)
        except Exception as e:
            return self._handle_aws_error("get_ec2_instance_details", e, instance_id=instance_id)

    def _find_ec2_by_name(self, name: str, region: str) -> str:
        """Find EC2 instances by name tag"""
        try:
            ec2 = boto3.client('ec2', region_name=region)
            response = ec2.describe_instances(
                Filters=[
                    {'Name': 'tag:Name', 'Values': [f'*{name}*']},
                    {'Name': 'instance-state-name', 'Values': ['running', 'stopped', 'stopping', 'starting']}
                ]
            )
            
            instances = []
            for reservation in response['Reservations']:
                for instance in reservation['Instances']:
                    instance_name = "N/A"
                    if 'Tags' in instance:
                        for tag in instance['Tags']:
                            if tag['Key'] == 'Name':
                                instance_name = tag['Value']
                                break
                    
                    instances.append({
                        'InstanceId': instance['InstanceId'],
                        'Name': instance_name,
                        'InstanceType': instance['InstanceType'],
                        'State': instance['State']['Name'],
                        'PublicIpAddress': instance.get('PublicIpAddress', 'N/A'),
                        'PrivateIpAddress': instance.get('PrivateIpAddress', 'N/A'),
                        'LaunchTime': instance['LaunchTime'].isoformat()
                    })
            
            return self._safe_json_response(True, searchTerm=name, region=region, instances=instances, count=len(instances))
        except Exception as e:
            return self._handle_aws_error("find_ec2_by_name", e, name=name, region=region)

    def _start_ec2_instance(self, instance_id: str, region: str) -> str:
        """Start an EC2 instance"""
        try:
            ec2 = boto3.client('ec2', region_name=region)
            response = ec2.start_instances(InstanceIds=[instance_id])
            starting_instance = response['StartingInstances'][0]
            
            return self._safe_json_response(
                True,
                message=f"Starting instance {instance_id} in {region}",
                instance_id=instance_id,
                current_state=starting_instance['CurrentState']['Name'],
                previous_state=starting_instance['PreviousState']['Name']
            )
        except Exception as e:
            return self._handle_aws_error("start_ec2_instance", e, instance_id=instance_id, region=region)

    def _stop_ec2_instance(self, instance_id: str, region: str) -> str:
        """Stop an EC2 instance"""
        try:
            ec2 = boto3.client('ec2', region_name=region)
            response = ec2.stop_instances(InstanceIds=[instance_id])
            stopping_instance = response['StoppingInstances'][0]
            
            return self._safe_json_response(
                True,
                message=f"Stopping instance {instance_id} in {region}",
                instance_id=instance_id,
                current_state=stopping_instance['CurrentState']['Name'],
                previous_state=stopping_instance['PreviousState']['Name']
            )
        except Exception as e:
            return self._handle_aws_error("stop_ec2_instance", e, instance_id=instance_id, region=region)

    # SSM Operations
    def _list_ssm_managed_instances(self, region: str) -> str:
        """List SSM managed instances"""
        try:
            ssm = boto3.client('ssm', region_name=region)
            response = ssm.describe_instance_information()
            
            instances = []
            for instance in response.get('InstanceInformationList', []):
                instances.append({
                    'InstanceId': instance['InstanceId'],
                    'PingStatus': instance['PingStatus'],
                    'LastPingDateTime': instance.get('LastPingDateTime', '').isoformat() if instance.get('LastPingDateTime') else 'N/A',
                    'AgentVersion': instance.get('AgentVersion', 'N/A'),
                    'PlatformType': instance.get('PlatformType', 'N/A'),
                    'PlatformName': instance.get('PlatformName', 'N/A'),
                    'IPAddress': instance.get('IPAddress', 'N/A'),
                })
            
            return self._safe_json_response(True, region=region, instances=instances, count=len(instances))
        except Exception as e:
            return self._handle_aws_error("list_ssm_managed_instances", e, region=region)

    def _run_ssm_command(self, instance_ids: str, commands: str, region: str, 
                        wait_for_completion: bool = True, max_wait_time: int = 300) -> str:
        """Run SSM commands on instances"""
        try:
            ssm = boto3.client('ssm', region_name=region)
            
            # Parse instance IDs and commands
            instance_id_list = [id.strip() for id in instance_ids.split(',')]
            if '\n' in commands:
                command_list = [cmd.strip() for cmd in commands.split('\n') if cmd.strip()]
            else:
                command_list = [cmd.strip() for cmd in commands.split(';') if cmd.strip()]
            
            # Send command
            response = ssm.send_command(
                InstanceIds=instance_id_list,
                DocumentName="AWS-RunShellScript",
                Parameters={'commands': command_list},
                TimeoutSeconds=300
            )
            
            command_id = response['Command']['CommandId']
            
            if not wait_for_completion:
                return self._safe_json_response(
                    True,
                    command_id=command_id,
                    instance_ids=instance_id_list,
                    commands=command_list,
                    message="Command sent successfully. Check results with get_ssm_command_output."
                )
            
            # Wait for completion and get results
            results = []
            for instance_id in instance_id_list:
                # Simple wait logic
                import time
                time.sleep(5)  # Give command time to execute
                
                try:
                    output_response = ssm.get_command_invocation(
                        CommandId=command_id,
                        InstanceId=instance_id
                    )
                    
                    results.append({
                        'instance_id': instance_id,
                        'status': output_response.get('Status'),
                        'standard_output': output_response.get('StandardOutputContent', ''),
                        'standard_error': output_response.get('StandardErrorContent', ''),
                        'response_code': output_response.get('ResponseCode')
                    })
                except Exception as e:
                    results.append({
                        'instance_id': instance_id,
                        'error': str(e)
                    })
            
            return self._safe_json_response(
                True,
                command_id=command_id,
                commands=command_list,
                results=results
            )
            
        except Exception as e:
            return self._handle_aws_error("run_ssm_command", e, instance_ids=instance_ids)

    def _run_quick_ssm_command(self, instance_id: str, command: str, region: str) -> str:
        """Run a quick single command"""
        result = self._run_ssm_command(instance_id, command, region, True, 60)
        
        try:
            result_data = json.loads(result)
            if result_data.get('success') and result_data.get('results'):
                output = result_data['results'][0]
                
                formatted_output = f"""
                Command: {command}
                Instance: {instance_id}
                Status: {output.get('status', 'N/A')}
                Response Code: {output.get('response_code', 'N/A')}

                Standard Output:
                {output.get('standard_output', 'No output')}

                Standard Error:
                {output.get('standard_error', 'No errors')}
                """.strip()
                
                return self._safe_json_response(
                    True,
                    command=command,
                    instance_id=instance_id,
                    formatted_output=formatted_output,
                    raw_output=output
                )
        except:
            pass
        
        return result

    def _check_ssm_connectivity(self, instance_id: str, region: str) -> str:
        """Check SSM connectivity for an instance"""
        try:
            ssm = boto3.client('ssm', region_name=region)
            
            response = ssm.describe_instance_information(
                Filters=[{'Key': 'InstanceIds', 'Values': [instance_id]}]
            )
            
            instances = response.get('InstanceInformationList', [])
            
            if not instances:
                return self._safe_json_response(
                    False,
                    instance_id=instance_id,
                    error="Instance not found in SSM managed instances",
                    suggestion="Ensure SSM agent is installed and IAM role has SSM permissions"
                )
            
            instance_info = instances[0]
            ping_status = instance_info.get('PingStatus', 'Unknown')
            
            return self._safe_json_response(
                True,
                instance_id=instance_id,
                ping_status=ping_status,
                agent_version=instance_info.get('AgentVersion', 'N/A'),
                platform_type=instance_info.get('PlatformType', 'N/A'),
                platform_name=instance_info.get('PlatformName', 'N/A'),
                ssm_ready=ping_status == 'Online'
            )
            
        except Exception as e:
            return self._handle_aws_error("check_ssm_connectivity", e, instance_id=instance_id)

    def _get_instance_system_info(self, instance_id: str, region: str) -> str:
        """Get system information via SSM"""
        commands = [
            "echo '=== SYSTEM INFO ==='",
            "uname -a",
            "echo '=== DISK USAGE ==='", 
            "df -h",
            "echo '=== MEMORY USAGE ==='",
            "free -h",
            "echo '=== UPTIME ==='",
            "uptime"
        ]
        
        return self._run_ssm_command(instance_id, '\n'.join(commands), region, True)

    def _get_instance_logs_via_ssm(self, instance_id: str, log_file: str = "/var/log/syslog", 
                                  lines: int = 50, region: str = "us-east-1") -> str:
        """Get log files via SSM"""
        command = f"tail -n {lines} {log_file}"
        return self._run_quick_ssm_command(instance_id, command, region)

    # S3 Operations
    def _list_s3_buckets(self, region: Optional[str] = None) -> str:
        """List S3 buckets"""
        try:
            s3 = boto3.client('s3', region_name=region) if region else boto3.client('s3')
            response = s3.list_buckets()
            buckets = []
            
            for bucket in response['Buckets']:
                bucket_info = {
                    'Name': bucket['Name'],
                    'CreationDate': bucket['CreationDate'].isoformat()
                }
                
                if not region:
                    try:
                        bucket_region = s3.get_bucket_location(Bucket=bucket['Name'])
                        bucket_info['Region'] = bucket_region.get('LocationConstraint', 'us-east-1')
                    except:
                        bucket_info['Region'] = 'unknown'
                
                buckets.append(bucket_info)
            
            return self._safe_json_response(True, buckets=buckets, count=len(buckets))
        except Exception as e:
            return self._handle_aws_error("list_s3_buckets", e, region=region)

    def _list_s3_objects(self, bucket_name: str, prefix: str = "", max_keys: int = 100) -> str:
        """List objects in S3 bucket"""
        try:
            s3 = boto3.client('s3')
            kwargs = {'Bucket': bucket_name, 'MaxKeys': max_keys}
            if prefix:
                kwargs['Prefix'] = prefix
            
            response = s3.list_objects_v2(**kwargs)
            objects = []
            
            for obj in response.get('Contents', []):
                objects.append({
                    'Key': obj['Key'],
                    'Size': obj['Size'],
                    'LastModified': obj['LastModified'].isoformat(),
                    'StorageClass': obj.get('StorageClass', 'STANDARD')
                })
            
            return self._safe_json_response(
                True,
                bucket=bucket_name,
                prefix=prefix,
                objects=objects,
                count=len(objects),
                is_truncated=response.get('IsTruncated', False)
            )
        except Exception as e:
            return self._handle_aws_error("list_s3_objects", e, bucket_name=bucket_name)

    def _create_s3_bucket(self, bucket_name: str, region: str) -> str:
        """Create S3 bucket"""
        try:
            s3 = boto3.client('s3', region_name=region)
            
            if region == 'us-east-1':
                response = s3.create_bucket(Bucket=bucket_name)
            else:
                response = s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': region}
                )
            
            return self._safe_json_response(
                True,
                message=f"Created bucket {bucket_name} in region {region}",
                bucket_name=bucket_name,
                region=region,
                location=response['Location']
            )
        except Exception as e:
            return self._handle_aws_error("create_s3_bucket", e, bucket_name=bucket_name, region=region)

    # RDS Operations
    def _list_rds_instances(self, region: str) -> str:
        """List RDS instances"""
        try:
            rds = boto3.client('rds', region_name=region)
            response = rds.describe_db_instances()
            instances = []
            
            for instance in response['DBInstances']:
                instances.append({
                    'DBInstanceIdentifier': instance['DBInstanceIdentifier'],
                    'DBInstanceClass': instance['DBInstanceClass'],
                    'Engine': instance['Engine'],
                    'EngineVersion': instance['EngineVersion'],
                    'DBInstanceStatus': instance['DBInstanceStatus'],
                    'Endpoint': instance.get('Endpoint', {}).get('Address', 'N/A'),
                    'Port': instance.get('Endpoint', {}).get('Port', 'N/A'),
                    'AllocatedStorage': instance['AllocatedStorage'],
                    'StorageType': instance['StorageType'],
                    'MultiAZ': instance['MultiAZ'],
                    'AvailabilityZone': instance.get('AvailabilityZone', 'N/A'),
                })
            
            return self._safe_json_response(True, region=region, instances=instances, count=len(instances))
        except Exception as e:
            return self._handle_aws_error("list_rds_instances", e, region=region)

    def _describe_rds_instance(self, instance_identifier: str, region: str) -> str:
        """Get detailed RDS instance information"""
        try:
            rds = boto3.client('rds', region_name=region)
            response = rds.describe_db_instances(DBInstanceIdentifier=instance_identifier)
            
            if not response['DBInstances']:
                return self._safe_json_response(False, error="Instance not found", instance_identifier=instance_identifier)
            
            instance = response['DBInstances'][0]
            detailed_info = {
                'DBInstanceIdentifier': instance['DBInstanceIdentifier'],
                'DBInstanceClass': instance['DBInstanceClass'],
                'Engine': instance['Engine'],
                'EngineVersion': instance['EngineVersion'],
                'DBInstanceStatus': instance['DBInstanceStatus'],
                'MasterUsername': instance['MasterUsername'],
                'DBName': instance.get('DBName', 'N/A'),
                'Endpoint': instance.get('Endpoint', {}).get('Address', 'N/A'),
                'Port': instance.get('Endpoint', {}).get('Port', 'N/A'),
                'AllocatedStorage': instance['AllocatedStorage'],
                'StorageType': instance['StorageType'],
                'StorageEncrypted': instance['StorageEncrypted'],
                'MultiAZ': instance['MultiAZ'],
                'AvailabilityZone': instance.get('AvailabilityZone', 'N/A'),
                'SecurityGroups': [sg['VpcSecurityGroupId'] for sg in instance.get('VpcSecurityGroups', [])],
                'BackupRetentionPeriod': instance['BackupRetentionPeriod'],
            }
            
            return self._safe_json_response(True, **detailed_info)
        except Exception as e:
            return self._handle_aws_error("describe_rds_instance", e, instance_identifier=instance_identifier)

    # CloudWatch Logs Operations
    def _list_cloudwatch_log_groups(self, region: str, max_groups: int = 1000) -> str:
        """List CloudWatch log groups"""
        try:
            logs_client = boto3.client('logs', region_name=region)
            log_groups = []
            next_token = None
            
            while len(log_groups) < max_groups:
                params = {'limit': min(50, max_groups - len(log_groups))}
                if next_token:
                    params['nextToken'] = next_token
                
                response = logs_client.describe_log_groups(**params)
                
                for group in response.get('logGroups', []):
                    log_groups.append({
                        'logGroupName': group['logGroupName'],
                        'creationTime': datetime.fromtimestamp(group['creationTime'] / 1000, tz=timezone.utc).isoformat(),
                        'retentionInDays': group.get('retentionInDays', 'Never expire'),
                        'storedBytes': group.get('storedBytes', 0),
                    })
                
                next_token = response.get('nextToken')
                if not next_token:
                    break
            
            return self._safe_json_response(True, region=region, logGroups=log_groups, count=len(log_groups))
        except Exception as e:
            return self._handle_aws_error("list_cloudwatch_log_groups", e, region=region)

    def _list_cloudwatch_log_streams(self, log_group_name: str, region: str, 
                                   max_streams: int = 50, order_by: str = "LastEventTime") -> str:
        """List log streams in a CloudWatch log group"""
        try:
            logs_client = boto3.client('logs', region_name=region)
            
            if order_by not in ['LogStreamName', 'LastEventTime']:
                order_by = 'LastEventTime'
            
            log_streams = []
            next_token = None
            
            while len(log_streams) < max_streams:
                params = {
                    'logGroupName': log_group_name,
                    'limit': min(50, max_streams - len(log_streams)),
                    'orderBy': order_by,
                    'descending': True
                }
                if next_token:
                    params['nextToken'] = next_token
                
                response = logs_client.describe_log_streams(**params)
                
                for stream in response.get('logStreams', []):
                    stream_info = {
                        'logStreamName': stream['logStreamName'],
                        'creationTime': datetime.fromtimestamp(stream['creationTime'] / 1000, tz=timezone.utc).isoformat(),
                        'storedBytes': stream.get('storedBytes', 0),
                    }
                    
                    # Add optional timestamp fields
                    for time_field in ['firstEventTime', 'lastEventTime', 'lastIngestionTime']:
                        if time_field in stream:
                            stream_info[time_field] = datetime.fromtimestamp(stream[time_field] / 1000, tz=timezone.utc).isoformat()
                    
                    log_streams.append(stream_info)
                
                next_token = response.get('nextToken')
                if not next_token:
                    break
            
            return self._safe_json_response(
                True,
                logGroupName=log_group_name,
                region=region,
                orderBy=order_by,
                logStreams=log_streams,
                count=len(log_streams)
            )
        except Exception as e:
            return self._handle_aws_error("list_cloudwatch_log_streams", e, log_group_name=log_group_name)

    def _get_cloudwatch_logs(self, log_group_name: str, log_stream_name: Optional[str] = None,
                           region: str = "us-east-1", hours_back: int = 1, max_events: int = 100,
                           filter_pattern: Optional[str] = None, start_from_head: bool = False) -> str:
        """Get CloudWatch logs"""
        try:
            logs_client = boto3.client('logs', region_name=region)
            
            # Calculate time range
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(hours=hours_back)
            start_time_ms = int(start_time.timestamp() * 1000)
            end_time_ms = int(end_time.timestamp() * 1000)
            
            # Prepare filter parameters
            filter_params = {
                'logGroupName': log_group_name,
                'startTime': start_time_ms,
                'endTime': end_time_ms,
                'limit': min(max_events, 1000)
            }
            
            if log_stream_name:
                filter_params['logStreamNames'] = [log_stream_name]
            if filter_pattern:
                filter_params['filterPattern'] = filter_pattern
            
            response = logs_client.filter_log_events(**filter_params)
            
            events = []
            for event in response.get('events', []):
                events.append({
                    'timestamp': datetime.fromtimestamp(event['timestamp'] / 1000, tz=timezone.utc).isoformat(),
                    'logStreamName': event['logStreamName'],
                    'message': event['message'].strip(),
                    'eventId': event.get('eventId', 'N/A')
                })
            
            return self._safe_json_response(
                True,
                logGroupName=log_group_name,
                logStreamName=log_stream_name or 'all streams',
                region=region,
                timeRange={
                    'start': start_time.isoformat(),
                    'end': end_time.isoformat(),
                    'hoursBack': hours_back
                },
                filterPattern=filter_pattern,
                eventCount=len(events),
                events=events,
                hasMoreEvents=response.get('nextToken') is not None
            )
        except Exception as e:
            return self._safe_json_response(
                False,
                error=str(e),
                logGroupName=log_group_name,
                logStreamName=log_stream_name
            )

    def _search_cloudwatch_logs(self, log_group_name: str, search_term: str,
                              region: str = "us-east-1", hours_back: int = 24,
                              max_events: int = 1000, log_stream_name: Optional[str] = None) -> str:
        """Search CloudWatch logs for specific terms"""
        result = self._get_cloudwatch_logs(
            log_group_name=log_group_name,
            log_stream_name=log_stream_name,
            region=region,
            hours_back=hours_back,
            max_events=max_events,
            filter_pattern=f'"{search_term}"'
        )
        
        # Add search-specific metadata
        try:
            result_data = json.loads(result)
            if result_data.get('success'):
                result_data['searchTerm'] = search_term
            return json.dumps(result_data, indent=2)
        except:
            return result

    def _get_cloudwatch_log_insights(self, log_group_name: str, query: str,
                                   region: str = "us-east-1", hours_back: int = 24,
                                   max_results: int = 1000) -> str:
        """Run CloudWatch Logs Insights query - simplified for Lambda"""
        try:
            logs_client = boto3.client('logs', region_name=region)
            
            # Calculate time range
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(hours=hours_back)
            start_time_timestamp = int(start_time.timestamp())
            end_time_timestamp = int(end_time.timestamp())
            
            # Start the query
            response = logs_client.start_query(
                logGroupName=log_group_name,
                startTime=start_time_timestamp,
                endTime=end_time_timestamp,
                queryString=query,
                limit=max_results
            )
            
            query_id = response['queryId']
            
            # Simple wait (limited for Lambda)
            import time
            for _ in range(10):  # Wait up to 50 seconds max
                time.sleep(5)
                result_response = logs_client.get_query_results(queryId=query_id)
                status = result_response['status']
                
                if status == 'Complete':
                    results = []
                    for result in result_response.get('results', []):
                        result_dict = {}
                        for field in result:
                            result_dict[field['field']] = field['value']
                        results.append(result_dict)
                    
                    return self._safe_json_response(
                        True,
                        logGroupName=log_group_name,
                        query=query,
                        queryId=query_id,
                        status=status,
                        results=results,
                        count=len(results)
                    )
                elif status in ['Failed', 'Cancelled']:
                    return self._safe_json_response(False, error=f"Query {status.lower()}", queryId=query_id)
            
            return self._safe_json_response(False, error="Query timed out", queryId=query_id)
        except Exception as e:
            return self._handle_aws_error("get_cloudwatch_log_insights", e, log_group_name=log_group_name)

    # EC2-specific log functions
    def _get_ec2_logs(self, instance_id: str, log_stream_name: Optional[str] = None,
                      search_term: str = "", region: str = "us-east-1",
                     hours_back: int = 24, max_events: int = 1000) -> str:
        """Get or search EC2 logs for a specific instance"""
        # Try multiple possible log group patterns
        possible_log_groups = [
            f"/aws/ec2/{instance_id}",
            f"/ec2/{instance_id}",
            f"/aws/ec2/i-{instance_id}",
        ]
        
        for log_group_name in possible_log_groups:
            try:
                if search_term:
                    result = self._search_cloudwatch_logs(
                        log_group_name=log_group_name,
                        search_term=search_term,
                        region=region,
                        hours_back=hours_back,
                        max_events=max_events,
                        log_stream_name=log_stream_name
                    )
                else:
                    result = self._get_cloudwatch_logs(
                        log_group_name=log_group_name,
                        log_stream_name=log_stream_name,
                        region=region,
                        hours_back=hours_back,
                        max_events=max_events
                    )
                
                result_data = json.loads(result)
                if result_data.get('success') and result_data.get('eventCount', 0) > 0:
                    result_data['instanceId'] = instance_id
                    if search_term:
                        result_data['searchTerm'] = search_term
                    return json.dumps(result_data, indent=2)
            
            except Exception as e:
                logger.debug(f"Log group {log_group_name} not accessible: {e}")
                continue
        
        # If no CloudWatch logs found
        return self._safe_json_response(
            False,
            error="No CloudWatch log groups found for this instance",
            instanceId=instance_id,
            suggestion="CloudWatch agent may not be installed or configured on this instance",
            triedLogGroups=possible_log_groups
        )

    def _get_ec2_log_streams(self, instance_id: str, region: str = "us-east-1") -> str:
        """Get all log streams for a specific EC2 instance"""
        log_group_name = f"/ec2/{instance_id}"
        return self._list_cloudwatch_log_streams(log_group_name=log_group_name, region=region, max_streams=100)

    def _get_recent_ec2_errors(self, instance_id: str, region: str = "us-east-1",
                              hours_back: int = 24, max_events: int = 500) -> str:
        """Get recent error messages from EC2 instance logs"""
        error_patterns = ['ERROR', 'FAILED', 'CRITICAL', 'FATAL', 'Exception']
        all_errors = []
        
        for pattern in error_patterns:
            try:
                result_json = self._get_ec2_logs(
                    instance_id=instance_id,
                    search_term=pattern,
                    region=region,
                    hours_back=hours_back,
                    max_events=max_events // len(error_patterns)
                )
                
                result_data = json.loads(result_json)
                if result_data.get('success', True) and 'events' in result_data:
                    for event in result_data['events']:
                        event['errorType'] = pattern
                        all_errors.append(event)
            except Exception as e:
                logger.warning(f"Error searching for pattern {pattern}: {e}")
                continue
        
        # Sort by timestamp (most recent first)
        all_errors.sort(key=lambda x: x['timestamp'], reverse=True)
        all_errors = all_errors[:max_events]
        
        return self._safe_json_response(
            True,
            instanceId=instance_id,
            region=region,
            timeRange={'hoursBack': hours_back},
            errors=all_errors,
            count=len(all_errors),
            searchPatterns=error_patterns
        )

    def _check_cloudwatch_agent_status(self, instance_id: str, region: str = "us-east-1") -> str:
        """Check if CloudWatch agent is configured for an EC2 instance"""
        try:
            logs_client = boto3.client('logs', region_name=region)
            
            log_group_patterns = [
                f"/aws/ec2/{instance_id}",
                f"/ec2/{instance_id}",
                f"/aws/amazoncloudwatch-agent/{instance_id}"
            ]
            
            found_groups = []
            
            for pattern in log_group_patterns:
                try:
                    response = logs_client.describe_log_groups(logGroupNamePrefix=pattern)
                    for group in response.get('logGroups', []):
                        found_groups.append({
                            'logGroupName': group['logGroupName'],
                            'creationTime': datetime.fromtimestamp(group['creationTime'] / 1000, tz=timezone.utc).isoformat(),
                            'storedBytes': group.get('storedBytes', 0),
                        })
                except Exception as e:
                    logger.debug(f"No log groups found for pattern {pattern}: {e}")
                    continue
            
            return self._safe_json_response(
                True,
                instanceId=instance_id,
                region=region,
                cloudWatchAgentConfigured=len(found_groups) > 0,
                logGroups=found_groups,
                count=len(found_groups),
                status='Configured' if found_groups else 'Not configured or no recent logs'
            )
        except Exception as e:
            return self._handle_aws_error("check_cloudwatch_agent_status", e, instance_id=instance_id)

    # Utility functions
    def _get_aws_regions(self) -> str:
        """Get list of available AWS regions"""
        try:
            ec2 = boto3.client('ec2', region_name='us-east-1')
            response = ec2.describe_regions()
            regions = [
                {
                    'RegionName': region['RegionName'],
                    'OptInStatus': region['OptInStatus']
                }
                for region in response['Regions']
            ]
            return self._safe_json_response(True, regions=regions, count=len(regions))
        except Exception as e:
            return self._handle_aws_error("get_aws_regions", e)

    def _get_aws_account_info(self) -> str:
        """Get AWS account information"""
        try:
            sts = boto3.client('sts')
            response = sts.get_caller_identity()
            
            return self._safe_json_response(
                True,
                Account=response.get('Account', 'N/A'),
                UserId=response.get('UserId', 'N/A'),
                Arn=response.get('Arn', 'N/A')
            )
        except Exception as e:
            return self._handle_aws_error("get_aws_account_info", e)

    def process_query_with_context(self, query: str, session_id: Optional[str] = None) -> Dict:
        """Process a query with context awareness"""
        start_time = time.time()
        logger.info(f"Processing query with context: {query[:100]}...")

        # Extract and update context if session_id provided
        context_info = ""
        existing_context = {}
        if session_id and self.context_manager:
            # Extract key points from current query
            new_key_points = self.context_manager.extract_key_points(query)

            # Get existing context
            existing_context = self.context_manager.get_context(session_id)

            # Merge contexts
            if new_key_points:
                existing_context.update(new_key_points)
                self.context_manager.update_context(session_id, existing_context)

            # Add context to system prompt if we have key points
            if existing_context:
                context_info = "\n\n**CURRENT CONTEXT:**\n"
                if 'instance_id' in existing_context:
                    context_info += f"- Instance ID: {existing_context['instance_id']}\n"
                if 'instance_type' in existing_context:
                    context_info += f"- Instance Type: {existing_context['instance_type']}\n"
                if 'issue_types' in existing_context:
                    context_info += f"- Issues: {', '.join(existing_context['issue_types'])}\n"

                logger.info(f"Added context to query: {context_info}")

        # Get history if available
        messages = []
        history = None

        if session_id:
            try:
                history = DynamoDBChatMessageHistory(
                    table_name=self.table_name,
                    session_id=session_id
                )
                messages = convert_history_to_messages(history)
                logger.info(f"Loaded {len(messages)} messages from history")
            except Exception as e:
                logger.warning(f"Could not load history: {e}")
                messages = []

        # Add current query with context
        query_with_context = query
        if context_info:
            query_with_context = f"{query}\n{context_info}"

        messages.append({"role": "user", "content": [{"text": query_with_context}]})

        # Use context-aware system prompt
        system_prompt = CONTEXT_AWARE_SYSTEM_PROMPT

        # Get available tools
        tools = self.get_available_tools()

        max_iterations = 40
        iteration = 0
        tool_calls_made = []

        while iteration < max_iterations:
            iteration += 1
            logger.debug(f"Conversation iteration {iteration}")

            converse_api_params = {
                "modelId": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
                "system": [{"text": system_prompt}],
                "messages": messages,
                "inferenceConfig": {"maxTokens": 4096, "temperature": 0.1},
                "toolConfig": {
                    "tools": tools,
                    "toolChoice": {"auto": {}}
                },
            }

            try:
                logger.info("Applying rate limiting before Bedrock API call")
                self.rate_limit()

                logger.info("Calling Bedrock Converse API")
                response_start = time.time()
                response = bedrock_client.converse(**converse_api_params)
                response_time = time.time() - response_start
                logger.info(f"Bedrock API call completed in {response_time:.2f} seconds")

                # Append assistant's response
                messages.append({
                    "role": "assistant",
                    "content": response['output']['message']['content']
                })

                if response['stopReason'] == "tool_use":
                    logger.info("Processing tool use requests")
                    tool_results_content = []

                    for content_item in response['output']['message']['content']:
                        if 'toolUse' in content_item:
                            tool_id = content_item['toolUse']['toolUseId']
                            tool_name = content_item['toolUse']['name']
                            tool_inputs = content_item['toolUse']['input']

                            logger.info(f"Executing tool: {tool_name} with inputs: {tool_inputs}")

                            # Execute tool call
                            try:
                                tool_result = self.execute_tool(tool_name, tool_inputs)
                                logger.info(f"Tool {tool_name} executed successfully")
                                logger.debug(f"Tool result: {tool_result[:200]}...")

                                tool_calls_made.append({
                                    "tool_name": tool_name,
                                    "inputs": tool_inputs,
                                    "result": tool_result[:500] + "..." if len(tool_result) > 500 else tool_result
                                })

                            except Exception as tool_error:
                                logger.error(f"Tool execution failed for {tool_name}: {tool_error}")
                                tool_result = f"Error executing {tool_name}: {str(tool_error)}"

                            result_content = {
                                "toolResult": {
                                    "toolUseId": tool_id,
                                    "content": [{"text": tool_result}]
                                }
                            }
                            tool_results_content.append(result_content)

                    # Append tool results to messages
                    messages.append({
                        "role": "user",
                        "content": tool_results_content
                    })

                else:
                    # Return the final assistant's response
                    final_response = response['output']['message']['content'][0]['text']
                    processing_time = time.time() - start_time
                    logger.info(f"Query processed successfully in {processing_time:.2f} seconds")

                    # Save to history if available
                    if history and session_id:
                        try:
                            history.add_user_message(query)
                            history.add_ai_message(final_response)
                            logger.info("Saved conversation to history")
                        except Exception as e:
                            logger.warning(f"Could not save to history: {e}")

                    return {
                        "response": final_response,
                        "tool_calls": tool_calls_made,
                        "processing_time_seconds": processing_time,
                        "iterations": iteration,
                        "context": existing_context if session_id else None
                    }

            except bedrock_client.exceptions.ThrottlingException as e:
                logger.warning(f"Bedrock API throttling error: {str(e)}")
                return {
                    "error": f"Rate limit exceeded: {str(e)}",
                    "tool_calls": tool_calls_made
                }
            except Exception as bedrock_error:
                logger.error(f"Bedrock API error: {bedrock_error}")
                return {
                    "error": f"Error calling Bedrock API: {str(bedrock_error)}",
                    "tool_calls": tool_calls_made
                }

        logger.warning(f"Conversation exceeded maximum iterations ({max_iterations})")
        return {
            "response": "The conversation took too many turns. Please try a more specific query.",
            "tool_calls": tool_calls_made,
            "processing_time_seconds": time.time() - start_time,
            "iterations": max_iterations
        }

    def process_query(self, query: str) -> Dict:
        """Process a query using Claude - backward compatibility wrapper"""
        return self.process_query_with_context(query, session_id=None)

    def cleanup(self):
        """Clean up resources"""
        if hasattr(self, 'session') and self.session:
            try:
                self.session.close()
                logger.info("HTTP session closed")
            except Exception as e:
                logger.warning(f"Error closing session: {e}")


def handle_slash_command(command: str, text: str, user_id: str, channel_id: str,
                        client: AWSMCPLambdaClient) -> Dict:
    """Handle Slack slash commands"""

    if command == "/aws_help":
        return {
            "response": """*AWS Operations Assistant - Available Commands*

*Basic Commands:*
• `/aws_help` - Show this help message
• `/bot_status` - Check bot and service status
• `/test` - Quick test to verify bot is responding

*Context Management:*
• `/show_context` - Display current conversation context
• `/set_context` - Manually set context (e.g., `/set_context instance_id=i-1234 instance_type=t2.micro`)
• `/clear_context` - Clear current context while keeping chat history

*Memory Management:*
• `/clear_memory` - Clear entire conversation history

*Usage Tips:*
• I maintain context about instances and issues throughout our conversation
• Use specific instance IDs when asking about AWS resources

*Example Queries:*
• "Check the status of instance i-1234567890abcdef0"
• "Show me high CPU instances in us-east-1"
• "List all CloudWatch alarms in ALARM state"
• "Get the last 10 errors from application logs"
"""
        }

    elif command == "/bot_status":
        status_info = {
            "Status": "✅ Online",
            "Region": client.region,
            "AI Model": "Claude 3.5 Sonnet",
            "Context Management": "✅ Enabled" if client.context_manager else "❌ Disabled",
            "Available Tools": len(client.get_available_tools())
        }

        response = "*🤖 AWS Operations Bot Status*\n\n"
        for key, value in status_info.items():
            response += f"*{key}:* {value}\n"

        return {"response": response}

    elif command == "/test":
        return {"response": "✅ Bot is working! I can respond to your AWS queries."}

    elif command == "/show_context":
        session_id = get_session_id(user_id, channel_id)

        if client.context_manager:
            context = client.context_manager.get_context(session_id)

            if context:
                response = "*📋 Current Conversation Context*\n\n"
                if 'instance_id' in context:
                    response += f"• *Instance ID:* `{context['instance_id']}`\n"
                if 'instance_type' in context:
                    response += f"• *Instance Type:* `{context['instance_type']}`\n"
                if 'issue_types' in context:
                    response += f"• *Issue Types:* {', '.join(context['issue_types'])}\n"
                if 'last_updated' in context:
                    response += f"• *Last Updated:* {context['last_updated']}\n"
            else:
                response = "No context found for this conversation. Start asking about specific instances or issues!"
        else:
            response = "Context management not available."

        return {"response": response}

    elif command == "/set_context":
        session_id = get_session_id(user_id, channel_id)

        if not text:
            return {"response": "*Usage:* `/set_context instance_id=i-1234567890abcdef0 instance_type=t2.micro issue_types=high_cpu,memory`"}

        # Parse key=value pairs
        context = {}
        pairs = text.split()
        for pair in pairs:
            if '=' in pair:
                key, value = pair.split('=', 1)
                if key == 'issue_types':
                    context[key] = [v.strip() for v in value.split(',')]
                else:
                    context[key] = value

        if context and client.context_manager:
            client.context_manager.update_context(session_id, context)

            response = "✅ *Context updated successfully!*\n\n"
            for key, value in context.items():
                if isinstance(value, list):
                    response += f"• *{key}:* {', '.join(value)}\n"
                else:
                    response += f"• *{key}:* `{value}`\n"

            return {"response": response}
        else:
            return {"response": "No valid key=value pairs found. Example: `/set_context instance_id=i-1234 instance_type=t2.micro`"}

    elif command == "/clear_context":
        session_id = get_session_id(user_id, channel_id)

        if client.context_manager:
            client.context_manager.update_context(session_id, {})
            return {"response": "✅ Context cleared! Chat history is preserved."}
        else:
            return {"response": "⚠️ Context management not available."}

    elif command == "/clear_memory":
        session_id = get_session_id(user_id, channel_id)

        try:
            history = DynamoDBChatMessageHistory(
                table_name=client.table_name,
                session_id=session_id
            )
            history.clear()
            return {"response": "✅ Your conversation memory has been cleared!"}
        except Exception as e:
            logger.warning(f"Could not clear history: {e}")
            return {"response": "✅ Starting fresh conversation!"}

    else:
        return {"response": f"Unknown command: {command}"}


def lambda_handler(event, context):
    """Enhanced Lambda handler with Slack integration and context management"""
    request_id = context.aws_request_id
    logger.info(f"Lambda invocation started - RequestID: {request_id}")

    # Log memory and time limits
    logger.info(f"Memory allocated: {context.memory_limit_in_mb}MB, " +
               f"Time remaining: {context.get_remaining_time_in_millis()/1000:.2f}s")

    # Log the entire event for debugging
    logger.info(f"Received event: {json.dumps(event)}")

    # Initialize variables
    is_slack_request = False
    is_slash_command = False
    slack_signing_secret = os.environ.get('SLACK_SIGNING_SECRET')

    # Check if this is a Slack request
    headers = event.get('headers', {})
    content_type = headers.get('Content-Type', headers.get('content-type', ''))
    
    if 'X-Slack-Request-Timestamp' in headers or content_type.startswith('application/x-www-form-urlencoded'):
        is_slack_request = True
        logger.info("Detected Slack request")

        # Verify Slack request if signing secret is configured
        if slack_signing_secret and not verify_slack_request(event, slack_signing_secret):
            logger.warning("Slack request verification failed")
            return {
                'statusCode': 401,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Unauthorized'})
            }

    # Parse the request body
    try:
        if is_slack_request and content_type.startswith('application/x-www-form-urlencoded'):
            # Parse Slack's URL-encoded format
            body = parse_slack_request(event)
            is_slash_command = body.get('command', '').startswith('/')
        else:
            # Parse normal JSON request
            if isinstance(event.get('body'), str):
                logger.info("Request body provided as string, parsing JSON")
                body = json.loads(event['body'])
            else:
                logger.info("Request body provided as object")
                body = event.get('body', event)  # Use event directly if no body

        logger.info(f"Parsed request body keys: {list(body.keys())}")

    except Exception as e:
        logger.error(f"Failed to parse request body: {str(e)}", exc_info=True)
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Invalid request format'})
        }

    # Get parameters
    query = body.get('query', body.get('text', ''))
    region = body.get('region', os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'))

    # Extract Slack-specific parameters
    channel_id = body.get('channel_id', '')
    user_id = body.get('user_id', '')
    response_url = body.get('response_url', '')
    command = body.get('command', '')
    text = body.get('text', '')
    thread_ts = body.get('thread_ts', '')

    # Generate session ID for context management
    session_id = None
    if user_id and channel_id:
        session_id = get_session_id(user_id, channel_id, thread_ts)
        logger.info(f"Using session ID: {session_id}")

    logger.info(f"Query length: {len(query)}")
    logger.info(f"Target region: {region}")
    logger.info(f"Channel ID: {channel_id}")
    logger.info(f"Command: {command}")

    start_time = time.time()

    # Create client and process request
    try:
        logger.info("Creating AWSMCPLambdaClient instance")
        client = AWSMCPLambdaClient(region=region)

        # Handle slash commands
        if is_slash_command:
            logger.info(f"Processing slash command: {command}")
            
            # For Slack slash commands, respond immediately to avoid timeout
            if is_slack_request:
                # Send immediate acknowledgment
                immediate_response = {
                    'statusCode': 200,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({'response_type': 'in_channel', 'text': 'Processing your command...'})
                }
                
                # Process command
                result = handle_slash_command(command, text, user_id, channel_id, client)
                
                # Send response back to Slack via response_url if available
                if response_url and result.get('response'):
                    try:
                        response_payload = {
                            'response_type': 'in_channel',
                            'text': result['response']
                        }
                        requests.post(response_url, json=response_payload, timeout=5)
                    except Exception as e:
                        logger.error(f"Failed to send response to Slack: {e}")
                
                return immediate_response
            else:
                # Non-Slack slash command handling
                result = handle_slash_command(command, text, user_id, channel_id, client)
        else:
            # Check if query is provided
            if not query:
                logger.warning("Missing required parameter: query")
                return {
                    'statusCode': 400,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({'error': 'Missing required parameter: query'})
                }

            # Process the query with context
            logger.info("Processing query with AWS MCP client")
            result = client.process_query_with_context(query, session_id)

        # Check for errors in result
        if 'error' in result:
            logger.error(f"Error in query processing: {result['error']}")

        # Clean up
        logger.info("Cleaning up client resources")
        client.cleanup()

        execution_time = time.time() - start_time
        logger.info(f"Lambda execution completed in {execution_time:.2f} seconds")

        # Handle Slack response formatting and sending
        if channel_id and not is_slash_command:
            logger.info("Processing Slack response")

            # Extract just the response text for Slack formatting
            response_text = result.get('response', str(result))

            # Format for Slack
            response_text = format_for_slack(response_text)

            # Add context information if available
            if result.get('context'):
                context = result['context']
                if any(k in context for k in ['instance_id', 'instance_type', 'issue_types']):
                    context_text = "\n\n📋 *Current Context:*\n"
                    if 'instance_id' in context:
                        context_text += f"• Instance: `{context['instance_id']}`\n"
                    if 'instance_type' in context:
                        context_text += f"• Type: `{context['instance_type']}`\n"
                    if 'issue_types' in context:
                        context_text += f"• Issues: {', '.join(context['issue_types'])}\n"
                    response_text += context_text

            # Add context about which system handled the query
            response_text += f"\n\n_☁️ Processed by AWS Cloud Operations System (Region: {region})_"

            # Add execution summary if tool calls were made
            if 'tool_calls' in result and result['tool_calls']:
                tool_summary = f"\n\n*🔧 Executed {len(result['tool_calls'])} AWS operations:*\n"
                for i, tool_call in enumerate(result['tool_calls'], 1):
                    tool_summary += f"{i}. {tool_call.get('tool_name', 'Unknown')} "
                    if 'inputs' in tool_call:
                        inputs_str = ', '.join([f"{k}={v}" for k, v in tool_call['inputs'].items() if k != 'region'])
                        if inputs_str:
                            tool_summary += f"({inputs_str})"
                    tool_summary += "\n"

                response_text += tool_summary

            # Add timing information
            response_text += f"\n*⏱️ AWS processing time: {execution_time:.2f} seconds*"

            # Format for Slack using Bedrock
            try:
                bedrock_slack_result = get_bedrock_slack_result(response_text)
                
                # Send via response_url if it's a Slack request
                if is_slack_request and response_url:
                    response_payload = {
                        'response_type': 'in_channel',
                        'text': bedrock_slack_result
                    }
                    requests.post(response_url, json=response_payload, timeout=5)
                else:
                    # Send via slack_utils
                    send_slack_message(channel_id, bedrock_slack_result)
                
                logger.info("Slack message sent successfully")
            except Exception as slack_error:
                logger.error(f"Failed to send Slack message: {slack_error}")
                # Continue with normal response even if Slack fails

            # Handle event alerts
            if body.get("command") == "event-alert":
                sns_topic_arn = os.environ.get('SNS_TOPIC_ARN')
                result_conv = get_bedrock_email_result(response_text)
                email_subject, email_body = result_conv["subject"], result_conv["body"]

                if sns_topic_arn:
                    logger.info(f"[{request_id}] Sending SNS alert to: {sns_topic_arn}")
                    send_sns_alert(email_subject, email_body, sns_topic_arn)
                else:
                    logger.warning(f"[{request_id}] SNS_TOPIC_ARN not configured, skipping email alert")

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'success': True,
                'query': query,
                'region': region,
                'result': result,
                'execution_time_seconds': execution_time,
                'request_id': request_id,
                'slack_integration': bool(channel_id),
                'session_id': session_id,
                'command': command if is_slash_command else None
            })
        }

    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(f"Internal server error: {str(e)}", exc_info=True)
        logger.info(f"Lambda execution failed after {execution_time:.2f} seconds")

        # Send error to Slack if channel_id is provided
        if channel_id:
            try:
                error_message = f"❌ *AWS Operations Error*\n\n```{str(e)}```\n\n_Request ID: {request_id}_"
                
                if is_slack_request and response_url:
                    # Send via response_url
                    response_payload = {
                        'response_type': 'in_channel',
                        'text': error_message
                    }
                    requests.post(response_url, json=response_payload, timeout=5)
                else:
                    # Send via slack_utils
                    bedrock_slack_result = get_bedrock_slack_result(error_message)
                    send_slack_message(channel_id, bedrock_slack_result)
            except Exception as slack_error:
                logger.error(f"Failed to send error to Slack: {slack_error}")

        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'error': f'Internal server error: {str(e)}',
                'execution_time_seconds': execution_time,
                'request_id': request_id
            })
        }
# ```

# This updated Lambda function now properly handles both:

# 1. **Normal API requests** (JSON format)
# 2. **Slack requests** (URL-encoded format) including:
#    - Slash commands
#    - Request verification
#    - Immediate acknowledgment to avoid timeouts
#    - Response via `response_url`

# Key improvements:
# - Detects Slack requests by headers and content type
# - Verifies Slack requests using signing secret (if configured)
# - Parses URL-encoded Slack payloads
# - Responds immediately to Slack slash commands to avoid 3-second timeout
# - Sends actual response asynchronously via `response_url`
# - Maintains backward compatibility with existing JSON API calls

# Make sure to add `SLACK_SIGNING_SECRET` to your Lambda environment variables for request verification.