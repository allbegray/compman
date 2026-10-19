#!/bin/bash
set -e

ENDPOINT=http://localhost:4566
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=ap-northeast-2
BUCKET=deploy-test

aws s3 mb "s3://$BUCKET" --region "$AWS_DEFAULT_REGION" --endpoint-url "$ENDPOINT" >/dev/null 2>&1 || true
aws s3 sync /init-data/app "s3://$BUCKET" --delete --endpoint-url "$ENDPOINT"
aws s3 cp /init-data/seed.tar.gz "s3://$BUCKET/archives/seed.tar.gz" --endpoint-url "$ENDPOINT"
echo "Seeded $BUCKET (dir + archive)"
