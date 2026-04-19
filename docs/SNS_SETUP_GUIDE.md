# SNS Notification Setup Guide

Fire detection notifications require AWS SNS (Simple Notification Service) to be configured. Follow these steps:

## 1. Check Current Configuration

Open your browser and go to:
```
http://localhost:5000/diagnostics
```

This will show you:
- Current user email
- SNS configuration status
- DynamoDB status
- Required fixes

## 2. Prerequisites

- AWS Account with SNS access
- User account must have an email address
- AWS credentials must be configured

## 3. Create SNS Topic

### Via AWS Console:
1. Go to https://console.aws.amazon.com/sns/
2. Click "Topics" in left menu
3. Click "Create topic"
4. Name: `fire-detection-alerts`
5. Type: Standard
6. Click "Create topic"
7. Copy the **Topic ARN** (format: `arn:aws:sns:region:account-id:topic-name`)

### Via AWS CLI:
```bash
aws sns create-topic --name fire-detection-alerts --region ap-south-1
```

## 4. Set SNS_TOPIC_ARN in .env

Edit `.env` and add:
```env
SNS_TOPIC_ARN=arn:aws:sns:ap-south-1:123456789012:fire-detection-alerts
```

Replace with your actual topic ARN from step 3.

## 5. Verify User Email

Your login account must have an email:

### For Admin User:
- Update the admin account email in DynamoDB table `fire-detection-users`
- Set the `email` field to your email address

### For Google Sign-In Users:
- Email is automatically added from Google account

### Update Email via AWS Console:
1. Go to DynamoDB → Tables → fire-detection-users
2. Find your user item
3. Edit the `email` attribute
4. Add your email address (e.g., `user@example.com`)

## 6. Configure AWS Credentials

Ensure your AWS credentials are set up. Check one of these:

### Option A: Environment Variables
```powershell
$env:AWS_ACCESS_KEY_ID="your-access-key"
$env:AWS_SECRET_ACCESS_KEY="your-secret-key"
```

### Option B: AWS CLI Profile
```powershell
aws configure
```

### Option C: Check Current Setup
```powershell
aws sts get-caller-identity
```

Should return your AWS account info.

## 7. Check IAM Permissions

Your AWS user/role needs these permissions:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sns:Subscribe",
        "sns:Publish"
      ],
      "Resource": "arn:aws:sns:*:*:*"
    }
  ]
}
```

## 8. Test Configuration

1. Restart Flask: `python app.py`
2. Go to `/diagnostics` again
3. Should show:
   - `sns_configured.enabled: true`
   - `sns_configured.topic_arn: ***` (not blank)
   - Your email address

## 9. Trigger Fire Detection

1. Click "Start Live Scan"
2. Trigger fire detection (or wait for real fire)
3. Check Flask console output for `[SNS]` messages
4. Check your email for "Fire Detected" notification

## 10. Troubleshooting

### Email not received?
- Check spam/junk folder
- Look at Flask console for `[SNS]` error messages
- Run `/diagnostics` endpoint

### SNS_TOPIC_ARN shows "NOT SET"?
- Add `SNS_TOPIC_ARN=arn:aws:sns:...` to `.env`
- Restart the app

### User has no email?
- Update email in DynamoDB
- Or log in with Google (auto-adds email)

### AWS credential error?
- Run `aws sts get-caller-identity`
- Configure credentials if not found
- Check IAM permissions

## 11. Monitor Notifications

### View SNS Metrics:
```bash
aws sns list-topics --region ap-south-1
aws sns list-subscriptions-by-topic --topic-arn "YOUR-TOPIC-ARN" --region ap-south-1
```

### View Flask Logs:
Look for lines starting with `[SNS]` in Flask console output

## Need Help?

1. Check `/diagnostics` endpoint
2. Review Flask console output for error messages
3. Verify all 6 items in section 10 are correct
