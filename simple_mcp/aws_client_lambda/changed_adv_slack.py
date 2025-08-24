# # Complete AWS MCP Lambda Code for Slack Integration

# ```python
import json
import os
import time
import logging
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
import re
import threading
from collections import OrderedDict

from tool.patch_manager import PatchManager
from tool.ssm_commands import SSMCommandManager
from tool.diagnostics import DiagnosticManager

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
# Context-aware system prompt with Slack formatting
CONTEXT_AWARE_SYSTEM_PROMPT = """You are an expert AWS Operations Assistant with comprehensive access to AWS management tools and context awareness capabilities.

**CRITICAL: SLACK FORMATTING REQUIREMENTS**
You MUST format ALL responses using Slack markdown syntax:
• Use *bold text* for headers and important information (NOT **double asterisks**)
• Use `inline code` for instance IDs, commands, technical terms
• Use ```code blocks``` for multi-line outputs
• Use • for bullet points (never -, *, or raw numbers for lists)
• Use :emoji_name: for visual indicators:
  - :white_check_mark: for success/healthy
  - :warning: for warnings
  - :x: or :red_circle: for errors/stopped
  - :green_circle: for running/online
  - :chart_with_upwards_trend: for metrics
  - :bulb: for recommendations
  - :mag: for findings
  - :arrow_right: for next steps
  - :clipboard: for summaries
  - :gear: for configuration
  - :information_source: for info
  - :zap: for performance
  - :lock: for security
  - :heart: for health status
  - :package: for patches/updates
  - :rocket: for deployments
  - :rotating_light: for critical alerts
  - :wrench: for maintenance

**REQUIRED RESPONSE STRUCTURE for all status checks:**

:clipboard: *Status Summary*
[One-line overview with appropriate emoji]

:mag: *Current Status*
• *Instance State:* `value` :green_circle:/:red_circle:
• *Instance Type:* `value`
• *Availability Zone:* `value`
• *Key Metrics:* Brief summary

:chart_with_upwards_trend: *Key Findings*
• Specific finding with data point
• Performance observation with numbers
• Configuration detail worth noting

:bulb: *Recommendations*
• Specific actionable recommendation 1
• Specific actionable recommendation 2
• Optimization suggestion even if healthy

:arrow_right: *Next Steps*
• Immediate action to take
• Monitoring suggestion
• Follow-up check

**FORMATTING RULES:**
1. ALWAYS use single asterisks (*) for bold, NEVER double (**)
2. ALWAYS put instance IDs in backticks: `i-1234567890abcdef0`
3. ALWAYS put instance types in backticks: `t2.micro`
4. ALWAYS use emojis for visual hierarchy
5. ALWAYS include Recommendations section even for healthy resources
6. NEVER use headers like # or ##, use *Bold Text* instead
7. NEVER use raw markdown, only Slack-compatible formatting
8. Format instance states with emojis: running :green_circle:, stopped :red_circle:

**CONTEXT MANAGEMENT RULES:**
1. Always maintain awareness of key information throughout the conversation:
   - Instance IDs (format: i-xxxxxxxxx)
   - Instance Types (e.g., t2.micro, m5.large)
   - Issue Types (e.g., high CPU, memory issues, disk space, network problems)
   - Alert IDs (format: alert_channel_instanceid)
   - Maintenance Window IDs
   - Patch compliance states
   - Any specific metrics or thresholds mentioned

2. When key information is identified, acknowledge it and refer back to it in subsequent responses.

3. If context from previous messages is relevant, include it in your analysis.

4. When referencing alerts or previous issues, use the alert ID for tracking.

**Core AWS Services:**
- **EC2 Management**: List, start, stop instances, retrieve detailed instance information, and find instances by name
- **SSM Operations**: Execute commands remotely on EC2 instances, check connectivity, get system information
- **S3 Operations**: Manage buckets, list objects, create new buckets with proper regional configuration
- **RDS Database Management**: Monitor instances, retrieve detailed database configurations and status
- **Account & Regional Information**: Provide AWS account details and available regions

**SSM Patching & Maintenance Window Operations:**
- **Maintenance Window Management**: Get execution details, monitor window status, analyze success/failure rates
- **Patch Compliance Monitoring**: Check patch compliance across instances, identify non-compliant systems
- **Patch Operation Analysis**: Get detailed patch installation results, identify failed patches
- **Automated Patch Verification**: Process maintenance window completion events and generate reports
- **Compliance Reporting**: Generate comprehensive patch compliance summaries by environment
- **Patch Remediation**: Identify instances needing patches or reboots, provide remediation commands

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

**Alert & Event Processing:**
- **External Alert Integration**: Process alerts from external monitoring systems
- **Disk Space Alerts**: Analyze and respond to disk usage warnings
- **Performance Alerts**: Investigate CPU, memory, and network alerts
- **Alert Context Storage**: Maintain context for alerts to enable follow-up investigations
- **Alert History Tracking**: Reference previous alerts using alert IDs

**Enhanced Patch Reporting Format:**
When reporting on patches, provide comprehensive details:

:package: *Patch Execution Summary*
• *Window Name:* [name]
• *Execution Status:* [status] :white_check_mark:/:x:
• *Duration:* [time]
• *Total Instances:* [count]

:chart_with_upwards_trend: *Compliance Metrics*
*By Environment:*
• *Production:* [X/Y compliant] ([percentage]%)
• *Staging:* [X/Y compliant] ([percentage]%)
• *Development:* [X/Y compliant] ([percentage]%)

:package: *Package Updates* (Top 10)
• `package-name` - [version] on [X] instances
• Include security classification

:rocket: *Application Updates*
• `app-name`: [old-version] → [new-version]
• Affected instances: [list]

:warning: *Failed Patches*
• `instance-id` (`name`):
  - Package: [name]
  - Error: [specific error]
  - Remediation: [specific command]

:rotating_light: *Instances Requiring Reboot*
• `instance-id` (`name`): [X] patches pending
• Recommended reboot window: [time]

:clipboard: *Detailed Instance Results*
Group by environment and show:
• Instance ID, Name, Status
• Patches installed/failed/pending
• Compliance state

:wrench: *Remediation Plan*
1. *Immediate Actions:*
   • Command to run: `[specific SSM command]`
   • Instances affected: [list]
2. *Scheduled Actions:*
   • Next maintenance window: [datetime]
   • Expected duration: [time]

:bulb: *Recommendations*
• Baseline adjustments needed
• Recurring failure patterns
• Process improvements

**Best Practices:**
- Always specify the AWS region when working with resources (default: us-east-1)
- When investigating performance issues, check both metrics and alarms
- For health checks, combine instance state, metrics, alarms, and logs for comprehensive assessment
- Use appropriate time ranges for metric analysis based on the investigation scope
- Provide context about alarm thresholds and what metric values mean
- When troubleshooting, start with alarms in ALARM state, then check metrics and logs
- For patch reports, always include environment grouping and actionable remediation steps
- Reference alert IDs when discussing previous issues for continuity

**Response Guidelines:**
- Format everything for Slack in your response - no post-processing will be done
- Provide clear, actionable responses with specific commands and recommendations
- Always use the appropriate tools for each request
- When showing metrics, explain what the values indicate about system health
- Highlight critical issues with appropriate emojis and formatting
- Explain AWS-specific terminology and concepts when relevant
- Always include recommendations, even for healthy resources (optimization opportunities)
- For patching issues, provide specific remediation commands
- Include alert IDs and session IDs for tracking and follow-up

Remember: Your response will be sent DIRECTLY to Slack without any modification, so ensure perfect Slack formatting."""



class ConversationContext:
    """Manages persistent context across conversations"""

    def __init__(self, dynamodb_resource, table_name):
        self.dynamodb = dynamodb_resource
        self.context_table_name = os.environ.get('DYNAMODB_TABLE_NAME_CONTEXT', f"{table_name}_context")
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


def detect_event_source(event):
    """Detect the source of the event"""
    logger.info(f"Detecting event source for: {json.dumps(event)[:500]}...")

    # Slack events
    headers = event.get('headers', {})
    if 'X-Slack-Signature' in headers:
        return 'slack'

    # EventBridge/CloudWatch Events
    if 'source' in event and 'detail-type' in event:
        return 'eventbridge'

    # SNS events
    if 'Records' in event and event.get('Records', [{}])[0].get('EventSource') == 'aws:sns':
        return 'sns'

    # CloudWatch Alarms (via SNS)
    if 'Records' in event:
        sns_message = event.get('Records', [{}])[0].get('Sns', {}).get('Message', '')
        if 'AlarmName' in sns_message:
            return 'cloudwatch-alarm'

    # S3 events
    if 'Records' in event and event.get('Records', [{}])[0].get('eventSource') == 'aws:s3':
        return 's3'

    # API Gateway/Direct call
    if 'body' in event and 'httpMethod' in event:
        return 'api-gateway'

    # Direct invocation
    if 'query' in event:
        return 'direct'

    return 'unknown'


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


def send_slack_message_with_thread(channel, text, thread_ts=None):
    """Send Slack message directly without any formatting"""
    try:
        slack_token = os.environ.get('SLACK_BOT_TOKEN')

        if slack_token:
            url = "https://slack.com/api/chat.postMessage"
            headers = {
                "Authorization": f"Bearer {slack_token}",
                "Content-Type": "application/json"
            }

            data = {
                "channel": channel,
                "text": text,  # Send exactly what Claude gave us
                "unfurl_links": False,
                "unfurl_media": False
            }

            if thread_ts:
                data["thread_ts"] = thread_ts

            # Send with retries
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = requests.post(url, headers=headers, json=data, timeout=10)
                    response_data = response.json()

                    if response_data.get('ok'):
                        logger.info("Message sent successfully via Slack API")
                        return True
                    else:
                        logger.error(f"Slack API error: {response_data.get('error')}")
                        if attempt < max_retries - 1:
                            time.sleep(1)
                        
                except requests.exceptions.Timeout:
                    logger.warning(f"Slack API timeout on attempt {attempt + 1}")
                    if attempt < max_retries - 1:
                        time.sleep(1)
                except Exception as e:
                    logger.error(f"Error sending to Slack on attempt {attempt + 1}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(1)
        else:
            # Fallback
            send_slack_message(channel, text)

    except Exception as e:
        logger.error(f"Failed to send Slack message: {e}")
        return False

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


# ================================================
# AWS MCP Lambda Client
# ================================================
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

        # Ensure the main conversation history table exists
        self._ensure_conversation_table()

        # Initialize context manager
        try:
            self.context_manager = ConversationContext(self.dynamodb, self.table_name)
            
            logger.info("Context manager initialized")
        except Exception as e:
            logger.warning(f"Context manager initialization failed: {e}")
            self.context_manager = None

        logger.info(f"AWSMCPLambdaClient initialized for region: {region}")

    def _ensure_conversation_table(self):
        """Ensure the main conversation history table exists"""
        try:
            # Check if table exists
            table = self.dynamodb.Table(self.table_name)
            
            table.load()
            logger.info(f"Conversation table '{self.table_name}' already exists")
        except self.dynamodb.meta.client.exceptions.ResourceNotFoundException:
            # Table doesn't exist, create it
            try:
                logger.info(f"Creating conversation table: {self.table_name}")
                table = self.dynamodb.create_table(
                    TableName=self.table_name,
                    KeySchema=[
                        {
                            'AttributeName': 'SessionId',
                            'KeyType': 'HASH'
                        }
                    ],
                    AttributeDefinitions=[
                        {
                            'AttributeName': 'SessionId',
                            'AttributeType': 'S'
                        }
                    ],
                    BillingMode='PAY_PER_REQUEST'
                )
                
                # Wait for table to be created
                logger.info(f"Waiting for table '{self.table_name}' to be created...")
                table.wait_until_exists()
                logger.info(f"Conversation table '{self.table_name}' created successfully")
                
            except Exception as e:
                logger.error(f"Error creating conversation table: {e}")
                raise
        except Exception as e:
            logger.error(f"Error checking conversation table existence: {e}")

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


    def get_patch_report_using_manager(self, window_id: str, region: str = "us-east-1") -> str:
        """Get patch report using PatchManager methods"""
        try:
            # Initialize PatchManager if needed
            if not hasattr(self, 'patch_manager'):
                self.patch_manager = PatchManager(region)
            
            report = {
                'windowId': window_id,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            # Get maintenance window details
            window_details = self.patch_manager.get_maintenance_windows(window_id)
            report['windowDetails'] = window_details
            
            # Get all instance IDs from the window execution
            instance_ids = []  # Extract from window_details
            
            # Get current patch status
            if instance_ids:
                patch_status = self.patch_manager.check_patch_status(instance_ids)
                report['patchStatus'] = patch_status
                
                # Get patch history for recent changes
                patch_history = self.patch_manager.get_patch_history(instance_ids, days_back=1)
                report['recentPatches'] = patch_history
                
                # Diagnose any failures
                diagnostics = self.diagnostic_manager.diagnose_patch_failures(instance_ids)
                report['diagnostics'] = diagnostics
            
            return json.dumps(report, indent=2, default=str)
            
        except Exception as e:
            return self._handle_aws_error("get_patch_report_using_manager", e, window_id=window_id)
    def get_available_tools(self) -> List[Dict]:
        """Return the list of available AWS tools"""
        with open('lambda_config.json', 'r') as f:
            tools = json.load(f)
        return tools

    def execute_tool(self, tool_name: str, tool_inputs: Dict) -> str:
        """Execute a tool call with enhanced error handling and AWS API calls"""
        try:
            logger.info(f"Executing tool: {tool_name} with inputs: {tool_inputs}")
    
            # Set default region
            region = tool_inputs.get('region', self.region)
            # Initialize managers if not already done
            if not hasattr(self, 'patch_manager'):
                self.patch_manager = PatchManager(region)
                self.diagnostic_manager = DiagnosticManager(region)
                self.ssm_command_manager = SSMCommandManager(region)


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
            elif tool_name == "get_window_execution_details":
                # New method for detailed execution results
                return json.dumps(self.patch_manager.get_window_execution_details(
                    tool_inputs['window_id'],
                    tool_inputs.get('execution_id')
                ))
            elif tool_name == "get_instances_needing_patches":
                # New method for finding instances needing action
                return json.dumps(self.patch_manager.get_instances_needing_patches())

            

            # =====================
            # SSM PATCHING OPERATIONS (ADD THIS SECTION)
            # =====================
            elif tool_name == "get_maintenance_window_executions":
                return self._get_maintenance_window_executions(
                    tool_inputs.get('window_id'),
                    tool_inputs.get('hours_back', 24),
                    region
                )
            elif tool_name == "get_patch_compliance_summary":
                return self._get_patch_compliance_summary(
                    tool_inputs.get('instance_ids'),
                    region
                )
            elif tool_name == "get_patch_operation_results":
                return self._get_patch_operation_results(
                    tool_inputs['instance_id'],
                    tool_inputs.get('operation_id'),
                    region
                )
            # =====================
            # PATCH MANAGEMENT TOOLS
            # =====================

            elif tool_name == "check_patch_status":
                instance_ids = tool_inputs.get('instance_ids', [])
                if isinstance(instance_ids, str):
                    instance_ids = [id.strip() for id in instance_ids.split(',')]
                return json.dumps(self.patch_manager.check_patch_status(instance_ids))

            elif tool_name == "apply_patches":
                instance_ids = tool_inputs.get('instance_ids', [])
                if isinstance(instance_ids, str):
                    instance_ids = [id.strip() for id in instance_ids.split(',')]
                return json.dumps(self.patch_manager.apply_patches(
                    instance_ids,
                    tool_inputs.get('operation', 'Install'),
                    tool_inputs.get('reboot_option', 'RebootIfNeeded'),
                    tool_inputs.get('baseline_id')
                ))

            elif tool_name == "get_patch_history":
                instance_ids = tool_inputs.get('instance_ids', [])
                if isinstance(instance_ids, str):
                    instance_ids = [id.strip() for id in instance_ids.split(',')]
                return json.dumps(self.patch_manager.get_patch_history(
                    instance_ids,
                    tool_inputs.get('days_back', 30)
                ))

            elif tool_name == "get_maintenance_windows_detailed":
                # Note: method name in PatchManager is get_maintenance_windows
                return json.dumps(self.patch_manager.get_maintenance_windows(
                    tool_inputs.get('window_id')
                ))

            # =====================
            # DIAGNOSTIC TOOLS
            # =====================

            elif tool_name == "diagnose_patch_failures":
                instance_ids = tool_inputs.get('instance_ids', [])
                if isinstance(instance_ids, str):
                    instance_ids = [id.strip() for id in instance_ids.split(',')]
                return json.dumps(self.diagnostic_manager.diagnose_patch_failures(instance_ids))

            elif tool_name == "collect_system_info":
                instance_ids = tool_inputs.get('instance_ids', [])
                if isinstance(instance_ids, str):
                    instance_ids = [id.strip() for id in instance_ids.split(',')]
                return json.dumps(self.diagnostic_manager.collect_system_info(instance_ids))

            elif tool_name == "analyze_patch_logs":
                instance_ids = tool_inputs.get('instance_ids', [])
                if isinstance(instance_ids, str):
                    instance_ids = [id.strip() for id in instance_ids.split(',')]
                return json.dumps(self.diagnostic_manager.analyze_logs(
                    instance_ids,
                    tool_inputs.get('log_type', 'patch'),
                    tool_inputs.get('hours_back', 24)
                ))

            elif tool_name == "repair_common_issues":
                instance_ids = tool_inputs.get('instance_ids', [])
                if isinstance(instance_ids, str):
                    instance_ids = [id.strip() for id in instance_ids.split(',')]
                return json.dumps(self.diagnostic_manager.repair_common_issues(
                    instance_ids,
                    tool_inputs.get('issue_type', 'auto')
                ))

            # =====================
            # SSM COMMAND TOOLS
            # =====================

            elif tool_name == "execute_ssm_command":
                instance_ids = tool_inputs.get('instance_ids', [])
                if isinstance(instance_ids, str):
                    instance_ids = [id.strip() for id in instance_ids.split(',')]
                return json.dumps(self.ssm_command_manager.execute_command(
                    instance_ids,
                    tool_inputs['document_name'],
                    tool_inputs['parameters'],
                    tool_inputs.get('comment')
                ))

            elif tool_name == "get_command_status":
                return json.dumps(self.ssm_command_manager.get_command_status(
                    tool_inputs['command_id']
                ))

            elif tool_name == "list_recent_commands":
                return json.dumps(self.ssm_command_manager.list_recent_commands(
                    tool_inputs.get('days_back', 7),
                    tool_inputs.get('instance_id')
                ))

            elif tool_name == "cancel_command":
                return json.dumps(self.ssm_command_manager.cancel_command(
                    tool_inputs['command_id'],
                    tool_inputs.get('instance_ids')
                ))

            elif tool_name == "get_command_output":
                return json.dumps(self.ssm_command_manager.get_command_output(
                    tool_inputs['command_id'],
                    tool_inputs['instance_id']
                ))

            elif tool_name == "run_shell_command":
                instance_ids = tool_inputs.get('instance_ids', [])
                if isinstance(instance_ids, str):
                    instance_ids = [id.strip() for id in instance_ids.split(',')]
                commands = tool_inputs.get('commands', [])
                if isinstance(commands, str):
                    commands = [commands]
                return json.dumps(self.ssm_command_manager.run_shell_command(
                    instance_ids,
                    commands,
                    tool_inputs.get('working_directory', '/tmp'),
                    tool_inputs.get('timeout_seconds', 1800)
                ))
            # =====================
            # SSM PATCHING OPERATIONS
            # =====================
            elif tool_name == "get_maintenance_window_executions":
                return self._get_maintenance_window_executions(
                    tool_inputs.get('window_id'),
                    tool_inputs.get('hours_back', 24),
                    region
                )
            elif tool_name == "get_patch_compliance_summary":
                return self._get_patch_compliance_summary(
                    tool_inputs.get('instance_ids'),
                    region
                )
            elif tool_name == "get_patch_operation_results":
                return self._get_patch_operation_results(
                    tool_inputs['instance_id'],
                    tool_inputs.get('operation_id'),
                    region
                )
            # In the execute_tool method, add:

            elif tool_name == "get_detailed_maintenance_window_report":
                return self._get_detailed_maintenance_window_report(
                    tool_inputs['window_id'],
                    tool_inputs.get('execution_id'),
                    region
                )
            elif tool_name == "get_patch_baseline_compliance":
                return self._get_patch_baseline_compliance(
                    tool_inputs.get('baseline_id'),
                    region
                )
            elif tool_name == "generate_patch_remediation_plan":
                return self._generate_patch_remediation_plan(
                    tool_inputs['instance_ids'],
                    region
                )

            
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
            if '\\n' in commands:
                command_list = [cmd.strip() for cmd in commands.split('\\n') if cmd.strip()]
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

        return self._run_ssm_command(instance_id, '\\n'.join(commands), region, True)

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
                context_info = "\\n\\n**CURRENT CONTEXT:**\\n"
                if 'instance_id' in existing_context:
                    context_info += f"- Instance ID: {existing_context['instance_id']}\\n"
                if 'instance_type' in existing_context:
                    context_info += f"- Instance Type: {existing_context['instance_type']}\\n"
                if 'issue_types' in existing_context:
                    context_info += f"- Issues: {', '.join(existing_context['issue_types'])}\\n"

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
            query_with_context = f"{query}\\n{context_info}"

        messages.append({"role": "user", "content": [{"text": query_with_context}]})

        # Use context-aware system prompt
        system_prompt = CONTEXT_AWARE_SYSTEM_PROMPT

        # Get available tools
        tools = self.get_available_tools()
        logger.debug(f"Loaded {len(tools)} tools. First tool has keys: {tools[0].keys() if tools else 'No tools'}")
        
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

    # [Include all the tool implementation methods here: _list_ec2_instances, _get_ec2_instance_details, etc.]
    # I'm not repeating them all as they remain the same from your original code
    # Just copy all the methods starting with underscore from your original code here

    # =====================
    # SSM PATCHING OPERATIONS
    # =====================

    def _get_maintenance_window_executions(self, window_id: Optional[str] = None, 
                                        hours_back: int = 24, region: str = "us-east-1") -> str:
        """Get recent Maintenance Window executions"""
        try:
            ssm = boto3.client('ssm', region_name=region)
            
            # Calculate time range
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(hours=hours_back)
            
            # Get maintenance windows
            windows = []
            if window_id:
                windows = [window_id]
            else:
                # Get all maintenance windows
                mw_response = ssm.describe_maintenance_windows(
                    Filters=[{'Key': 'Enabled', 'Values': ['true']}]
                )
                windows = [w['WindowId'] for w in mw_response.get('WindowIdentities', [])]
            
            all_executions = []
            
            for win_id in windows:
                try:
                    # Get window details
                    win_details = ssm.get_maintenance_window(WindowId=win_id)
                    
                    # Get executions for this window
                    exec_response = ssm.describe_maintenance_window_executions(
                        WindowId=win_id,
                        Filters=[
                            {
                                'Key': 'ExecutedAfter',
                                'Values': [start_time.isoformat()]
                            }
                        ]
                    )
                    
                    for execution in exec_response.get('WindowExecutions', []):
                        exec_id = execution['WindowExecutionId']
                        
                        # Get task executions for this window execution
                        task_response = ssm.describe_maintenance_window_execution_tasks(
                            WindowExecutionId=exec_id
                        )
                        
                        # Get target executions for detailed results
                        instance_results = []
                        for task in task_response.get('WindowExecutionTaskIdentities', []):
                            task_exec_id = task['TaskExecutionId']
                            
                            target_response = ssm.describe_maintenance_window_execution_task_invocations(
                                WindowExecutionId=exec_id,
                                TaskId=task_exec_id
                            )
                            
                            for invocation in target_response.get('WindowExecutionTaskInvocationIdentities', []):
                                instance_results.append({
                                    'InstanceId': invocation.get('Parameters', {}).get('InstanceIds', ['Unknown'])[0],
                                    'Status': invocation['Status'],
                                    'StatusDetails': invocation.get('StatusDetails', ''),
                                    'StartTime': invocation.get('StartTime', '').isoformat() if invocation.get('StartTime') else 'N/A',
                                    'EndTime': invocation.get('EndTime', '').isoformat() if invocation.get('EndTime') else 'N/A'
                                })
                        
                        execution_info = {
                            'WindowId': win_id,
                            'WindowName': win_details.get('Name', 'N/A'),
                            'ExecutionId': exec_id,
                            'Status': execution['Status'],
                            'StartTime': execution.get('StartTime', '').isoformat() if execution.get('StartTime') else 'N/A',
                            'EndTime': execution.get('EndTime', '').isoformat() if execution.get('EndTime') else 'N/A',
                            'InstanceResults': instance_results,
                            'SuccessCount': len([r for r in instance_results if r['Status'] == 'SUCCESS']),
                            'FailureCount': len([r for r in instance_results if r['Status'] in ['FAILED', 'TIMED_OUT']]),
                            'TotalInstances': len(instance_results)
                        }
                        
                        all_executions.append(execution_info)
                        
                except Exception as e:
                    logger.error(f"Error getting executions for window {win_id}: {e}")
                    continue
            
            # Sort by start time (most recent first)
            all_executions.sort(key=lambda x: x['StartTime'], reverse=True)
            
            return self._safe_json_response(
                True,
                region=region,
                timeRange={'hoursBack': hours_back},
                executions=all_executions,
                count=len(all_executions)
            )
        except Exception as e:
            return self._handle_aws_error("get_maintenance_window_executions", e, region=region)

   
    def _get_patch_compliance_summary(self, instance_ids: Optional[str] = None, region: str = "us-east-1") -> str:
        """Get patch compliance summary for instances"""
        try:
            ssm = boto3.client('ssm', region_name=region)
            
            # Build parameters for list_compliance_items
            params = {
                'ResourceTypes': ['ManagedInstance']
            }
            
            # Add filters for ComplianceType
            params['Filters'] = [
                {
                    'Key': 'ComplianceType',
                    'Values': ['Patch'],
                    'Type': 'EQUAL'
                }
            ]
            
            # Add instance IDs if provided
            if instance_ids:
                instance_list = [id.strip() for id in instance_ids.split(',')]
                params['ResourceIds'] = instance_list
            
            # Get compliance summary
            response = ssm.list_compliance_items(**params)
            
            compliance_summary = {}
            
            for item in response.get('ComplianceItems', []):
                instance_id = item['ResourceId']
                
                if instance_id not in compliance_summary:
                    compliance_summary[instance_id] = {
                        'InstanceId': instance_id,
                        'ComplianceType': item['ComplianceType'],
                        'Severity': item.get('Severity', 'UNSPECIFIED'),
                        'Status': item['Status'],
                        'InstalledPatches': 0,
                        'InstalledPendingRebootPatches': 0,
                        'MissingPatches': 0,
                        'FailedPatches': 0,
                        'NotApplicablePatches': 0,
                        'Details': {}
                    }
                
                # Parse details
                details = item.get('Details', {})
                
                # The Details field contains patch summary information
                if details:
                    for key, value in details.items():
                        compliance_summary[instance_id]['Details'][key] = value
            
            # Get more detailed patch state information
            if compliance_summary or instance_ids:
                # Get instance patch states for more detailed info
                try:
                    if instance_ids:
                        patch_states_response = ssm.describe_instance_patch_states(
                            InstanceIds=instance_list
                        )
                    else:
                        # Get all instance patch states
                        patch_states_response = ssm.describe_instance_patch_states(
                            InstanceIds=list(compliance_summary.keys())
                        )
                    
                    for state in patch_states_response.get('InstancePatchStates', []):
                        instance_id = state['InstanceId']
                        
                        if instance_id not in compliance_summary:
                            compliance_summary[instance_id] = {
                                'InstanceId': instance_id,
                                'ComplianceType': 'Patch',
                                'Severity': 'UNSPECIFIED',
                                'Status': 'UNKNOWN'
                            }
                        
                        compliance_summary[instance_id].update({
                            'InstalledPatches': state.get('InstalledCount', 0),
                            'InstalledPendingRebootPatches': state.get('InstalledPendingRebootCount', 0),
                            'MissingPatches': state.get('MissingCount', 0),
                            'FailedPatches': state.get('FailedCount', 0),
                            'NotApplicablePatches': state.get('NotApplicableCount', 0),
                            'OperationStartTime': state.get('OperationStartTime', '').isoformat() if state.get('OperationStartTime') else 'N/A',
                            'OperationEndTime': state.get('OperationEndTime', '').isoformat() if state.get('OperationEndTime') else 'N/A',
                            'Operation': state.get('Operation', 'N/A'),
                            'RebootOption': state.get('RebootOption', 'N/A')
                        })
                        
                except Exception as e:
                    logger.warning(f"Could not get patch states: {e}")
            
            # Get instance details for context
            if compliance_summary:
                ec2 = boto3.client('ec2', region_name=region)
                instance_ids_list = list(compliance_summary.keys())
                
                try:
                    # Handle empty list case
                    if instance_ids_list:
                        ec2_response = ec2.describe_instances(InstanceIds=instance_ids_list)
                        
                        for reservation in ec2_response['Reservations']:
                            for instance in reservation['Instances']:
                                instance_id = instance['InstanceId']
                                if instance_id in compliance_summary:
                                    # Get instance name from tags
                                    name = 'N/A'
                                    env = 'N/A'
                                    for tag in instance.get('Tags', []):
                                        if tag['Key'] == 'Name':
                                            name = tag['Value']
                                        elif tag['Key'] in ['Environment', 'Env']:
                                            env = tag['Value']
                                    
                                    compliance_summary[instance_id].update({
                                        'Name': name,
                                        'Environment': env,
                                        'State': instance['State']['Name'],
                                        'InstanceType': instance['InstanceType']
                                    })
                except Exception as e:
                    logger.warning(f"Could not get EC2 details: {e}")
            
            # Convert to list and add compliance status
            results = []
            for instance_id, data in compliance_summary.items():
                # Determine overall compliance status
                if data.get('MissingPatches', 0) > 0 or data.get('FailedPatches', 0) > 0:
                    data['ComplianceStatus'] = 'NON_COMPLIANT'
                elif data.get('InstalledPendingRebootPatches', 0) > 0:
                    data['ComplianceStatus'] = 'PENDING_REBOOT'
                else:
                    data['ComplianceStatus'] = 'COMPLIANT'
                
                results.append(data)
            
            return self._safe_json_response(
                True,
                region=region,
                instances=results,
                count=len(results),
                summary={
                    'compliant': len([r for r in results if r.get('ComplianceStatus') == 'COMPLIANT']),
                    'non_compliant': len([r for r in results if r.get('ComplianceStatus') == 'NON_COMPLIANT']),
                    'pending_reboot': len([r for r in results if r.get('ComplianceStatus') == 'PENDING_REBOOT'])
                }
            )
        except Exception as e:
            return self._handle_aws_error("get_patch_compliance_summary", e, region=region)

    def _get_patch_operation_results(self, instance_id: str, operation_id: Optional[str] = None, 
                                    region: str = "us-east-1") -> str:
        """Get detailed patch operation results"""
        try:
            ssm = boto3.client('ssm', region_name=region)
            
            # Get patch history for the instance
            response = ssm.describe_instance_patch_states(
                InstanceIds=[instance_id]
            )
            
            if not response.get('InstancePatchStates'):
                return self._safe_json_response(False, error="No patch state found for instance", instance_id=instance_id)
            
            patch_state = response['InstancePatchStates'][0]
            
            # Get detailed patch results
            patch_response = ssm.describe_instance_patches(
                InstanceId=instance_id,
                MaxResults=100
            )
            
            patches = []
            for patch in patch_response.get('Patches', []):
                patches.append({
                    'Title': patch.get('Title', 'N/A'),
                    'KBId': patch.get('KBId', 'N/A'),
                    'Classification': patch.get('Classification', 'N/A'),
                    'Severity': patch.get('Severity', 'N/A'),
                    'State': patch.get('State', 'N/A'),
                    'InstalledTime': patch.get('InstalledTime', '').isoformat() if patch.get('InstalledTime') else 'N/A'
                })
            
            # Get command invocations if operation_id provided
            command_details = None
            if operation_id:
                try:
                    cmd_response = ssm.get_command_invocation(
                        CommandId=operation_id,
                        InstanceId=instance_id
                    )
                    command_details = {
                        'CommandId': cmd_response['CommandId'],
                        'Status': cmd_response['Status'],
                        'StatusDetails': cmd_response.get('StatusDetails', ''),
                        'StandardOutput': cmd_response.get('StandardOutputContent', '')[:1000],  # First 1000 chars
                        'StandardError': cmd_response.get('StandardErrorContent', '')[:1000]
                    }
                except Exception as e:
                    logger.warning(f"Could not get command details: {e}")
            
            return self._safe_json_response(
                True,
                instanceId=instance_id,
                patchState={
                    'OperationStartTime': patch_state.get('OperationStartTime', '').isoformat() if patch_state.get('OperationStartTime') else 'N/A',
                    'OperationEndTime': patch_state.get('OperationEndTime', '').isoformat() if patch_state.get('OperationEndTime') else 'N/A',
                    'Operation': patch_state.get('Operation', 'N/A'),
                    'InstalledCount': patch_state.get('InstalledCount', 0),
                    'InstalledPendingRebootCount': patch_state.get('InstalledPendingRebootCount', 0),
                    'MissingCount': patch_state.get('MissingCount', 0),
                    'FailedCount': patch_state.get('FailedCount', 0),
                    'NotApplicableCount': patch_state.get('NotApplicableCount', 0),
                    'RebootOption': patch_state.get('RebootOption', 'N/A')
                },
                patches=patches,
                commandDetails=command_details
            )
        except Exception as e:
            return self._handle_aws_error("get_patch_operation_results", e, instance_id=instance_id)
    # =====================
    # ENHANCED SSM PATCHING OPERATIONS
    # =====================

    def _get_detailed_maintenance_window_report(self, window_id: str, execution_id: Optional[str] = None, 
                                            region: str = "us-east-1") -> str:
        """Get comprehensive maintenance window execution report with package details"""
        try:
            ssm = boto3.client('ssm', region_name=region)
            ec2 = boto3.client('ec2', region_name=region)
            
            report = {
                'windowId': window_id,
                'executionId': execution_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'summary': {},
                'instanceDetails': [],
                'packageUpdates': [],
                'applicationUpdates': [],
                'failedPatches': [],
                'pendingActions': []
            }
            
            # Get window details
            window_details = ssm.get_maintenance_window(WindowId=window_id)
            report['windowName'] = window_details.get('Name', 'N/A')
            report['windowDescription'] = window_details.get('Description', 'N/A')
            
            # # Get executions
            # if execution_id:
            #     exec_filter = [{'Key': 'ExecutionId', 'Values': [execution_id]}]
            # else:
            #     # Get latest execution
            #     exec_filter = []
            
            # exec_response = ssm.describe_maintenance_window_executions(
            #     WindowId=window_id,
            #     Filters=exec_filter,
            #     MaxResults=1
            # )
            # Get executions
            if execution_id:
                exec_filter = [{'Key': 'ExecutionId', 'Values': [execution_id]}]
            else:
                # Get latest execution
                exec_filter = []

            exec_response = ssm.describe_maintenance_window_executions(
                WindowId=window_id,
                Filters=exec_filter,
                MaxResults=10  # Changed from 1 to 10 (AWS minimum requirement)
            )

            # Since we only want the latest, still take the first one
            if not execution_id and exec_response.get('WindowExecutions'):
                # Take only the most recent execution
                exec_response['WindowExecutions'] = exec_response['WindowExecutions'][:1]
            
            if not exec_response.get('WindowExecutions'):
                return self._safe_json_response(False, error="No executions found", window_id=window_id)
            
            execution = exec_response['WindowExecutions'][0]
            exec_id = execution['WindowExecutionId']
            report['executionId'] = exec_id
            report['executionStatus'] = execution['Status']
            report['startTime'] = execution.get('StartTime', '').isoformat() if execution.get('StartTime') else 'N/A'
            report['endTime'] = execution.get('EndTime', '').isoformat() if execution.get('EndTime') else 'N/A'
            
            # Get task executions
            task_response = ssm.describe_maintenance_window_execution_tasks(
                WindowExecutionId=exec_id
            )
            
            all_instance_ids = set()
            instance_patch_details = {}
            
            # Process each task
            for task in task_response.get('WindowExecutionTaskIdentities', []):
                task_exec_id = task['TaskExecutionId']
                
                # Get task invocations (per instance)
                invocation_response = ssm.describe_maintenance_window_execution_task_invocations(
                    WindowExecutionId=exec_id,
                    TaskId=task_exec_id,
                    MaxResults=50
                )
                
                for invocation in invocation_response.get('WindowExecutionTaskInvocationIdentities', []):
                    instance_id = invocation.get('Parameters', {}).get('InstanceIds', ['Unknown'])[0]
                    if instance_id != 'Unknown':
                        all_instance_ids.add(instance_id)
                    
                    invocation_id = invocation.get('InvocationId')
                    
                    # Get detailed command output if available
                    if invocation_id:
                        try:
                            # Get command invocation details
                            cmd_response = ssm.get_command_invocation(
                                CommandId=invocation_id.split('/')[-1],  # Extract command ID
                                InstanceId=instance_id
                            )
                            
                            # Parse patch installation output
                            output = cmd_response.get('StandardOutputContent', '')
                            
                            # Extract package details from output
                            packages = self._parse_patch_output(output)
                            
                            instance_patch_details[instance_id] = {
                                'status': invocation['Status'],
                                'packages': packages,
                                'output': output[:2000],  # First 2000 chars
                                'errors': cmd_response.get('StandardErrorContent', '')[:1000]
                            }
                            
                        except Exception as e:
                            logger.warning(f"Could not get command details for {instance_id}: {e}")
            
            # Get instance metadata
            if all_instance_ids:
                try:
                    ec2_response = ec2.describe_instances(InstanceIds=list(all_instance_ids))
                    instance_metadata = {}
                    
                    for reservation in ec2_response['Reservations']:
                        for instance in reservation['Instances']:
                            instance_id = instance['InstanceId']
                            
                            # Get tags
                            name = 'N/A'
                            env = 'N/A'
                            app = 'N/A'
                            
                            for tag in instance.get('Tags', []):
                                if tag['Key'] == 'Name':
                                    name = tag['Value']
                                elif tag['Key'] in ['Environment', 'Env']:
                                    env = tag['Value']
                                elif tag['Key'] in ['Application', 'App']:
                                    app = tag['Value']
                            
                            instance_metadata[instance_id] = {
                                'name': name,
                                'environment': env,
                                'application': app,
                                'instanceType': instance['InstanceType'],
                                'platform': instance.get('Platform', 'Linux'),
                                'state': instance['State']['Name']
                            }
                    
                except Exception as e:
                    logger.error(f"Could not get EC2 metadata: {e}")
                    instance_metadata = {}
            
            # Get current patch compliance for all instances
            compliance_data = {}
            if all_instance_ids:
                try:
                    compliance_response = ssm.describe_instance_patch_states(
                        InstanceIds=list(all_instance_ids)
                    )
                    
                    for state in compliance_response.get('InstancePatchStates', []):
                        instance_id = state['InstanceId']
                        compliance_data[instance_id] = {
                            'installedCount': state.get('InstalledCount', 0),
                            'installedPendingRebootCount': state.get('InstalledPendingRebootCount', 0),
                            'installedRejectedCount': state.get('InstalledRejectedCount', 0),
                            'missingCount': state.get('MissingCount', 0),
                            'failedCount': state.get('FailedCount', 0),
                            'notApplicableCount': state.get('NotApplicableCount', 0),
                            'unreportedNotApplicableCount': state.get('UnreportedNotApplicableCount', 0),
                            'operationStartTime': state.get('OperationStartTime', '').isoformat() if state.get('OperationStartTime') else 'N/A',
                            'operationEndTime': state.get('OperationEndTime', '').isoformat() if state.get('OperationEndTime') else 'N/A',
                            'rebootOption': state.get('RebootOption', 'N/A')
                        }
                        
                        # Get detailed patch information
                        patches_response = ssm.describe_instance_patches(
                            InstanceId=instance_id,
                            MaxResults=100
                        )
                        
                        patches_by_state = {
                            'installed': [],
                            'installedPendingReboot': [],
                            'missing': [],
                            'failed': []
                        }
                        
                        for patch in patches_response.get('Patches', []):
                            patch_info = {
                                'title': patch.get('Title', 'N/A'),
                                'kbId': patch.get('KBId', 'N/A'),
                                'classification': patch.get('Classification', 'N/A'),
                                'severity': patch.get('Severity', 'N/A'),
                                'state': patch.get('State', 'N/A'),
                                'installedTime': patch.get('InstalledTime', '').isoformat() if patch.get('InstalledTime') else 'N/A',
                                'cveIds': patch.get('CVEIds', [])
                            }
                            
                            state_map = {
                                'INSTALLED': 'installed',
                                'INSTALLED_PENDING_REBOOT': 'installedPendingReboot',
                                'MISSING': 'missing',
                                'FAILED': 'failed'
                            }
                            
                            patch_state = state_map.get(patch.get('State', ''), 'other')
                            if patch_state in patches_by_state:
                                patches_by_state[patch_state].append(patch_info)
                        
                        compliance_data[instance_id]['patches'] = patches_by_state
                        
                except Exception as e:
                    logger.error(f"Could not get compliance data: {e}")
            
            # Build instance details
            success_count = 0
            failure_count = 0
            pending_reboot_count = 0
            
            for instance_id in all_instance_ids:
                metadata = instance_metadata.get(instance_id, {})
                patch_details = instance_patch_details.get(instance_id, {})
                compliance = compliance_data.get(instance_id, {})
                
                instance_info = {
                    'instanceId': instance_id,
                    'name': metadata.get('name', 'N/A'),
                    'environment': metadata.get('environment', 'N/A'),
                    'application': metadata.get('application', 'N/A'),
                    'platform': metadata.get('platform', 'Linux'),
                    'executionStatus': patch_details.get('status', 'N/A'),
                    'compliance': compliance,
                    'packagesInstalled': patch_details.get('packages', []),
                    'errors': patch_details.get('errors', '')
                }
                
                # Categorize instance
                if patch_details.get('status') == 'SUCCESS':
                    success_count += 1
                    instance_info['category'] = 'success'
                elif patch_details.get('status') in ['FAILED', 'TIMED_OUT']:
                    failure_count += 1
                    instance_info['category'] = 'failed'
                    report['failedPatches'].append({
                        'instanceId': instance_id,
                        'name': metadata.get('name', 'N/A'),
                        'reason': patch_details.get('errors', 'Unknown error')
                    })
                
                if compliance.get('installedPendingRebootCount', 0) > 0:
                    pending_reboot_count += 1
                    report['pendingActions'].append({
                        'instanceId': instance_id,
                        'action': 'REBOOT_REQUIRED',
                        'reason': f"{compliance.get('installedPendingRebootCount', 0)} patches pending reboot"
                    })
                
                report['instanceDetails'].append(instance_info)
            
            # Aggregate package updates across all instances
            package_summary = {}
            app_summary = {}
            
            for instance_id, details in instance_patch_details.items():
                for package in details.get('packages', []):
                    pkg_name = package.get('name', 'Unknown')
                    
                    if pkg_name not in package_summary:
                        package_summary[pkg_name] = {
                            'name': pkg_name,
                            'instances': [],
                            'versions': set(),
                            'classification': package.get('classification', 'N/A')
                        }
                    
                    package_summary[pkg_name]['instances'].append(instance_id)
                    if package.get('version'):
                        package_summary[pkg_name]['versions'].add(package.get('version'))
                    
                    # Check if it's an application update
                    if package.get('classification') in ['Application', 'Updates']:
                        app_name = package.get('name', 'Unknown')
                        if app_name not in app_summary:
                            app_summary[app_name] = {
                                'name': app_name,
                                'instances': [],
                                'fromVersion': package.get('oldVersion', 'N/A'),
                                'toVersion': package.get('version', 'N/A')
                            }
                        app_summary[app_name]['instances'].append(instance_id)
            
            # Convert sets to lists for JSON serialization
            for pkg in package_summary.values():
                pkg['versions'] = list(pkg['versions'])
                pkg['instanceCount'] = len(pkg['instances'])
            
            report['packageUpdates'] = list(package_summary.values())
            report['applicationUpdates'] = list(app_summary.values())
            
            # Build summary
            report['summary'] = {
                'totalInstances': len(all_instance_ids),
                'successfulInstances': success_count,
                'failedInstances': failure_count,
                'instancesPendingReboot': pending_reboot_count,
                'totalPackagesUpdated': len(package_summary),
                'totalApplicationsUpdated': len(app_summary),
                'executionDuration': self._calculate_duration(
                    execution.get('StartTime'),
                    execution.get('EndTime')
                ) if execution.get('StartTime') and execution.get('EndTime') else 'N/A'
            }
            
            return self._safe_json_response(True, **report)
            
        except Exception as e:
            return self._handle_aws_error("get_detailed_maintenance_window_report", e, window_id=window_id)

    def _parse_patch_output(self, output: str) -> List[Dict]:
        """Parse patch installation output to extract package details"""
        packages = []
        
        # Common patterns for different OS types
        patterns = {
            'yum': r'(Installing|Updating|Upgrading):\s+(\S+)\s+(\S+)',
            'apt': r'(Installing|Upgrading)\s+(\S+)\s+from\s+(\S+)\s+to\s+(\S+)',
            'windows': r'Successfully installed\s+\-\s+(\S+)',
        }
        
        # Try to identify package manager and parse accordingly
        if 'yum' in output.lower() or 'rpm' in output.lower():
            # Red Hat/CentOS/Amazon Linux
            for match in re.finditer(patterns['yum'], output):
                packages.append({
                    'action': match.group(1),
                    'name': match.group(2),
                    'version': match.group(3),
                    'type': 'rpm'
                })
        elif 'apt' in output.lower() or 'dpkg' in output.lower():
            # Ubuntu/Debian
            for match in re.finditer(patterns['apt'], output):
                packages.append({
                    'action': match.group(1),
                    'name': match.group(2),
                    'oldVersion': match.group(3),
                    'version': match.group(4),
                    'type': 'deb'
                })
        elif 'windows' in output.lower() or 'kb' in output.lower():
            # Windows
            for match in re.finditer(patterns['windows'], output):
                packages.append({
                    'action': 'Installed',
                    'name': match.group(1),
                    'type': 'windows_update'
                })
        
        return packages

    def _get_patch_baseline_compliance(self, baseline_id: Optional[str] = None, 
                                    region: str = "us-east-1") -> str:
        """Get patch baseline compliance across all instances"""
        try:
            ssm = boto3.client('ssm', region_name=region)
            
            # Get all patch baselines if not specified
            if not baseline_id:
                baselines_response = ssm.describe_patch_baselines(MaxResults=100)
                baselines = baselines_response.get('BaselineIdentities', [])
            else:
                baselines = [{'BaselineId': baseline_id}]
            
            compliance_report = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'baselines': [],
                'overallCompliance': {}
            }
            
            for baseline in baselines:
                baseline_id = baseline['BaselineId']
                
                # Get baseline details
                baseline_details = ssm.get_patch_baseline(BaselineId=baseline_id)
                
                # Get compliance for this baseline
                compliance_response = ssm.describe_patch_group_state(
                    PatchGroup=baseline_details.get('Name', baseline_id)
                )
                
                baseline_info = {
                    'baselineId': baseline_id,
                    'name': baseline_details.get('Name', 'N/A'),
                    'operatingSystem': baseline_details.get('OperatingSystem', 'N/A'),
                    'approvalRules': baseline_details.get('ApprovalRules', {}),
                    'compliance': {
                        'instances': compliance_response.get('Instances', 0),
                        'instancesWithInstalledPatches': compliance_response.get('InstancesWithInstalledPatches', 0),
                        'instancesWithInstalledOtherPatches': compliance_response.get('InstancesWithInstalledOtherPatches', 0),
                        'instancesWithMissingPatches': compliance_response.get('InstancesWithMissingPatches', 0),
                        'instancesWithFailedPatches': compliance_response.get('InstancesWithFailedPatches', 0),
                        'instancesWithNotApplicablePatches': compliance_response.get('InstancesWithNotApplicablePatches', 0),
                        'instancesWithUnreportedNotApplicablePatches': compliance_response.get('InstancesWithUnreportedNotApplicablePatches', 0)
                    }
                }
                
                compliance_report['baselines'].append(baseline_info)
            
            # Calculate overall compliance
            total_instances = sum(b['compliance']['instances'] for b in compliance_report['baselines'])
            compliant_instances = sum(b['compliance']['instancesWithInstalledPatches'] for b in compliance_report['baselines'])
            non_compliant = sum(b['compliance']['instancesWithMissingPatches'] for b in compliance_report['baselines'])
            
            compliance_report['overallCompliance'] = {
                'totalInstances': total_instances,
                'compliantInstances': compliant_instances,
                'nonCompliantInstances': non_compliant,
                'compliancePercentage': (compliant_instances / total_instances * 100) if total_instances > 0 else 0
            }
            
            return self._safe_json_response(True, **compliance_report)
            
        except Exception as e:
            return self._handle_aws_error("get_patch_baseline_compliance", e, baseline_id=baseline_id)

    def _calculate_duration(self, start_time, end_time) -> str:
        """Calculate duration between two times"""
        if not start_time or not end_time:
            return 'N/A'
        
        duration = end_time - start_time
        hours = duration.seconds // 3600
        minutes = (duration.seconds % 3600) // 60
        
        if hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"

    # TODO: This is a placeholder for the patch remediation plan.
    def _generate_patch_remediation_plan(self, instance_ids: str, region: str = "us-east-1") -> str:
        """Generate a remediation plan for non-compliant instances"""
        try:
            ssm = boto3.client('ssm', region_name=region)
            ec2 = boto3.client('ec2', region_name=region)
            
            instance_list = [id.strip() for id in instance_ids.split(',')]
            
            remediation_plan = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'instances': [],
                'commands': [],
                'estimatedDuration': 0,
                'maintenanceWindows': []
            }
            
            # Get instance and patch states
            for instance_id in instance_list:
                # Get patch state
                patch_response = ssm.describe_instance_patch_states(InstanceIds=[instance_id])
                
                if not patch_response.get('InstancePatchStates'):
                    continue
                
                patch_state = patch_response['InstancePatchStates'][0]
                
                # Get instance details
                ec2_response = ec2.describe_instances(InstanceIds=[instance_id])
                instance = ec2_response['Reservations'][0]['Instances'][0] if ec2_response['Reservations'] else {}
                
                # Get instance name from tags
                name = 'N/A'
                env = 'N/A'
                for tag in instance.get('Tags', []):
                    if tag['Key'] == 'Name':
                        name = tag['Value']
                    elif tag['Key'] in ['Environment', 'Env']:
                        env = tag['Value']
                
                instance_plan = {
                    'instanceId': instance_id,
                    'name': name,
                    'environment': env,
                    'currentState': {
                        'missingPatches': patch_state.get('MissingCount', 0),
                        'failedPatches': patch_state.get('FailedCount', 0),
                        'pendingReboot': patch_state.get('InstalledPendingRebootCount', 0)
                    },
                    'actions': []
                }
                
                # Determine required actions
                if patch_state.get('MissingCount', 0) > 0:
                    instance_plan['actions'].append({
                        'type': 'INSTALL_PATCHES',
                        'description': f"Install {patch_state.get('MissingCount', 0)} missing patches",
                        'estimatedMinutes': 30
                    })
                    remediation_plan['estimatedDuration'] += 30
                
                if patch_state.get('FailedCount', 0) > 0:
                    instance_plan['actions'].append({
                        'type': 'RETRY_FAILED_PATCHES',
                        'description': f"Retry {patch_state.get('FailedCount', 0)} failed patches",
                        'estimatedMinutes': 20
                    })
                    remediation_plan['estimatedDuration'] += 20
                
                if patch_state.get('InstalledPendingRebootCount', 0) > 0:
                    instance_plan['actions'].append({
                        'type': 'REBOOT',
                        'description': f"Reboot to complete {patch_state.get('InstalledPendingRebootCount', 0)} patches",
                        'estimatedMinutes': 10
                    })
                    remediation_plan['estimatedDuration'] += 10
                
                remediation_plan['instances'].append(instance_plan)
            
            # Generate SSM commands
            if any(i['currentState']['missingPatches'] > 0 for i in remediation_plan['instances']):
                remediation_plan['commands'].append({
                    'description': 'Install missing patches',
                    'command': f"aws ssm send-command --document-name 'AWS-RunPatchBaseline' --targets 'Key=InstanceIds,Values={','.join(instance_list)}' --parameters 'Operation=Install'",
                    'documentName': 'AWS-RunPatchBaseline',
                    'parameters': {'Operation': 'Install'}
                })
            
            if any(i['currentState']['pendingReboot'] > 0 for i in remediation_plan['instances']):
                reboot_instances = [i['instanceId'] for i in remediation_plan['instances'] if i['currentState']['pendingReboot'] > 0]
                remediation_plan['commands'].append({
                    'description': 'Reboot instances with pending patches',
                    'command': f"aws ec2 reboot-instances --instance-ids {' '.join(reboot_instances)}",
                    'instanceIds': reboot_instances
                })
            
            # Suggest maintenance windows
            current_time = datetime.now(timezone.utc)
            remediation_plan['maintenanceWindows'] = [
                {
                    'name': 'Immediate',
                    'startTime': current_time.isoformat(),
                    'duration': f"{remediation_plan['estimatedDuration']} minutes",
                    'recommendation': 'For critical security patches'
                },
                {
                    'name': 'Next Maintenance Window',
                    'startTime': (current_time + timedelta(days=1)).replace(hour=2, minute=0).isoformat(),
                    'duration': f"{remediation_plan['estimatedDuration']} minutes",
                    'recommendation': 'For non-critical patches during off-hours'
                }
            ]
            
            return self._safe_json_response(True, **remediation_plan)
            
        except Exception as e:
            return self._handle_aws_error("generate_patch_remediation_plan", e, instance_ids=instance_ids)


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
    
    elif command == "/last_alert":
        """Show the last alert in this channel"""
        channel_context_id = f"channel_{channel_id}_last_alert"
        
        if client.context_manager:
            channel_context = client.context_manager.get_context(channel_context_id)
            
            if channel_context and 'last_alert_session' in channel_context:
                alert_session_id = channel_context['last_alert_session']
                alert_context = client.context_manager.get_context(alert_session_id)
                
                if alert_context:
                    response = "*📋 Last Alert Details*\n\n"
                    response += f"• *Alert ID:* `{alert_session_id}`\n"
                    response += f"• *Instance:* `{alert_context.get('instance_id', 'N/A')}`\n"
                    response += f"• *Type:* {alert_context.get('alert_type', 'N/A')}\n"
                    response += f"• *Time:* {alert_context.get('alert_time', 'N/A')}\n"
                    response += f"• *Region:* {alert_context.get('region', 'N/A')}\n"
                    
                    if 'disk_usage' in alert_context:
                        response += f"• *Disk Usage:* {alert_context['disk_usage']}%\n"
                    
                    response += f"\n*Continue investigating:*\n"
                    response += f"• `/aws check status of {alert_context.get('instance_id')}`\n"
                    response += f"• `/show_alert {alert_session_id}` for full details"
                else:
                    response = "No alert details found."
            else:
                response = "No recent alerts in this channel."
        else:
            response = "Context management not available."
        
        return {"response": response}
    
    elif command == "/show_alert":
        """Show specific alert details"""
        if not text:
            return {"response": "Please provide an alert ID. Example: `/show_alert alert_C1234_i-abc123`"}
        
        alert_id = text.strip()
        
        if client.context_manager:
            alert_context = client.context_manager.get_context(alert_id)
            
            if alert_context:
                response = f"*🔍 Alert Details for `{alert_id}`*\n\n"
                
                for key, value in alert_context.items():
                    if key != 'initial_text':  # Skip long text
                        formatted_key = key.replace('_', ' ').title()
                        response += f"• *{formatted_key}:* {value}\n"
                
                if 'initial_text' in alert_context:
                    response += f"\n*Initial Alert (truncated):*\n```{alert_context['initial_text'][:500]}...```"
            else:
                response = f"Alert `{alert_id}` not found."
        else:
            response = "Context management not available."
        
        return {"response": response}
    
    elif command == "/list_alerts":
        """List recent alerts"""
        # This would require storing alerts in a separate DynamoDB table
        # For now, show how to access the last alert
        channel_context_id = f"channel_{channel_id}_last_alert"
        
        if client.context_manager:
            context = client.context_manager.get_context(channel_context_id)
            if context:
                response = "*📊 Recent Alerts*\n\n"
                response += f"• Last Alert: `{context.get('last_alert_session', 'N/A')}`\n"
                response += f"• Instance: `{context.get('last_alert_instance', 'N/A')}`\n"
                response += f"• Time: {context.get('last_alert_time', 'N/A')}\n"
                response += "\nUse `/show_alert <alert_id>` for details"
            else:
                response = "No recent alerts found."
        else:
            response = "Context management not available."
        
        return {"response": response}

    else:
        return {"response": f"Unknown command: {command}"}


# Event tracking for deduplication
processed_events = OrderedDict()
processed_events_lock = threading.Lock()
MAX_CACHED_EVENTS = 1000


def get_event_hash(event_data):
    """Generate a hash for event deduplication"""
    if isinstance(event_data, dict):
        # For Slack events, use specific fields
        if 'event_id' in event_data:
            return event_data['event_id']
        elif 'event' in event_data and 'client_msg_id' in event_data.get('event', {}):
            return event_data['event']['client_msg_id']
        elif 'event' in event_data:
            event = event_data['event']
            # Create hash from event type, text, user, and timestamp
            hash_str = f"{event.get('type', '')}{event.get('text', '')}{event.get('user', '')}{event.get('ts', '')}"
            return hashlib.md5(hash_str.encode()).hexdigest()
    
    # Fallback to creating hash from entire event
    event_str = json.dumps(event_data, sort_keys=True)
    return hashlib.md5(event_str.encode()).hexdigest()


def is_duplicate_event(event_hash):
    """Check if event is duplicate and track it"""
    with processed_events_lock:
        current_time = time.time()
        
        # Clean old events (older than 5 minutes)
        events_to_remove = []
        for ehash, etime in list(processed_events.items()):
            if current_time - etime > 300:  # 5 minutes
                events_to_remove.append(ehash)
        
        for ehash in events_to_remove:
            del processed_events[ehash]
        
        # Check if current event is duplicate
        if event_hash in processed_events:
            logger.info(f"Duplicate event detected: {event_hash}")
            return True
        
        # Add event to processed
        processed_events[event_hash] = current_time
        
        # Limit cache size
        if len(processed_events) > MAX_CACHED_EVENTS:
            # Remove oldest events
            for _ in range(len(processed_events) - MAX_CACHED_EVENTS):
                processed_events.popitem(last=False)
        
        return False





def lambda_handler(event, context):
    """Lambda handler optimized for Slack Events API with mentions and slash commands"""
    request_id = context.aws_request_id
    logger.info(f"Lambda invocation started - RequestID: {request_id}")
    
    # Log memory and time limits
    logger.info(f"Memory allocated: {context.memory_limit_in_mb}MB, " +
               f"Time remaining: {context.get_remaining_time_in_millis()/1000:.2f}s")

    # ============================================
    # ASYNC PROCESSING CHECK (SELF-INVOCATION)
    # ============================================
    # Check if this is a self-invoked async processing request
    if event.get('_async_processing'):
        logger.info("Processing async request from self-invocation")
        
        try:
            # Extract the saved event details
            process_type = event.get('process_type')
            if process_type == 'app_mention':
                # Process app mention asynchronously
                text =  event['text']
                channel = event['channel']
                user = event['user']
                thread_ts = event['thread_ts']
                region = event.get('region', 'us-east-1')
                alert_context = event.get('alert_context', {})
                
                # Send initial "processing" message
                send_slack_message_with_thread(
                    channel, 
                    "🤔 Processing your request...", 
                    thread_ts
                )
                
                # Create client
                client = AWSMCPLambdaClient(region=region)
                
                # Determine session ID (use alert session if referenced)
                if alert_context.get('referenced_alert'):
                    # User explicitly referenced an alert
                    session_id = alert_context['referenced_alert']
                    
                    # Load alert context into current conversation
                    if client.context_manager:
                        stored_context = client.context_manager.get_context(session_id)
                        if stored_context:
                            # Add note about context
                            text = f"{text}\n\n[Context from alert {session_id}: Instance {stored_context.get('instance_id')}, Disk usage was {stored_context.get('disk_usage')}%]"
                
                elif alert_context.get('possible_alert'):
                    # Check if there's an alert for this instance
                    possible_session = alert_context['possible_alert']
                    if client.context_manager:
                        stored_context = client.context_manager.get_context(possible_session)
                        if stored_context:
                            session_id = possible_session
                            text = f"{text}\n\n[Using context from recent alert on this instance]"
                        else:
                            session_id = get_session_id(user, channel, thread_ts)
                else:
                    # Normal session
                    session_id = get_session_id(user, channel, thread_ts)
                
                # Process based on query type
                if text.lower() in ['hello', 'hi', 'hey', 'test']:
                    response_text = "👋 Hello! I'm your AWS Operations Assistant. How can I help you today?"
                else:
                    result = client.process_query_with_context(text, session_id)
                    response_text = result.get('response', 'I encountered an error processing your request.')
                
                # Send the actual response
                send_slack_message_with_thread(channel, response_text, thread_ts)
                client.cleanup()
            elif process_type == 'scheduled_patch_check':
                # Process scheduled patch compliance check
                environments = event.get('environments', [])
                channel = event['channel']
                region = event.get('region', 'us-east-1')
                
                client = AWSMCPLambdaClient(region=region)
                
                # Build comprehensive patch check query
                query = f"""
                Perform a comprehensive patch compliance check for all instances in environments: {', '.join(environments)}
                
                Please:
                1. Get patch compliance summary for all instances
                2. Group results by environment
                3. Identify:
                - Non-compliant instances
                - Instances pending reboot
                - Failed patch installations
                - Instances not reporting patch status
                4. Provide actionable recommendations
                5. Highlight any critical security patches missing
                
                Format as a clear Slack report with sections for each environment.
                """
                
                result = client.process_query_with_context(query, f"scheduled_patch_{datetime.now().strftime('%Y%m%d')}")
                
                # Build report
                report = f"""📊 *Weekly Patch Compliance Report*
            *Date:* {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}
            *Environments:* {', '.join(environments)}

            {result.get('response', 'Unable to generate report')}

            ---
            *🔧 Quick Actions:*
            • Apply missing patches: `/aws apply patches to non-compliant instances`
            • Schedule reboot: `/aws schedule reboot for instances pending restart`
            • View details: `/aws show detailed patch report`
            """
                
                send_slack_message_with_thread(channel, report, None)
                client.cleanup()
                
            elif process_type == 'slash_command':
                # Process slash command asynchronously (for long-running queries)
                command = event['command']
                text = event['text']
                user_id = event['user_id']
                channel_id = event['channel_id']
                response_url = event.get('response_url')
                region = event.get('region', 'us-east-1')
                
                # Process the command
                client = AWSMCPLambdaClient(region=region)
                session_id = get_session_id(user_id, channel_id)
                result = client.process_query_with_context(text, session_id)
                response_text = result.get('response', 'Error processing request.')
                
                # Send response via response_url if available
                if response_url:
                    try:
                        requests.post(response_url, json={
                            'response_type': 'in_channel',
                            'text': response_text
                        }, timeout=5)
                    except Exception as e:
                        logger.error(f"Failed to send to response_url: {e}")
                
                client.cleanup()

            elif process_type == 'patch_verification':
                window_id = event['window_id']
                execution_status = event['execution_status']
                channel = event['channel']
                region = event.get('region', 'us-east-1')
                
                logger.info(f"Processing patch verification using PatchManager for window {window_id}")
                
                # Create client
                client = AWSMCPLambdaClient(region=region)
                
                # Build comprehensive query using PatchManager tools
                verification_query = f"""
                Generate a comprehensive patch report for maintenance window {window_id} with execution status {execution_status}:
                
                1. Use get_maintenance_windows_detailed to get window configuration for {window_id}
                2. Use check_patch_status to verify current compliance for all affected instances
                3. Use get_patch_history with days_back=1 to see what patches were recently applied
                4. If status is FAILED, use diagnose_patch_failures to identify issues
                5. Use collect_system_info for any instances that show failures
                
                Provide a detailed report with:
                - Execution summary with start/end times
                - Total instances affected, grouped by environment (prod/staging/dev)
                - Success/failure/pending reboot counts
                - List of specific packages/applications updated
                - For any failures, provide specific error messages and remediation steps
                - List instances requiring reboot with patch counts
                - Actionable next steps based on the results
                
                Format for Slack with:
                - Clear sections using *bold headers*
                - Appropriate emojis (✅ for success, ❌ for failures, ⚠️ for warnings)
                - Instance IDs in backticks
                - Bullet points using •
                - Group results by environment
                
                Current execution status: {execution_status}
                """
                
                # Process the query
                result = client.process_query_with_context(
                    verification_query, 
                    f"patch_{window_id}_{context.aws_request_id}"
                )
                
                # Extract the response text from result
                response_text = result.get('response', 'Unable to generate patch report.')
                
                # Determine notification header based on status
                if execution_status == 'SUCCESS':
                    header = "✅ *Patch Maintenance Window Completed Successfully*"
                    alert_emoji = "🎉"
                elif execution_status == 'FAILED':
                    header = "❌ *Patch Maintenance Window Failed*"
                    alert_emoji = "🚨"
                    # Also send to alert channel for failures
                    send_sns_alert(f"Patch window {window_id} failed", "CRITICAL")
                else:
                    header = f"⚠️ *Patch Maintenance Window Status: {execution_status}*"
                    alert_emoji = "⚠️"
                
                # Build the final message
                final_message = f"""{alert_emoji} {header}
            *Window ID:* `{window_id}`
            *Execution Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}

            {response_text}

            ---
            *📊 Quick Actions:*
            • Check patch compliance: `/aws check patch status for all instances`
            • View patch history: `/aws get patch history for window {window_id}`
            • Generate remediation plan: `/aws generate patch remediation plan for non-compliant instances`

            *🔧 Remediation Commands:*
            • Apply missing patches: `/aws apply patches to non-compliant instances`
            • Schedule reboots: `/aws schedule reboot for instances pending restart`
            • Diagnose failures: `/aws diagnose patch failures for window {window_id}`
            • Check specific instance: `/aws get patch details for instance <id>`

            *📅 Maintenance Windows:*
            • View all windows: `/aws get maintenance windows`
            • Check next window: `/aws show next maintenance window schedule`
            • Modify window: `/aws update maintenance window {window_id}`
            """
                
                # Send to Slack
                send_slack_message_with_thread(channel, final_message, None)
                
                # Store context for follow-up using data from the query result
                if client.context_manager:
                    # Extract summary data from the AI's tool calls if available
                    tool_calls = result.get('tool_calls', [])
                    
                    # Build context from tool call results
                    summary_data = {}
                    failed_instances = []
                    pending_reboots = []
                    
                    # Parse tool call results for context
                    for call in tool_calls:
                        if call['tool_name'] == 'check_patch_status':
                            # Extract summary from patch status results
                            try:
                                status_result = json.loads(call.get('result', '{}'))
                                if status_result.get('success'):
                                    summary_data = status_result.get('summary', {})
                                    
                                    # Extract failed and pending reboot instances
                                    for instance_id, data in status_result.get('instances', {}).items():
                                        if 'patch_state' in data:
                                            state = data['patch_state']
                                            if state.get('compliance_status') == 'NON_COMPLIANT_CRITICAL':
                                                failed_instances.append({
                                                    'instance_id': instance_id,
                                                    'name': data.get('instance_info', {}).get('name', 'N/A'),
                                                    'failed_count': state.get('patch_counts', {}).get('failed', 0)
                                                })
                                            if state.get('patch_counts', {}).get('installed_pending_reboot', 0) > 0:
                                                pending_reboots.append({
                                                    'instance_id': instance_id,
                                                    'name': data.get('instance_info', {}).get('name', 'N/A'),
                                                    'pending_count': state.get('patch_counts', {}).get('installed_pending_reboot', 0)
                                                })
                            except Exception as e:
                                logger.warning(f"Could not parse patch status results: {e}")
                    
                    # Store the context
                    patch_context = {
                        'window_id': window_id,
                        'execution_status': execution_status,
                        'execution_time': datetime.now().isoformat(),
                        'channel': channel,
                        'summary': summary_data,
                        'failed_instances': failed_instances,
                        'pending_reboots': pending_reboots,
                        'tool_calls_made': len(tool_calls),
                        'query_iterations': result.get('iterations', 0)
                    }
                    
                    client.context_manager.update_context(f"patch_{window_id}", patch_context)
                    
                    # Also update channel context for easy reference
                    channel_context = {
                        'last_patch_window': window_id,
                        'last_patch_status': execution_status,
                        'last_patch_time': datetime.now().isoformat()
                    }
                    client.context_manager.update_context(f"channel_{channel}_patches", channel_context)
                
                client.cleanup()
                logger.info(f"Patch verification completed for window {window_id}")



            elif process_type == 'patch_command':
                # Process individual patch command completion
                command_id = event['command_id']
                status = event['status']
                event_detail = event['event_detail']
                channel = event['channel']
                region = event.get('region', 'us-east-1')
                
                # Only notify for failures or if explicitly configured
                if status != 'Success' or os.environ.get('NOTIFY_ALL_PATCHES', 'false').lower() == 'true':
                    client = AWSMCPLambdaClient(region=region)
                    
                    # Get command details
                    query = f"""
                    Get details for SSM command {command_id} and provide:
                    1. Which instances were targeted
                    2. What patches were applied
                    3. Any failures or errors
                    4. Current patch compliance status
                    """
                    
                    result = client.process_query_with_context(query, f"patch_cmd_{command_id}")
                    
                    if status == 'Success':
                        icon = "✅"
                    else:
                        icon = "❌"
                    
                    message = f"""{icon} *Patch Command {status}*
            *Command ID:* `{command_id}`

            {result.get('response', 'No details available')}
            """
                    
                    send_slack_message_with_thread(channel, message, None)
                    client.cleanup()





            elif process_type == 'scheduled_patch_check':
                # Enhanced scheduled patch compliance check
                environments = event.get('environments', [])
                channel = event['channel']
                region = event.get('region', 'us-east-1')
                
                client = AWSMCPLambdaClient(region=region)
                
                # Build comprehensive patch check query
                query = f"""
                Perform a comprehensive weekly patch compliance audit:
                
                1. Get patch baseline compliance for all baselines
                2. Get patch compliance summary for all instances grouped by environment: {', '.join(environments)}
                3. For each environment, provide:
                - Total instances and compliance percentage
                - List of non-compliant instances with missing patch counts
                - Critical security patches missing
                - Instances pending reboot
                - Failed patch installations from the past week
                - Application updates completed
                4. Generate remediation plans for non-compliant instances
                5. Identify instances that haven't reported patch status in >7 days
                6. Check for any superseded patches that need updating
                7. Provide trending data (compare with last week if available)
                
                Include specific recommendations for:
                - Critical patches that should be applied immediately
                - Maintenance window scheduling
                - Instances that repeatedly fail patching
                
                Format as a comprehensive Slack report with executive summary and detailed sections.
                """
                
                result = client.process_query_with_context(query, f"scheduled_patch_{datetime.now().strftime('%Y%m%d')}")
                
                # Build enhanced report
                report = f"""📊 *Weekly Patch Compliance Audit Report*
                *Report Date:* {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}
                *Environments Audited:* {', '.join(environments)}

                {result.get('response', 'Unable to generate report')}

                ---
                *🎯 Quick Actions Dashboard:*

                *Critical Actions (Do Today):*
                • Apply critical security patches: `/aws apply critical patches`
                • Reboot pending instances: `/aws reboot instances pending restart`

                *Scheduled Actions (This Week):*
                • Review failed patches: `/aws investigate failed patches`
                • Update patch baselines: `/aws update patch baselines`

                *Planning Actions:*
                • Schedule next maintenance: `/aws schedule maintenance window`
                • Review patch policies: `/aws show patch baseline configuration`

                ---
                *📈 Report History:*
                • Previous report: `/aws show last patch report`
                • Trend analysis: `/aws show patch compliance trend`
                • Download full report: `/aws export patch report to s3`

                *🔔 Alert Configuration:*
                • Current thresholds: `/aws show patch alert thresholds`
                • Modify alerts: `/aws configure patch alerts`
                """
                
                # Send main report
                send_slack_message_with_thread(channel, report, None)
                
                # If critical issues found, send additional alert
                if "CRITICAL" in result.get('response', '') or "urgent" in result.get('response', '').lower():
                    alert_channel = os.environ.get('SLACK_CRITICAL_CHANNEL', channel)
                    critical_alert = """🚨 *CRITICAL: Patch Compliance Issues Detected*
                            
                    Critical security patches are missing on production systems.
                    See full report in #aws-patches channel.

                    *Immediate Action Required:*
                    • Review critical patches: `/aws show critical missing patches`
                    • Apply patches: `/aws apply critical patches to production`
                    """
                    send_slack_message_with_thread(alert_channel, critical_alert, None)
                
                client.cleanup()

            elif process_type == 'event_alert':
                # Process event alert asynchronously
                text = event['text']
                channel = event['channel']
                region = event.get('region', 'us-east-1')
                
                # Extract instance ID and create session
                
                instance_match = re.search(r'i-[0-9a-f]{8,17}', text)
                instance_id = instance_match.group(0) if instance_match else None
                
                # Create a session ID that can be referenced later
                alert_session_id = f"alert_{channel}_{instance_id}" if instance_id else f"alert_{channel}_{context.aws_request_id}"
                
                # Send initial notification with session reference
                initial_message = f"""🔔 *Automated Alert Received*
                    Alert ID: `{alert_session_id}`
                    Instance: `{instance_id}` 
                    Processing disk space alert..."""
                
                send_slack_message_with_thread(channel, initial_message, None)
                
                # Create client and process the alert
                client = AWSMCPLambdaClient(region=region)
                
                # Store alert context for future reference
                if client.context_manager and instance_id:
                    alert_context = {
                        'instance_id': instance_id,
                        'alert_type': 'disk_space',
                        'alert_time': datetime.now().isoformat(),
                        'initial_text': text[:500],  # Store first 500 chars
                        'region': region,
                        'channel': channel
                    }
                    
                    # Extract metrics from alert
                    usage_match = re.search(r'(\d+\.?\d*)%', text)
                    if usage_match:
                        alert_context['disk_usage'] = usage_match.group(1)
                    
                    # Store in context manager with the alert session ID
                    client.context_manager.update_context(alert_session_id, alert_context)
                    
                    # Also store in a channel-wide context for easy access
                    channel_context_id = f"channel_{channel}_last_alert"
                    client.context_manager.update_context(channel_context_id, {
                        'last_alert_session': alert_session_id,
                        'last_alert_instance': instance_id,
                        'last_alert_time': datetime.now().isoformat()
                    })
                
                # Process the alert text as a query
                result = client.process_query_with_context(text, alert_session_id)
                response_text = result.get('response', 'Unable to process alert.')
                
                # Add follow-up instructions
                follow_up_text = f"""{response_text}

                ---
                *📝 Follow-up Instructions:*
                • To check this instance status: `@bot check instance {instance_id}`
                • To see alert history: `@bot show alert {alert_session_id}`
                • To continue investigating: `@bot investigate disk usage on {instance_id}`
                • Reference this alert anytime with Alert ID: `{alert_session_id}`"""
                
                # Send the analysis results
                send_slack_message_with_thread(channel, follow_up_text, None)
                
                client.cleanup()
            
        except Exception as e:
            logger.error(f"Error in async processing: {e}", exc_info=True)
            
            # Try to send error message to Slack
            try:
                if event.get('channel'):
                    send_slack_message_with_thread(
                        event['channel'], 
                        f"❌ Sorry, I encountered an error: {str(e)}", 
                        event.get('thread_ts')
                    )
            except:
                logger.error("Could not send error message to Slack")
            
            return {
                'statusCode': 500,
                'body': json.dumps({'async_processed': True, 'error': str(e)})
            }
    
    # ============================================
    # CHECK FOR DIRECT EVENT-ALERT INVOCATION
    # ============================================
    if event.get('command') == 'event-alert':
        logger.info("Processing direct event-alert command")
        
        # Get the default alert channel from environment
        alert_channel = os.environ.get('SLACK_ALERT_CHANNEL', '#alerts')
        
        # Get text from the event
        text = event.get('text', '')
        
        if not text:
            logger.error("No text provided in event-alert")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'No alert text provided'})
            }
        
        # Trigger async processing
        try:
            import boto3
            lambda_client = boto3.client('lambda')
            
            async_payload = {
                '_async_processing': True,
                'process_type': 'event_alert',
                'text': text,
                'channel': alert_channel,
                'region': os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
            }
            
            lambda_client.invoke(
                FunctionName=context.function_name,
                InvocationType='Event',  # Async invocation
                Payload=json.dumps(async_payload)
            )
            
            logger.info(f"Successfully triggered async processing for event-alert to channel {alert_channel}")
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'success': True,
                    'message': 'Alert processing initiated',
                    'channel': alert_channel
                })
            }
            
        except Exception as e:
            logger.error(f"Failed to trigger async processing: {e}")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': str(e)})
            }

    # ============================================
    # CHECK FOR MAINTENANCE WINDOW EVENTS (EventBridge)
    # ============================================

    if event.get('source') == 'aws.scheduler' or (event.get('detail-type') == 'Scheduled Event' and 'patch-check' in event.get('resources', [{}])[0].get('tag', '')):
        logger.info("Processing scheduled patch compliance check")
        
        # Get configuration from event or environment
        check_config = event.get('detail', {})
        environments = check_config.get('environments', ['prod', 'staging', 'dev'])
        alert_channel = os.environ.get('SLACK_PATCH_CHANNEL', '#alerts')
        
        # Trigger async processing
        try:
            import boto3
            lambda_client = boto3.client('lambda')
            
            async_payload = {
                '_async_processing': True,
                'process_type': 'scheduled_patch_check',
                'environments': environments,
                'channel': alert_channel,
                'region': os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
            }
            
            lambda_client.invoke(
                FunctionName=context.function_name,
                InvocationType='Event',
                Payload=json.dumps(async_payload)
            )
            
            return {
                'statusCode': 200,
                'body': json.dumps({'success': True, 'message': 'Scheduled patch check initiated'})
            }
            
        except Exception as e:
            logger.error(f"Failed to trigger scheduled patch check: {e}")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': str(e)})
            }
    if event.get('source') == 'aws.ssm' and event.get('detail-type') == 'Maintenance Window Execution State-change Notification':
        logger.info("Processing Maintenance Window event from EventBridge")
        
        detail = event.get('detail', {})
        window_id = detail.get('window-id')
        status = detail.get('status')
        
        # Get the alert channel
        alert_channel = os.environ.get('SLACK_PATCH_CHANNEL', os.environ.get('SLACK_ALERT_CHANNEL', '#alerts'))
        
        # Trigger async processing for patch verification
        try:
            import boto3
            lambda_client = boto3.client('lambda')
            
            async_payload = {
                '_async_processing': True,
                'process_type': 'patch_verification',
                'window_id': window_id,
                'execution_status': status,
                'event_detail': detail,
                'channel': alert_channel,
                'region': event.get('region', 'us-east-1')
            }
            
            lambda_client.invoke(
                FunctionName=context.function_name,
                InvocationType='Event',
                Payload=json.dumps(async_payload)
            )
            
            logger.info(f"Triggered patch verification for window {window_id}")
            
            return {
                'statusCode': 200,
                'body': json.dumps({'success': True, 'message': 'Patch verification initiated'})
            }
            
        except Exception as e:
            logger.error(f"Failed to trigger patch verification: {e}")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': str(e)})
            }

    # Add this to detect SSM Run Command completion (for patching)
    if event.get('source') == 'aws.ssm' and 'Run Command' in event.get('detail-type', ''):
        logger.info("Processing SSM Run Command event")
        
        detail = event.get('detail', {})
        document_name = detail.get('document-name', '')
        
        # Check if this is a patching command
        if 'Patch' in document_name or 'AWS-RunPatchBaseline' in document_name:
            alert_channel = os.environ.get('SLACK_PATCH_CHANNEL', os.environ.get('SLACK_ALERT_CHANNEL', '#alerts'))
            
            # Trigger async processing
            try:
                import boto3
                lambda_client = boto3.client('lambda')
                
                async_payload = {
                    '_async_processing': True,
                    'process_type': 'patch_command',
                    'command_id': detail.get('command-id'),
                    'status': detail.get('status'),
                    'event_detail': detail,
                    'channel': alert_channel,
                    'region': event.get('region', 'us-east-1')
                }
                
                lambda_client.invoke(
                    FunctionName=context.function_name,
                    InvocationType='Event',
                    Payload=json.dumps(async_payload)
                )
                
                return {
                    'statusCode': 200,
                    'body': json.dumps({'success': True})
                }
                
            except Exception as e:
                logger.error(f"Failed to trigger patch command processing: {e}")
                return {
                    'statusCode': 500,
                    'body': json.dumps({'error': str(e)})
                }
    # ============================================
    # NORMAL EVENT PROCESSING (SLACK EVENTS)
    # ============================================
    
    # Log the entire event for debugging (truncated)
    event_str = json.dumps(event)
    logger.info(f"Received event: {event_str[:1000]}...")

    start_time = time.time()

    try:
        # Detect event source
        event_source = detect_event_source(event)
        logger.info(f"Detected event source: {event_source}")

        # Handle different event sources
        if event_source == 'slack':
            # Check headers
            headers = event.get('headers', {})
            content_type = headers.get('Content-Type', headers.get('content-type', ''))

            # Verify Slack signature if present
            slack_signing_secret = os.environ.get('SLACK_SIGNING_SECRET')

            if slack_signing_secret and not verify_slack_request(event, slack_signing_secret):
                logger.warning("Slack request verification failed")
                return {
                    'statusCode': 401,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({'error': 'Unauthorized'})
                }

            # Handle Events API (JSON)
            if content_type == 'application/json' or (not content_type and event.get('body', '').strip().startswith('{')):
                logger.info("Processing Slack Events API request")

                # Parse event body
                body_str = event.get('body', '')
                if event.get('isBase64Encoded'):
                    body_str = base64.b64decode(body_str).decode('utf-8')

                body = json.loads(body_str) if isinstance(body_str, str) else body_str

                # Handle URL verification challenge
                if body.get('type') == 'url_verification':
                    logger.info(f"Handling Slack URL verification challenge: {body.get('challenge')}")
                    return {
                        'statusCode': 200,
                        'headers': {
                            'Content-Type': 'text/plain',
                            'X-Content-Type-Options': 'nosniff'
                        },
                        'body': body.get('challenge', ''),
                        'isBase64Encoded': False
                    }

                # Check for duplicate events EARLY
                event_hash = get_event_hash(body)
                if is_duplicate_event(event_hash):
                    logger.info(f"Skipping duplicate event: {event_hash}")
                    return {
                        'statusCode': 200,
                        'headers': {'Content-Type': 'application/json'},
                        'body': json.dumps({'ok': True, 'duplicate': True})
                    }

                # Handle event callbacks
                if body.get('type') == 'event_callback':
                    logger.info("Processing event callback")

                    # Extract event details
                    slack_event = body.get('event', {})
                    event_type = slack_event.get('type')

                    # Skip bot messages to prevent loops
                    if slack_event.get('bot_id') or slack_event.get('subtype') == 'bot_message':
                        logger.info("Ignoring bot message")
                        return {
                            'statusCode': 200,
                            'headers': {'Content-Type': 'application/json'},
                            'body': json.dumps({'ok': True})
                        }

                    # Handle app_mention events
                    if event_type == 'app_mention':
                        logger.info("Processing app mention")
                        
                        # Extract mention details
                        text = slack_event.get('text', '')
                        channel = slack_event.get('channel')
                        user = slack_event.get('user')
                        thread_ts = slack_event.get('thread_ts', slack_event.get('ts'))
                        
                        # Skip bot messages
                        if slack_event.get('bot_id'):
                            return {
                                'statusCode': 200,
                                'headers': {'Content-Type': 'application/json'},
                                'body': json.dumps({'ok': True, 'bot_message': True})
                            }
                        
                        # Remove bot mention from text
                        clean_text = re.sub(r'<@[A-Z0-9]+>', '', text).strip()
                        # clean_text = f"Keep your response concise and to the point. {clean_text} Here no need to be too verbose.And avoid using markdown. Also dont suggest using the @bot command. Just respond to the user's question and nothing else."
                        clean_text = clean_text = f"""Query: {clean_text}

                                Before responding:
                                1. Analyze the request thoroughly
                                2. Consider all relevant aspects
                                3. Plan your response structure

                                Response requirements:
                                - Provide a concised analysis with clear reasoning and do not be too verbose.
                                - Include necessary steps or methodology
                                - Keep explanations focused and relevant
                                - Use plain text only (no markdown formatting)
                                - Do not provide any suggestions to use the @bot command and the recommendations and no next steps.
                                - Do not mention @bot commands or meta-instructions"""
                        if clean_text:
                            # Check for alert references
                            alert_ref_match = re.search(r'alert_[\w_]+', clean_text)
                            instance_ref_match = re.search(r'i-[0-9a-f]{8,17}', clean_text)
                            
                            # Prepare context for async processing
                            async_context = {}
                            
                            # If user references an alert, load its context
                            if alert_ref_match:
                                alert_id = alert_ref_match.group(0)
                                async_context['referenced_alert'] = alert_id
                            
                            # If user references an instance, check if it's from a recent alert
                            if instance_ref_match and not alert_ref_match:
                                instance_id = instance_ref_match.group(0)
                                # Check if this instance had a recent alert
                                possible_alert_id = f"alert_{channel}_{instance_id}"
                                async_context['possible_alert'] = possible_alert_id
                            
                            # Check for duplicate
                            event_key = f"mention_{slack_event.get('ts')}_{user}"
                            if is_duplicate_event(event_key):
                                return {
                                    'statusCode': 200,
                                    'headers': {'Content-Type': 'application/json'},
                                    'body': json.dumps({'ok': True, 'duplicate': True})
                                }
                            
                            # Invoke this Lambda asynchronously with context
                            try:
                                import boto3
                                
                                lambda_client = boto3.client('lambda')
                                
                                async_payload = {
                                    '_async_processing': True,
                                    'process_type': 'app_mention',
                                    'text': clean_text,
                                    'channel': channel,
                                    'user': user,
                                    'thread_ts': thread_ts,
                                    'region': os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'),
                                    'alert_context': async_context  # Pass alert context
                                }
                                
                                lambda_client.invoke(
                                    FunctionName=context.function_name,
                                    InvocationType='Event',
                                    Payload=json.dumps(async_payload)
                                )
                                
                                logger.info("Successfully triggered async processing")
                                
                            except Exception as e:
                                logger.error(f"Failed to trigger async processing: {e}")
                        
                        # Return 200 immediately
                        return {
                            'statusCode': 200,
                            'headers': {'Content-Type': 'application/json'},
                            'body': json.dumps({'ok': True, 'acknowledged': True})
                        }


                    # if event_type == 'app_mention':
                    #     logger.info("Processing app mention")
                        
                    #     # Extract mention details
                    #     text = slack_event.get('text', '')
                    #     channel = slack_event.get('channel')
                    #     user = slack_event.get('user')
                    #     thread_ts = slack_event.get('thread_ts', slack_event.get('ts'))
                        
                    #     # Skip bot messages
                    #     if slack_event.get('bot_id'):
                    #         logger.info("Ignoring bot message")
                    #         return {
                    #             'statusCode': 200,
                    #             'headers': {'Content-Type': 'application/json'},
                    #             'body': json.dumps({'ok': True, 'bot_message': True})
                    #         }
                        
                    #     # Remove bot mention from text
                    #     clean_text = re.sub(r'<@[A-Z0-9]+>', '', text).strip()
                        
                    #     if clean_text:
                    #         # Check if this is a duplicate using event timestamp
                    #         event_key = f"mention_{slack_event.get('ts')}_{user}"
                    #         if is_duplicate_event(event_key):
                    #             logger.info(f"Skipping duplicate mention: {event_key}")
                    #             return {
                    #                 'statusCode': 200,
                    #                 'headers': {'Content-Type': 'application/json'},
                    #                 'body': json.dumps({'ok': True, 'duplicate': True})
                    #             }
                            
                    #         logger.info(f"Triggering async processing for: '{clean_text[:50]}...'")
                            
                    #         # Invoke this Lambda asynchronously
                    #         try:
                    #             import boto3
                    #             lambda_client = boto3.client('lambda')
                                
                    #             async_payload = {
                    #                 '_async_processing': True,  # Flag for async processing
                    #                 'process_type': 'app_mention',
                    #                 'text': clean_text,
                    #                 'channel': channel,
                    #                 'user': user,
                    #                 'thread_ts': thread_ts,
                    #                 'region': os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
                    #             }
                                
                    #             lambda_client.invoke(
                    #                 FunctionName=context.function_name,
                    #                 InvocationType='Event',  # Async - fire and forget
                    #                 Payload=json.dumps(async_payload)
                    #             )
                                
                    #             logger.info("Successfully triggered async processing")
                                
                    #         except Exception as e:
                    #             logger.error(f"Failed to trigger async processing: {e}")
                    #             # Still return 200 to prevent Slack retries
                        
                    #     # IMMEDIATELY return 200 to Slack
                    #     return {
                    #         'statusCode': 200,
                    #         'headers': {'Content-Type': 'application/json'},
                    #         'body': json.dumps({'ok': True, 'acknowledged': True})
                    #     }

            # Handle Slash Commands (URL-encoded)
            elif content_type.startswith('application/x-www-form-urlencoded'):
                logger.info("Processing Slack slash command")

                # Parse URL-encoded body
                body = parse_slack_request(event)

                # Extract parameters
                command = body.get('command', '')
                text = body.get('text', '')
                channel_id = body.get('channel_id', '')
                user_id = body.get('user_id', '')
                response_url = body.get('response_url', '')

                logger.info(f"Slash command details - Command: {command}, Text: {text}, User: {user_id}")

                try:
                    # Create client for simple commands
                    region = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
                    client = AWSMCPLambdaClient(region=region)

                    # Process commands
                    response_text = ""
                    
                    # Handle simple/quick commands synchronously
                    if command in ['/aws_help', '/bot_status', '/test', '/show_context',
                                  '/set_context', '/clear_context', '/clear_memory']:
                        logger.info(f"Handling built-in command: {command}")
                        result = handle_slash_command(command, text, user_id, channel_id, client)
                        response_text = result.get('response', 'Command processed.')
                        
                        # Clean up
                        client.cleanup()
                        
                        # Return immediate response for simple commands
                        return {
                            'statusCode': 200,
                            'headers': {'Content-Type': 'application/json'},
                            'body': json.dumps({
                                'response_type': 'in_channel',
                                'text': response_text
                            })
                        }
                        
                    elif command == '/aws':
                        # Handle /aws command
                        if not text:
                            response_text = "Please provide a query. Example: `/aws list all EC2 instances`"
                            return {
                                'statusCode': 200,
                                'headers': {'Content-Type': 'application/json'},
                                'body': json.dumps({
                                    'response_type': 'ephemeral',
                                    'text': response_text
                                })
                            }
                        else:
                            # For potentially long queries, process async
                            logger.info(f"Processing AWS query asynchronously: {text}")
                            
                            try:
                                import boto3
                                lambda_client = boto3.client('lambda')
                                
                                async_payload = {
                                    '_async_processing': True,
                                    'process_type': 'slash_command',
                                    'command': command,
                                    'text': text,
                                    'user_id': user_id,
                                    'channel_id': channel_id,
                                    'response_url': response_url,
                                    'region': os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
                                }
                                
                                lambda_client.invoke(
                                    FunctionName=context.function_name,
                                    InvocationType='Event',
                                    Payload=json.dumps(async_payload)
                                )
                                
                                # Return immediate acknowledgment
                                return {
                                    'statusCode': 200,
                                    'headers': {'Content-Type': 'application/json'},
                                    'body': json.dumps({
                                        'response_type': 'ephemeral',
                                        'text': '🤔 Processing your AWS query. Response will appear shortly...'
                                    })
                                }
                                
                            except Exception as e:
                                logger.error(f"Failed to trigger async: {e}")
                                return {
                                    'statusCode': 200,
                                    'headers': {'Content-Type': 'application/json'},
                                    'body': json.dumps({
                                        'response_type': 'ephemeral',
                                        'text': f'❌ Error: {str(e)}'
                                    })
                                }
                    else:
                        # Unknown command
                        response_text = f"Unknown command: {command}. Use `/aws_help` for available commands."
                        return {
                            'statusCode': 200,
                            'headers': {'Content-Type': 'application/json'},
                            'body': json.dumps({
                                'response_type': 'ephemeral',
                                'text': response_text
                            })
                        }

                except Exception as e:
                    logger.error(f"Error processing slash command: {e}", exc_info=True)
                    return {
                        'statusCode': 200,
                        'headers': {'Content-Type': 'application/json'},
                        'body': json.dumps({
                            'response_type': 'ephemeral',
                            'text': f"❌ Error: {str(e)}"
                        })
                    }

        # Handle direct invocation and other sources
        elif event_source == 'direct' or event_source == 'unknown':
            # Check if it has a query field (backward compatibility)
            if 'query' in event:
                logger.info("Processing direct query invocation")
                query = event['query']
                region = event.get('region', 'us-east-1')
                
                try:
                    client = AWSMCPLambdaClient(region=region)
                    result = client.process_query(query)
                    
                    return {
                        'statusCode': 200,
                        'headers': {'Content-Type': 'application/json'},
                        'body': json.dumps(result)
                    }
                except Exception as e:
                    logger.error(f"Error processing direct query: {e}")
                    return {
                        'statusCode': 500,
                        'body': json.dumps({'error': str(e)})
                    }
            else:
                logger.warning(f"Unknown event format")
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': 'Unknown event format'})
                }
                
        else:
            # Handle non-Slack events (EventBridge, SNS, etc.)
            logger.warning(f"Event source {event_source} not fully implemented")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': f'Event source {event_source} not fully implemented'})
            }

    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(f"Internal server error: {str(e)}", exc_info=True)

        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'error': f'Internal server error: {str(e)}',
                'execution_time_seconds': execution_time,
                'request_id': request_id
            })
        }


