




import json
import boto3
import logging
from event_manager import EventManager
from sns_alert import send_sns_alert
import os
import re

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    dict_json = {"statusCode": 200, "body": "Hello from Lambda!"}
    logger.info(f"Welcome: {dict_json}")
    logger.info(f"Received event: {json.dumps(event)}")
    
    try:
        logger.info(f"Received event: {json.dumps(event)}")
        
        # Create Bedrock client using Lambda's IAM role
        logger.info("Initializing Bedrock client...")
        bedrock_client = boto3.client(
            service_name="bedrock-runtime",
            region_name=event.get('region', 'us-east-1')
        )
        logger.info("Bedrock client initialized successfully")
        
        # Initialize EventManager with the Bedrock client
        event_manager = EventManager(bedrock_client)
        
        # Process the event using EventManager
        logger.info("Processing event with EventManager...")
        result = event_manager.process_event(event)
        logger.info("Successfully processed event")
        
        # Check if this is a disk space related alarm
        is_disk_alarm = is_disk_space_alarm(event)
        logger.info(f"Is disk space alarm: {is_disk_alarm}")
        
        if is_disk_alarm:
            # Send to disk space management Lambda
            logger.info("Processing disk space alarm through specialized workflow")
            disk_response = send_to_disk_management_lambda(event, result, context)
            logger.info(f"Disk management Lambda response: {disk_response}")
        else:
            # Handle regular alarms
            logger.info("Processing regular alarm")
            
        # Use Bedrock to format the result as the email body for the SNS alert
        email_subject = f"Lambda Function Execution Complete: {event.get('alarm_name', 'N/A')} : {event.get('id', 'N/A')}"

        # Minimal prompt: just ask Bedrock to format the given result for an on-call email
        bedrock_email_prompt = f"Format the following result as a professional on-call incident email body for sns alert, without changing the content:\n\n{json.dumps(result, indent=2)}"
        try:
            bedrock_email_response = bedrock_client.invoke_model(
                modelId="anthropic.claude-3-sonnet-20240229-v1:0",
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 1000,
                    "temperature": 0.5,
                    "messages": [
                        {"role": "user", "content": bedrock_email_prompt}
                    ]
                })
            )
            bedrock_email_body = json.loads(bedrock_email_response["body"].read())["content"][0]["text"]
        except Exception as e:
            logger.error(f"Failed to generate email body with Bedrock: {str(e)}")
            bedrock_email_body = "Error generating formatted email body. Please see Lambda logs."

        email_body = f"""{bedrock_email_body}"""
        
        logger.info(f"Email body: {email_body}")

        # Send SNS alert if topic ARN is set
        sns_topic_arn = os.environ.get('SNS_TOPIC_ARN')
        logger.info(f"SNS topic ARN: {sns_topic_arn}")
        if sns_topic_arn:
            send_sns_alert(email_subject, email_body, sns_topic_arn)

        dict_json = {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps({
                "message": "Success",
                "response": result,
                "event": event,
                "disk_alarm_processed": is_disk_alarm
            })
        }
        logger.info(f"Returning response: {json.dumps(result)}")
        return dict_json
        
    except Exception as e:
        logger.error(f"Error occurred: {str(e)}", exc_info=True)
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps({
                "message": "Error",
                "error": str(e),
                "event": event
            })
        }

def is_disk_space_alarm(event):
    """Check if the alarm is related to disk space"""
    alarm_indicators = [
        'disk', 'storage', 'space', 'full', 'capacity', 
        'filesystem', 'mount', 'volume', 'partition',
        '/var', '/tmp', '/home', '/opt', 'DiskSpaceUtilization'
    ]
    
    # Check alarm name
    alarm_name = event.get('alarm_name', '').lower()
    if any(indicator in alarm_name for indicator in alarm_indicators):
        return True
    
    # Check alarm description
    alarm_description = event.get('AlarmDescription', '').lower()
    if any(indicator in alarm_description for indicator in alarm_indicators):
        return True
    
    # Check metric name
    metric_name = event.get('MetricName', '').lower()
    if any(indicator in metric_name for indicator in alarm_indicators):
        return True
    
    return False

def send_to_disk_management_lambda(original_event, analysis_result, context):
    """Send disk space alarm to specialized disk management Lambda"""
    try:
        # Initialize Lambda client
        lambda_client = boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        
        # Get Disk Management Lambda function name from environment variable
        disk_lambda_name = os.environ.get('DISK_MANAGEMENT_LAMBDA_NAME', 'disk-space-management-lambda')
        
        # Get Slack channel ID from environment variable or event
        slack_channel_id = os.environ.get('SLACK_CHANNEL_ID') or original_event.get('slack_channel_id', 'C1234567890')
        
        # Prepare the payload for Disk Management Lambda
        disk_payload = {
            "alarm_event": original_event,
            "analysis_result": analysis_result,
            "metadata": {
                "timestamp": context.aws_request_id,
                "processing_lambda": context.function_name,
                "region": original_event.get('region', 'us-east-1')
            },
            "slack_config": {
                "channel_id": slack_channel_id,
                "user_id": "system"
            }
        }
        
        # Invoke Disk Management Lambda asynchronously
        response = lambda_client.invoke(
            FunctionName=disk_lambda_name,
            InvocationType='Event',  # Asynchronous invocation
            Payload=json.dumps(disk_payload)
        )
        
        logger.info(f"Successfully invoked Disk Management Lambda: {disk_lambda_name}")
        return {
            "success": True,
            "status_code": response['StatusCode'],
            "disk_lambda_name": disk_lambda_name,
            "channel_id": slack_channel_id
        }
        
    except Exception as e:
        logger.error(f"Error invoking Disk Management Lambda: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }
    

# Step 2-6: Disk Space Management Lambda



import json
import boto3
import logging
import time
import os
import re
from datetime import datetime, timezone
from slack_utils import send_slack_message, send_slack_message_with_buttons
from sns_alert import send_sns_alert

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """Main handler for disk space management workflow"""
    logger.info(f"Disk Space Management Lambda started - RequestID: {context.aws_request_id}")
    logger.info(f"Received event: {json.dumps(event, default=str)}")
    
    try:
        # Extract information from the event
        alarm_event = event.get('alarm_event', {})
        analysis_result = event.get('analysis_result', {})
        metadata = event.get('metadata', {})
        slack_config = event.get('slack_config', {})
        
        # Extract instance information
        instance_id = extract_instance_id(alarm_event)
        region = metadata.get('region', 'us-east-1')
        
        if not instance_id:
            logger.error("Could not extract instance ID from alarm event")
            return create_error_response("Instance ID not found in alarm event")
        
        logger.info(f"Processing disk space alarm for instance: {instance_id}")
        
        # Step 1: Already triggered (CloudWatch alarm)
        # Step 2: Identify which file/directory is causing the issue
        disk_analysis = identify_large_files(instance_id, region)
        
        if not disk_analysis.get('success'):
            logger.error(f"Failed to identify large files: {disk_analysis.get('error')}")
            return create_error_response(f"Failed to analyze disk usage: {disk_analysis.get('error')}")
        
        # Step 3 & 4: Process files based on type
        file_processing_result = process_identified_files(instance_id, region, disk_analysis)
        
        # Step 5: Handle user interaction if needed
        if file_processing_result.get('requires_user_input'):
            send_user_interaction_request(file_processing_result, slack_config, alarm_event, context)
        
        # Step 6: Send summary
        send_summary_notification(alarm_event, disk_analysis, file_processing_result, slack_config)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Disk space management workflow completed',
                'instance_id': instance_id,
                'disk_analysis': disk_analysis,
                'processing_result': file_processing_result
            })
        }
        
    except Exception as e:
        logger.error(f"Error in disk space management: {str(e)}", exc_info=True)
        return create_error_response(str(e))

def extract_instance_id(alarm_event):
    """Extract instance ID from alarm event"""
    # Try multiple sources for instance ID
    if 'instance_id' in alarm_event:
        return alarm_event['instance_id']
    
    # Look in alarm description
    alarm_description = alarm_event.get('AlarmDescription', '')
    instance_match = re.search(r'i-[a-f0-9]{8,17}', alarm_description)
    if instance_match:
        return instance_match.group()
    
    # Look in dimensions
    dimensions = alarm_event.get('Dimensions', [])
    for dimension in dimensions:
        if dimension.get('Name') == 'InstanceId':
            return dimension.get('Value')
    
    return None

def identify_large_files(instance_id, region):
    """Step 2: Identify which files are causing disk space issues"""
    try:
        ssm_client = boto3.client('ssm', region_name=region)
        
        # Command to find large files and directories
        disk_analysis_command = '''
#!/bin/bash
echo "=== DISK USAGE ANALYSIS ==="
echo "Current disk usage:"
df -h

echo ""
echo "=== TOP 20 LARGEST DIRECTORIES ==="
du -h --max-depth=2 / 2>/dev/null | sort -hr | head -20

echo ""
echo "=== TOP 20 LARGEST FILES ==="
find / -type f -size +10M 2>/dev/null | xargs ls -lh | sort -k5 -hr | head -20

echo ""
echo "=== LOG FILES ANALYSIS ==="
echo "Large log files (>10MB):"
find /var/log /tmp /opt -name "*.log" -size +10M 2>/dev/null | xargs ls -lh 2>/dev/null | sort -k5 -hr

echo ""
echo "=== ROTATABLE LOG FILES ==="
find /var/log -name "*.log" -size +10M 2>/dev/null | while read file; do
    if [[ "\$file" != *".gz" ]] && [[ "\$file" != *".zip" ]]; then
        echo "ROTATABLE: \$file (\$(du -h "\$file" | cut -f1))"
    fi
done

echo ""
echo "=== SYSTEM TEMP FILES ==="
find /tmp -type f -size +1M 2>/dev/null | xargs ls -lh 2>/dev/null | sort -k5 -hr | head -10
'''
        
        # Execute the command
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={'commands': [disk_analysis_command]},
            TimeoutSeconds=300
        )
        
        command_id = response['Command']['CommandId']
        
        # Wait for completion
        time.sleep(10)
        
        # Get results
        output_response = ssm_client.get_command_invocation(
            CommandId=command_id,
            InstanceId=instance_id
        )
        
        if output_response['Status'] == 'Success':
            analysis_output = output_response['StandardOutputContent']
            return {
                'success': True,
                'instance_id': instance_id,
                'analysis_output': analysis_output,
                'files_identified': parse_disk_analysis(analysis_output)
            }
        else:
            return {
                'success': False,
                'error': f"Command failed: {output_response.get('StandardErrorContent', 'Unknown error')}"
            }
            
    except Exception as e:
        logger.error(f"Error identifying large files: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def parse_disk_analysis(analysis_output):
    """Parse the disk analysis output to identify files"""
    files_info = {
        'log_files': [],
        'other_large_files': [],
        'temp_files': [],
        'rotatable_logs': []
    }
    
    lines = analysis_output.split('\n')
    current_section = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if 'LOG FILES ANALYSIS' in line:
            current_section = 'log_files'
        elif 'TOP 20 LARGEST FILES' in line:
            current_section = 'other_files'
        elif 'ROTATABLE LOG FILES' in line:
            current_section = 'rotatable'
        elif 'SYSTEM TEMP FILES' in line:
            current_section = 'temp_files'
        elif line.startswith('ROTATABLE:'):
            # Extract rotatable log file info
            match = re.search(r'ROTATABLE: (.+?) $(.+?)$', line)
            if match:
                files_info['rotatable_logs'].append({
                    'path': match.group(1),
                    'size': match.group(2),
                    'type': 'log'
                })
        elif current_section and line and not line.startswith('==='):
            # Parse file lines (ls -lh format)
            if current_section in ['log_files', 'other_files', 'temp_files']:
                parts = line.split()
                if len(parts) >= 9:
                    size = parts[4]
                    filename = ' '.join(parts[8:])
                    
                    file_info = {
                        'path': filename,
                        'size': size,
                        'type': 'log' if any(ext in filename.lower() for ext in ['.log', 'syslog', 'messages']) else 'other'
                    }
                    
                    if current_section == 'log_files':
                        files_info['log_files'].append(file_info)
                    elif current_section == 'temp_files':
                        files_info['temp_files'].append(file_info)
                    else:
                        files_info['other_large_files'].append(file_info)
    
    return files_info

def process_identified_files(instance_id, region, disk_analysis):
    """Steps 3 & 4: Process files based on type"""
    try:
        files_info = disk_analysis.get('files_identified', {})
        processing_results = {
            'log_rotations_performed': [],
            'files_requiring_user_input': [],
            'temp_files_cleaned': [],
            'requires_user_input': False
        }
        
        # Step 3: Handle log files - perform automatic log rotation
        rotatable_logs = files_info.get('rotatable_logs', [])
        large_log_files = [f for f in files_info.get('log_files', []) if is_size_large(f.get('size', '0'))]
        
        all_log_files = rotatable_logs + large_log_files
        
        for log_file in all_log_files:
            rotation_result = rotate_log_file(instance_id, region, log_file['path'])
            if rotation_result.get('success'):
                processing_results['log_rotations_performed'].append({
                    'file': log_file['path'],
                    'original_size': log_file['size'],
                    'result': rotation_result
                })
        
        # Clean up temp files automatically
        temp_files = files_info.get('temp_files', [])
        for temp_file in temp_files:
            if '/tmp/' in temp_file['path']:
                cleanup_result = cleanup_temp_file(instance_id, region, temp_file['path'])
                if cleanup_result.get('success'):
                    processing_results['temp_files_cleaned'].append({
                        'file': temp_file['path'],
                        'size': temp_file['size'],
                        'result': cleanup_result
                    })
        
        # Step 4: Handle other large files - require user input
        other_files = files_info.get('other_large_files', [])
        for file_info in other_files:
            if is_size_large(file_info.get('size', '0')):
                file_details = get_file_details(instance_id, region, file_info['path'])
                processing_results['files_requiring_user_input'].append({
                    'file': file_info['path'],
                    'size': file_info['size'],
                    'details': file_details
                })
        
        # Set flag if user input is needed
        if processing_results['files_requiring_user_input']:
            processing_results['requires_user_input'] = True
        
        return processing_results
        
    except Exception as e:
        logger.error(f"Error processing files: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def rotate_log_file(instance_id, region, log_file_path):
    """Step 3: Rotate a log file (compress and truncate)"""
    try:
        ssm_client = boto3.client('ssm', region_name=region)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        rotation_command = f'''
#!/bin/bash
LOG_FILE="{log_file_path}"
TIMESTAMP="{timestamp}"

if [ -f "\$LOG_FILE" ]; then
    echo "Rotating log file: \$LOG_FILE"
    
    # Create compressed backup in /tmp
    BACKUP_FILE="/tmp/\$(basename \$LOG_FILE)_\$TIMESTAMP.gz"
    
    # Copy and compress the log file
    cp "\$LOG_FILE" "/tmp/\$(basename \$LOG_FILE)_temp_\$TIMESTAMP"
    gzip "/tmp/\$(basename \$LOG_FILE)_temp_\$TIMESTAMP"
    mv "/tmp/\$(basename \$LOG_FILE)_temp_\$TIMESTAMP.gz" "\$BACKUP_FILE"
    
    # Truncate the original log file
    > "\$LOG_FILE"
    
    echo "Log rotation completed:"
    echo "Original file: \$LOG_FILE (now empty)"
    echo "Backup created: \$BACKUP_FILE"
    echo "Backup size: \$(du -h \$BACKUP_FILE | cut -f1)"
    
    # Verify the rotation
    echo "Current log file size: \$(du -h \$LOG_FILE | cut -f1)"
else
    echo "Error: Log file \$LOG_FILE not found"
    exit 1
fi
'''
        
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={'commands': [rotation_command]},
            TimeoutSeconds=300
        )
        
        command_id = response['Command']['CommandId']
        time.sleep(5)
        
        output_response = ssm_client.get_command_invocation(
            CommandId=command_id,
            InstanceId=instance_id
        )
        
        if output_response['Status'] == 'Success':
            return {
                'success': True,
                'output': output_response['StandardOutputContent'],
                'backup_location': f"/tmp/{os.path.basename(log_file_path)}_{timestamp}.gz"
            }
        else:
            return {
                'success': False,
                'error': output_response.get('StandardErrorContent', 'Unknown error')
            }
            
    except Exception as e:
        logger.error(f"Error rotating log file {log_file_path}: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def cleanup_temp_file(instance_id, region, file_path):
    """Clean up temporary files"""
    try:
        ssm_client = boto3.client('ssm', region_name=region)
        
        cleanup_command = f'''
#!/bin/bash
FILE_PATH="{file_path}"

if [ -f "\$FILE_PATH" ]; then
    echo "Cleaning up temp file: \$FILE_PATH"
    FILE_SIZE=\$(du -h "\$FILE_PATH" | cut -f1)
    rm -f "\$FILE_PATH"
    echo "Removed temp file: \$FILE_PATH (was \$FILE_SIZE)"
else
    echo "File not found: \$FILE_PATH"
fi
'''
        
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={'commands': [cleanup_command]},
            TimeoutSeconds=60
        )
        
        command_id = response['Command']['CommandId']
        time.sleep(3)
        
        output_response = ssm_client.get_command_invocation(
            CommandId=command_id,
            InstanceId=instance_id
        )
        
        return {
            'success': output_response['Status'] == 'Success',
            'output': output_response.get('StandardOutputContent', ''),
            'error': output_response.get('StandardErrorContent', '')
        }
        
    except Exception as e:
        logger.error(f"Error cleaning up temp file {file_path}: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def get_file_details(instance_id, region, file_path):
    """Get detailed information about a file"""
    try:
        ssm_client = boto3.client('ssm', region_name=region)
        
        details_command = f'''
#!/bin/bash
FILE_PATH="{file_path}"

if [ -e "\$FILE_PATH" ]; then
    echo "=== FILE DETAILS ==="
    echo "Path: \$FILE_PATH"
    echo "Size: \$(du -h \$FILE_PATH | cut -f1)"
    echo "Type: \$(file \$FILE_PATH)"
    echo "Last modified: \$(stat -c %y \$FILE_PATH)"
    echo "Last accessed: \$(stat -c %x \$FILE_PATH)"
    echo "Owner: \$(stat -c %U:%G \$FILE_PATH)"
    echo "Permissions: \$(stat -c %A \$FILE_PATH)"
    
    echo ""
    echo "=== AGE ANALYSIS ==="
    DAYS_OLD=\$(( (\$(date +%s) - \$(stat -c %Y \$FILE_PATH)) / 86400 ))
    echo "File is \$DAYS_OLD days old"
    
    if [ \$DAYS_OLD -gt 30 ]; then
        echo "Assessment: OLD file (>30 days)"
    elif [ \$DAYS_OLD -gt 7 ]; then
        echo "Assessment: RECENT file (7-30 days)"
    else
        echo "Assessment: NEW file (<7 days)"
    fi
else
    echo "File not found: \$FILE_PATH"
fi
'''
        
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={'commands': [details_command]},
            TimeoutSeconds=60
        )
        
        command_id = response['Command']['CommandId']
        time.sleep(3)
        
        output_response = ssm_client.get_command_invocation(
            CommandId=command_id,
            InstanceId=instance_id
        )
        
        if output_response['Status'] == 'Success':
            return parse_file_details(output_response['StandardOutputContent'])
        else:
            return {'error': 'Could not get file details'}
            
    except Exception as e:
        logger.error(f"Error getting file details for {file_path}: {str(e)}")
        return {'error': str(e)}

def parse_file_details(details_output):
    """Parse file details output"""
    details = {}
    lines = details_output.split('\n')
    
    for line in lines:
        if ':' in line and not line.startswith('==='):
            key, value = line.split(':', 1)
            details[key.strip()] = value.strip()
    
    return details

def is_size_large(size_str):
    """Check if a file size is considered large"""
    if not size_str:
        return False
    
    # Convert size to MB for comparison
    size_str = size_str.upper()
    if 'G' in size_str:
        return True  # Any GB file is large
    elif 'M' in size_str:
        try:
            size_mb = float(re.findall(r'[\d.]+', size_str)[0])
            return size_mb > 50  # >50MB is considered large
        except:
            return False
    
    return False

def send_user_interaction_request(processing_result, slack_config, alarm_event, context):
    """Step 5: Send interactive message to Slack for user decision"""
    try:
        channel_id = slack_config.get('channel_id')
        if not channel_id:
            logger.warning("No Slack channel configured for user interaction")
            return
        
        files_needing_decision = processing_result.get('files_requiring_user_input', [])
        
        for file_info in files_needing_decision:
            file_path = file_info['file']
            file_size = file_info['size']
            file_details = file_info.get('details', {})
            
            # Determine if file is old or new
            age_assessment = "Unknown age"
            if 'Assessment' in file_details:
                age_assessment = file_details['Assessment']
            
            message = f"""
🔍 **Large File Detected - Action Required**

**File Information:**
• Path: `{file_path}`
• Size: `{file_size}`
• {age_assessment}
• Owner: {file_details.get('Owner', 'Unknown')}
• Last Modified: {file_details.get('Last modified', 'Unknown')}

**Instance:** {alarm_event.get('instance_id', 'Unknown')}
**Alarm:** {alarm_event.get('alarm_name', 'Disk Space Alert')}

**What would you like to do with this file?**
"""
            
            # Create callback data
            callback_data = {
                'action': 'file_decision',
                'file_path': file_path,
                'instance_id': alarm_event.get('instance_id'),
                'lambda_request_id': context.aws_request_id
            }
            
            # Send interactive message
            send_slack_message_with_buttons(
                channel_id=channel_id,
                message=message,
                buttons=[
                    {
                        'text': '🗑️ Delete File',
                        'value': 'delete',
                        'style': 'danger',
                        'callback_data': {**callback_data, 'decision': 'delete'}
                    },
                    {
                        'text': '📦 Archive File',
                        'value': 'archive',
                        'style': 'primary',
                        'callback_data': {**callback_data, 'decision': 'archive'}
                    },
                    {
                        'text': '⏭️ Keep File',
                        'value': 'keep',
                        'style': 'default',
                        'callback_data': {**callback_data, 'decision': 'keep'}
                    }
                ]
            )
        
        logger.info(f"Sent user interaction requests for {len(files_needing_decision)} files")
        
    except Exception as e:
        logger.error(f"Error sending user interaction request: {str(e)}")

def send_summary_notification(alarm_event, disk_analysis, processing_result, slack_config):
    """Step 6: Send summary notification"""
    try:
        # Prepare summary data
        instance_id = alarm_event.get('instance_id', 'Unknown')
        alarm_name = alarm_event.get('alarm_name', 'Disk Space Alert')
        
        log_rotations = processing_result.get('log_rotations_performed', [])
        temp_cleanups = processing_result.get('temp_files_cleaned', [])
        user_input_files = processing_result.get('files_requiring_user_input', [])
        
        # Create summary message
        summary_message = f"""
🔧 **Disk Space Management Summary**

**Alarm Details:**
• Instance: `{instance_id}`
• Alert: {alarm_name}
• Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}

**Actions Performed:**

📄 **Log Rotations ({len(log_rotations)}):**
"""
        
        for rotation in log_rotations:
            summary_message += f"• Rotated `{rotation['file']}` ({rotation['original_size']}) ✅\n"
        
        if not log_rotations:
            summary_message += "• No log files required rotation\n"
        
        summary_message += f"""
🧹 **Temp File Cleanup ({len(temp_cleanups)}):**
"""
        
        for cleanup in temp_cleanups:
            summary_message += f"• Cleaned `{cleanup['file']}` ({cleanup['size']}) ✅\n"
        
        if not temp_cleanups:
            summary_message += "• No temp files cleaned\n"
        
        summary_message += f"""
❓ **Pending User Decisions ({len(user_input_files)}):**
"""
        
        for file_info in user_input_files:
            summary_message += f"• `{file_info['file']}` ({file_info['size']}) - Awaiting decision\n"
        
        if not user_input_files:
            summary_message += "• No files require user decisions\n"
        
        # Send to Slack
        channel_id = slack_config.get('channel_id')
        if channel_id:
            send_slack_message(channel_id, summary_message)
        
        # Send email notification if configured
        sns_topic_arn = os.environ.get('SNS_TOPIC_ARN')
        if sns_topic_arn:
            email_subject = f"Disk Space Management Summary - {instance_id}"
            send_sns_alert(email_subject, summary_message, sns_topic_arn)
        
        logger.info("Summary notifications sent successfully")
        
    except Exception as e:
        logger.error(f"Error sending summary notification: {str(e)}")

def create_error_response(error_message):
    """Create standardized error response"""
    return {
        'statusCode': 500,
        'body': json.dumps({
            'error': error_message,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
    }