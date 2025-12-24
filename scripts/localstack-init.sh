#!/bin/bash
# LocalStack initialization script
# Creates S3 buckets and SQS queues for local development

set -e

echo "Initializing LocalStack resources..."

# Wait for LocalStack to be ready
sleep 5

# Create S3 bucket
awslocal s3 mb s3://heliograph-documents
echo "Created S3 bucket: heliograph-documents"

# Configure CORS for S3 bucket (required for browser uploads)
awslocal s3api put-bucket-cors --bucket heliograph-documents --cors-configuration '{
    "CORSRules": [
        {
            "AllowedHeaders": ["*"],
            "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
            "AllowedOrigins": ["http://localhost:3000", "http://localhost:5173", "http://localhost:13000", "*"],
            "ExposeHeaders": ["ETag", "x-amz-meta-custom-header"],
            "MaxAgeSeconds": 3000
        }
    ]
}'
echo "Configured CORS for S3 bucket"

# Create SQS queues
awslocal sqs create-queue --queue-name document-registered
awslocal sqs create-queue --queue-name document-registered-dlq
echo "Created SQS queues: document-registered, document-registered-dlq"

# Configure DLQ for document-registered queue
awslocal sqs set-queue-attributes \
    --queue-url http://localhost:4566/000000000000/document-registered \
    --attributes '{
        "RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:document-registered-dlq\",\"maxReceiveCount\":3}"
    }'
echo "Configured DLQ for document-registered queue"

echo "LocalStack initialization complete!"
