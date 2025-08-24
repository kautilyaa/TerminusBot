import csv
import io
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import boto3
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import os
import requests

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

class PatchReportManager:
    """Manages patch report generation, storage, and distribution"""

    def __init__(self, region: str = 'us-east-1'):
        self.region = region
        self.s3_client = boto3.client('s3', region_name=region)
        self.ses_client = boto3.client('ses', region_name=region)
        self.dynamodb = boto3.resource('dynamodb', region_name=region)
        self.reports_bucket = os.environ.get('PATCH_REPORTS_BUCKET', 'aws-patch-reports')
        self.reports_table = os.environ.get('PATCH_REPORTS_TABLE', 'PatchReports')
        self._ensure_storage()

    def _ensure_storage(self):
        """Ensure S3 bucket and DynamoDB table exist"""
        # Create S3 bucket if doesn't exist
        try:
            self.s3_client.head_bucket(Bucket=self.reports_bucket)
        except:
            try:
                if self.region == 'us-east-1':
                    self.s3_client.create_bucket(Bucket=self.reports_bucket)
                else:
                    self.s3_client.create_bucket(
                        Bucket=self.reports_bucket,
                        CreateBucketConfiguration={'LocationConstraint': self.region}
                    )

                # Enable versioning
                self.s3_client.put_bucket_versioning(
                    Bucket=self.reports_bucket,
                    VersioningConfiguration={'Status': 'Enabled'}
                )

                # Set lifecycle policy for 90 days retention
                self.s3_client.put_bucket_lifecycle_configuration(
                    Bucket=self.reports_bucket,
                    LifecycleConfiguration={
                        'Rules': [{
                            'ID': 'DeleteOldReports',
                            'Status': 'Enabled',
                            'Expiration': {'Days': 90}
                        }]
                    }
                )
            except Exception as e:
                logger.warning(f"Could not create reports bucket: {e}")

        # Create DynamoDB table for report metadata
        try:
            table = self.dynamodb.create_table(
                TableName=self.reports_table,
                KeySchema=[
                    {'AttributeName': 'ReportId', 'KeyType': 'HASH'},
                    {'AttributeName': 'Timestamp', 'KeyType': 'RANGE'}
                ],
                AttributeDefinitions=[
                    {'AttributeName': 'ReportId', 'AttributeType': 'S'},
                    {'AttributeName': 'Timestamp', 'AttributeType': 'S'},
                    {'AttributeName': 'WindowId', 'AttributeType': 'S'}
                ],
                GlobalSecondaryIndexes=[
                    {
                        'IndexName': 'WindowIdIndex',
                        'Keys': [
                            {'AttributeName': 'WindowId', 'KeyType': 'HASH'},
                            {'AttributeName': 'Timestamp', 'KeyType': 'RANGE'}
                        ],
                        'Projection': {'ProjectionType': 'ALL'}
                    }
                ],
                BillingMode='PAY_PER_REQUEST'
            )
            table.wait_until_exists()
        except self.dynamodb.meta.client.exceptions.ResourceInUseException:
            logger.info(f"Reports table already exists")

    def generate_patch_csv_report(self, patch_data: Dict) -> Tuple[str, bytes]:
        """Generate CSV report from patch data"""

        # Create CSV in memory
        csv_buffer = io.StringIO()

        # Define CSV headers based on report type
        if 'instanceDetails' in patch_data:
            # Detailed maintenance window report
            fieldnames = [
                'Instance ID', 'Instance Name', 'Environment', 'Application',
                'Platform', 'Execution Status', 'Compliance Status',
                'Installed Count', 'Pending Reboot Count', 'Missing Count',
                'Failed Count', 'Packages Installed', 'Errors', 'Timestamp'
            ]

            writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
            writer.writeheader()

            for instance in patch_data.get('instanceDetails', []):
                compliance = instance.get('compliance', {})
                packages = ', '.join([p.get('name', '') for p in instance.get('packagesInstalled', [])])

                writer.writerow({
                    'Instance ID': instance.get('instanceId', 'N/A'),
                    'Instance Name': instance.get('name', 'N/A'),
                    'Environment': instance.get('environment', 'N/A'),
                    'Application': instance.get('application', 'N/A'),
                    'Platform': instance.get('platform', 'N/A'),
                    'Execution Status': instance.get('executionStatus', 'N/A'),
                    'Compliance Status': instance.get('category', 'unknown'),
                    'Installed Count': compliance.get('installedCount', 0),
                    'Pending Reboot Count': compliance.get('installedPendingRebootCount', 0),
                    'Missing Count': compliance.get('missingCount', 0),
                    'Failed Count': compliance.get('failedCount', 0),
                    'Packages Installed': packages,
                    'Errors': instance.get('errors', ''),
                    'Timestamp': patch_data.get('timestamp', datetime.now().isoformat())
                })

            # Add package summary sheet
            csv_buffer.write('\\n\\n--- PACKAGE SUMMARY ---\\n')
            package_headers = ['Package Name', 'Version(s)', 'Instance Count', 'Classification']
            writer = csv.DictWriter(csv_buffer, fieldnames=package_headers)
            writer.writeheader()

            for package in patch_data.get('packageUpdates', []):
                writer.writerow({
                    'Package Name': package.get('name', 'N/A'),
                    'Version(s)': ', '.join(package.get('versions', [])),
                    'Instance Count': package.get('instanceCount', 0),
                    'Classification': package.get('classification', 'N/A')
                })

        else:
            # Simple patch status report
            fieldnames = [
                'Instance ID', 'Instance Name', 'Environment', 'State',
                'Compliance Status', 'Installed', 'Pending Reboot',
                'Missing', 'Failed', 'Last Update Time'
            ]

            writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
            writer.writeheader()

            for instance in patch_data.get('instances', []):
                writer.writerow({
                    'Instance ID': instance.get('InstanceId', 'N/A'),
                    'Instance Name': instance.get('Name', 'N/A'),
                    'Environment': instance.get('Environment', 'N/A'),
                    'State': instance.get('State', 'N/A'),
                    'Compliance Status': instance.get('ComplianceStatus', 'N/A'),
                    'Installed': instance.get('InstalledPatches', 0),
                    'Pending Reboot': instance.get('InstalledPendingRebootPatches', 0),
                    'Missing': instance.get('MissingPatches', 0),
                    'Failed': instance.get('FailedPatches', 0),
                    'Last Update Time': instance.get('OperationEndTime', 'N/A')
                })

        # Get CSV content
        csv_content = csv_buffer.getvalue()
        csv_bytes = csv_content.encode('utf-8')

        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        window_id = patch_data.get('windowId', 'manual')
        filename = f"patch_report_{window_id}_{timestamp}.csv"

        csv_buffer.close()

        return filename, csv_bytes

    def store_report(self, report_id: str, window_id: str, csv_bytes: bytes,
                    filename: str, metadata: Dict) -> str:
        """Store report in S3 and track in DynamoDB"""

        try:
            # Upload to S3
            s3_key = f"reports/{window_id}/{filename}"

            self.s3_client.put_object(
                Bucket=self.reports_bucket,
                Key=s3_key,
                Body=csv_bytes,
                ContentType='text/csv',
                Metadata={
                    'window-id': window_id,
                    'report-id': report_id,
                    'generated-at': datetime.now().isoformat()
                }
            )

            # Generate presigned URL (valid for 7 days)
            presigned_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.reports_bucket, 'Key': s3_key},
                ExpiresIn=604800  # 7 days
            )

            # Store metadata in DynamoDB
            table = self.dynamodb.Table(self.reports_table)
            table.put_item(
                Item={
                    'ReportId': report_id,
                    'Timestamp': datetime.now().isoformat(),
                    'WindowId': window_id,
                    'Filename': filename,
                    'S3Bucket': self.reports_bucket,
                    'S3Key': s3_key,
                    'PresignedUrl': presigned_url,
                    'UrlExpiry': (datetime.now() + timedelta(days=7)).isoformat(),
                    'Metadata': metadata,
                    'ReportSize': len(csv_bytes),
                    'TTL': int((datetime.now() + timedelta(days=90)).timestamp())
                }
            )

            logger.info(f"Report stored: s3://{self.reports_bucket}/{s3_key}")
            return presigned_url

        except Exception as e:
            logger.error(f"Failed to store report: {e}")
            raise

    def send_email_report(self, recipients: List[str], subject: str,
                         body: str, csv_bytes: bytes, filename: str) -> bool:
        """Send email with CSV attachment"""

        try:
            sender = os.environ.get('SES_SENDER_EMAIL', 'noreply@yourcompany.com')

            # Create message
            msg = MIMEMultipart()
            msg['Subject'] = subject
            msg['From'] = sender
            msg['To'] = ', '.join(recipients)

            # Add body
            body_part = MIMEText(body, 'html')
            msg.attach(body_part)

            # Add CSV attachment
            attachment = MIMEBase('text', 'csv')
            attachment.set_payload(csv_bytes)
            encoders.encode_base64(attachment)
            attachment.add_header(
                'Content-Disposition',
                f'attachment; filename={filename}'
            )
            msg.attach(attachment)

            # Send email
            response = self.ses_client.send_raw_email(
                Source=sender,
                Destinations=recipients,
                RawMessage={'Data': msg.as_string()}
            )

            logger.info(f"Email sent to {recipients}: {response['MessageId']}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    def send_slack_file(self, channel: str, csv_bytes: bytes, filename: str,
                       title: str, initial_comment: str) -> bool:
        """Upload CSV file to Slack"""

        try:
            slack_token = os.environ.get('SLACK_BOT_TOKEN')

            if not slack_token:
                logger.warning("No Slack token available for file upload")
                return False

            url = "<https://slack.com/api/files.upload>"

            # Prepare the file upload
            files = {'file': (filename, csv_bytes, 'text/csv')}

            data = {
                'channels': channel,
                'title': title,
                'initial_comment': initial_comment,
                'filename': filename
            }

            headers = {
                'Authorization': f'Bearer {slack_token}'
            }

            response = requests.post(url, headers=headers, data=data, files=files)
            result = response.json()

            if result.get('ok'):
                logger.info(f"File uploaded to Slack: {filename}")
                return True
            else:
                logger.error(f"Slack file upload failed: {result.get('error')}")
                return False

        except Exception as e:
            logger.error(f"Failed to upload file to Slack: {e}")
            return False

    def get_report_by_id(self, report_id: str) -> Dict:
        """Retrieve report metadata by ID"""

        try:
            table = self.dynamodb.Table(self.reports_table)
            response = table.query(
                KeyConditionExpression='ReportId = :rid',
                ExpressionAttributeValues={':rid': report_id}
            )

            if response['Items']:
                return response['Items'][0]
            return None

        except Exception as e:
            logger.error(f"Failed to get report: {e}")
            return None

    def get_reports_by_window(self, window_id: str, limit: int = 10) -> List[Dict]:
        """Get reports for a specific maintenance window"""

        try:
            table = self.dynamodb.Table(self.reports_table)
            response = table.query(
                IndexName='WindowIdIndex',
                KeyConditionExpression='WindowId = :wid',
                ExpressionAttributeValues={':wid': window_id},
                ScanIndexForward=False,  # Most recent first
                Limit=limit
            )

            return response.get('Items', [])

        except Exception as e:
            logger.error(f"Failed to get reports by window: {e}")
            return []

    def generate_and_distribute_report(self, patch_data: Dict, window_id: str,
                                      email_recipients: List[str] = None,
                                      slack_channel: str = None) -> Dict:
        """Generate, store, and distribute patch report"""

        try:
            # Generate report ID
            report_id = f"report_{window_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

            # Generate CSV
            filename, csv_bytes = self.generate_patch_csv_report(patch_data)

            # Store in S3 and DynamoDB
            presigned_url = self.store_report(
                report_id=report_id,
                window_id=window_id,
                csv_bytes=csv_bytes,
                filename=filename,
                metadata={
                    'total_instances': patch_data.get('summary', {}).get('totalInstances', 0),
                    'successful': patch_data.get('summary', {}).get('successfulInstances', 0),
                    'failed': patch_data.get('summary', {}).get('failedInstances', 0),
                    'execution_status': patch_data.get('executionStatus', 'N/A')
                }
            )

            # Prepare summary for notifications
            summary = patch_data.get('summary', {})
            summary_text = f"""
            Patch Report Summary:
            • Window: {window_id}
            • Total Instances: {summary.get('totalInstances', 0)}
            • Successful: {summary.get('successfulInstances', 0)}
            • Failed: {summary.get('failedInstances', 0)}
            • Pending Reboot: {summary.get('instancesPendingReboot', 0)}
            """

            # Send email if recipients provided
            if email_recipients:
                email_body = f"""
                <html>
                <body>
                <h2>AWS Patch Maintenance Report</h2>
                <p>Please find attached the detailed patch report for maintenance window: <b>{window_id}</b></p>

                <h3>Summary:</h3>
                <ul>
                    <li>Total Instances: {summary.get('totalInstances', 0)}</li>
                    <li>Successful: {summary.get('successfulInstances', 0)}</li>
                    <li>Failed: {summary.get('failedInstances', 0)}</li>
                    <li>Pending Reboot: {summary.get('instancesPendingReboot', 0)}</li>
                </ul>

                <p>You can also download the report from: <a href="{presigned_url}">Download Report</a></p>
                <p><i>This link will expire in 7 days.</i></p>
                </body>
                </html>
                """

                self.send_email_report(
                    recipients=email_recipients,
                    subject=f"Patch Report - {window_id} - {datetime.now().strftime('%Y-%m-%d')}",
                    body=email_body,
                    csv_bytes=csv_bytes,
                    filename=filename
                )

            # Upload to Slack if channel provided
            if slack_channel:
                slack_comment = f"""📊 *Patch Maintenance Report*

{summary_text}

📥 *Download Link:* {presigned_url}
_Link expires in 7 days_

Use `/aws get patch report {report_id}` to retrieve this report later.
                """

                self.send_slack_file(
                    channel=slack_channel,
                    csv_bytes=csv_bytes,
                    filename=filename,
                    title=f"Patch Report - {window_id}",
                    initial_comment=slack_comment
                )

            return {
                'success': True,
                'report_id': report_id,
                'filename': filename,
                'presigned_url': presigned_url,
                's3_location': f"s3://{self.reports_bucket}/reports/{window_id}/{filename}",
                'message': 'Report generated and distributed successfully'
            }

        except Exception as e:
            logger.error(f"Failed to generate and distribute report: {e}")
            return {
                'success': False,
                'error': str(e)
            }
