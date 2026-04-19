# Email Notifications Not Received - Troubleshooting

Follow these steps to diagnose why fire detection emails are not being received.

## Step 1: Check Diagnostics Page

1. Start the Flask app: `python app.py`
2. Open browser: `http://localhost:5000/diagnostics`
3. Review the JSON output carefully

Look for these sections:

### If `email_not_set` is `true`:
```json
"troubleshooting": {
  "email_not_set": true
}
```
**FIX:** Your user account has no email. See "Update User Email" below.

### If `sns_not_configured` is `true`:
```json
"troubleshooting": {
  "sns_not_configured": true
}
```
**FIX:** Add `SNS_TOPIC_ARN` to `.env`. See "Configure SNS" below.

### If `pending_confirmation` is `true`:
```json
"troubleshooting": {
  "pending_confirmation": true
}
```
**FIX:** Check your email inbox for SNS confirmation. You MUST click the confirmation link.

---

## Step 2: Verify SNS Topic ARN

Check your `.env` file:
```env
SNS_TOPIC_ARN=arn:aws:sns:ap-south-1:994077996308:fire-alert-topic
```

Should NOT be empty or `NOT SET`.

### How to get the correct ARN:

**Option A: Via AWS Console**
```
https://console.aws.amazon.com/sns/
→ Topics
→ Select your topic
→ Copy ARN from "Topic details"
```

**Option B: Via AWS CLI**
```bash
aws sns list-topics --region ap-south-1
```

---

## Step 3: Update User Email

Your user account must have an email address.

### For Admin User (local auth):

Edit DynamoDB table:
1. Go to: https://console.aws.amazon.com/dynamodb/
2. Tables → `fire-detection-users`
3. Items tab
4. Find your admin user (username: `admin`)
5. Click on the item
6. Edit attributes
7. Set `email` field to your email (e.g., `user@example.com`)
8. Save

### For Google Sign-In Users:

Email is automatically added from your Google account. Verify it's present:
1. DynamoDB → Tables → `fire-detection-users`
2. Find your user item
3. Check `email` field has a value

---

## Step 4: Check SNS Subscription Status

In the `/diagnostics` output, look at `sns_subscriptions`:

```json
"sns_subscriptions": [
  {
    "endpoint": "user@example.com",
    "protocol": "email",
    "status": "arn:aws:sns:..."
  }
]
```

### If subscription `status` is `PendingConfirmation`:

AWS sent a confirmation email to your address. You MUST:
1. Check your email inbox (and spam folder)
2. Look for "AWS Notification - Subscription Confirmation"
3. Click "Confirm subscription" button in the email

### If status is an ARN (not PendingConfirmation):

Your subscription is confirmed and active.

### If no subscriptions listed:

Subscriptions will be created automatically when fire is first detected.

---

## Step 5: Test SNS Manually

### Via AWS CLI:

```bash
# Publish a test message to the topic
aws sns publish \
  --topic-arn "arn:aws:sns:ap-south-1:994077996308:fire-alert-topic" \
  --subject "Test Fire Alert" \
  --message "This is a test message from CLI" \
  --region ap-south-1
```

Check your email for the message within 1-2 minutes.

### Via AWS Console:

1. Go to SNS dashboard
2. Topics → Select your topic
3. Click "Publish message"
4. Add Subject and Message
5. Click "Publish"
6. Check your email

---

## Step 6: Check Flask Console Logs

When fire is detected, look at the Flask console for `[SNS]` messages:

### Successful message:
```
[SNS] Subscribing user@example.com to topic...
[SNS] User user@example.com subscribed to SNS topic. Subscription ARN: PendingConfirmation
[SNS] Publishing notification to user@example.com...
[SNS] Notification published successfully. MessageId: abc123...
```

### Error: No email
```
[SNS] User 'admin' has no email address in account
```
→ Set email in DynamoDB (Step 3)

### Error: SNS not configured
```
[SNS] SNS_TOPIC_ARN not configured in environment
```
→ Add SNS_TOPIC_ARN to `.env` (Step 2)

### Error: AWS API error
```
[SNS] AWS error: ClientError: Invalid topic ARN format
```
→ Check SNS_TOPIC_ARN is correct (Step 2)

---

## Step 7: Check AWS Credentials

SNS calls need valid AWS credentials. Verify with:

```bash
aws sts get-caller-identity
```

Should return your AWS account info. If not:
- Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables
- Or run `aws configure`

---

## Step 8: Verify IAM Permissions

Your AWS user needs SNS permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sns:Subscribe",
        "sns:Publish",
        "sns:ListSubscriptionsByTopic"
      ],
      "Resource": "arn:aws:sns:*:*:*"
    }
  ]
}
```

Check via AWS IAM console:
1. Users → Your user
2. Permissions tab
3. Verify SNS permissions are present

---

## Quick Checklist

- [ ] SNS_TOPIC_ARN is set in `.env`
- [ ] SNS topic exists in AWS account
- [ ] User email is set in DynamoDB
- [ ] SNS subscription confirmed (check email for confirmation link)
- [ ] AWS credentials configured
- [ ] IAM user has SNS permissions
- [ ] Flask console shows `[SNS]` messages without errors

---

## Common Issues & Fixes

### "Subscription to this topic has failed"
- Check SNS topic ARN format
- Verify topic exists in same AWS region
- Check IAM permissions

### Confirmation email not received
- Check spam/junk folder
- Check that email address in DynamoDB is correct
- Wait 5-10 minutes, AWS can be slow

### Email received but very late
- SNS can take 5-10 minutes to deliver
- Check CloudWatch logs for delays

### Email received but no content
- Check Flask logs for message formatting errors
- Message might exceed size limits (255KB max)

---

## Still Not Working?

1. Check all items in the checklist above
2. Review Flask console for `[SNS]` error messages
3. Run AWS CLI test (Step 5)
4. Check AWS CloudWatch logs for SNS delivery failures
5. Verify email address is not in AWS SNS bounce list

If all else fails, temporarily send logs to a file:
```powershell
python app.py 2>&1 | Tee-Object -FilePath debug.log
```

Then check `debug.log` for detailed error messages.
