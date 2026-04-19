# Fire Detection Using AWS

This project is a Flask web app that captures webcam frames in the browser, relays them to an AWS-backed detection API, and shows the latest fire-detection result in a live dashboard.

## Local Run

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set environment variables if needed:

```bash
set FIRE_API_URL=https://uy3abarouf.execute-api.ap-south-1.amazonaws.com/upload
set FLASK_DEBUG=true
set SECRET_KEY=replace-this-with-a-long-random-secret
set ADMIN_USERNAME=admin
set ADMIN_PASSWORD=change-this-password
set GOOGLE_CLIENT_ID=your-google-client-id
set GOOGLE_CLIENT_SECRET=your-google-client-secret
set AWS_REGION=ap-south-1
set DYNAMODB_USERS_TABLE=fire-detection-users
```

4. Start the app:

```bash
python app.py
```

The app will be available at `http://localhost:5000`.

## Production Run

Use Gunicorn with the WSGI entry point:

```bash
gunicorn --bind 0.0.0.0:$PORT wsgi:app
```

## Environment Variables

- `PORT`: Port exposed by the host platform.
- `FLASK_DEBUG`: Set to `true` only for local debugging.
- `SECRET_KEY`: Required for secure Flask sessions.
- `SESSION_COOKIE_SECURE`: Set to `true` in HTTPS deployments.
- `ADMIN_USERNAME`: Optional bootstrap admin username created automatically on first request.
- `ADMIN_PASSWORD`: Optional bootstrap admin password paired with `ADMIN_USERNAME`.
- `FIRE_API_URL`: AWS detection API endpoint.
- `GOOGLE_CLIENT_ID`: Google OAuth client ID for Sign-In.
- `GOOGLE_CLIENT_SECRET`: Google OAuth client secret for Sign-In.
- `AWS_REGION`: AWS region for DynamoDB.
- `DYNAMODB_USERS_TABLE`: DynamoDB table used by the login system.
- `SNS_TOPIC_ARN`: AWS SNS topic ARN for fire notifications (format: `arn:aws:sns:region:account-id:topic-name`).

## DynamoDB Login Storage

The login system now stores users in AWS DynamoDB instead of a local file or local database.

Suggested table design:

- Table name: `fire-detection-users`
- Partition key: `id` (String)

Each user item stores:

- `id`
- `username`
- `email`
- `password_hash`
- `auth_provider`
- `google_sub`
- `email_verified`
- `created_at`

The app currently looks users up by scanning the table and filtering in code, so this works best for small auth datasets. If you expect many users, the next improvement would be adding a GSI on `username` and optionally on `email`.

## Google Sign-In Setup

This app supports Google Sign-In through OpenID Connect. It only accepts Google accounts when Google reports `email_verified=true`.

Configure these in Google Cloud:

- Application type: Web application
- Authorized redirect URI: `https://your-domain.com/auth/google`
- Local redirect URI for development: `http://127.0.0.1:5000/auth/google`

Then set:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `SECRET_KEY`

Important:

- Google Sign-In will stay disabled until both Google environment variables are present.
- In production, use HTTPS and keep `SESSION_COOKIE_SECURE=true`.

## SNS Notifications

Push notifications are sent via AWS SNS to the email address associated with the logged-in user account. Notifications are triggered in two scenarios:
1. **Fire Detection**: When fire is first detected in a live scan
2. **Acknowledgement**: When a user acknowledges the fire alert

### SNS Topic Setup

1. Create an SNS topic in AWS Console:
   - Go to SNS → Topics → Create topic
   - Name: e.g., `fire-detection-alerts`
   - Choose Standard topic type
   - Copy the Topic ARN

2. Set environment variable:
   ```env
   SNS_TOPIC_ARN=arn:aws:sns:ap-south-1:123456789:fire-detection-alerts
   ```

3. Ensure IAM user/role has SNS permissions:
   ```json
   {
     "Effect": "Allow",
     "Action": [
       "sns:Subscribe",
       "sns:Publish"
     ],
     "Resource": "arn:aws:sns:*:*:*"
   }
   ```

### User Email Requirements
- Users must have an email address in their account for notifications to work
- First time fire is detected, user's email is automatically subscribed to the SNS topic
- They will receive a confirmation email from AWS SNS (must confirm subscription)
- After confirmation, they will receive fire detection and acknowledgement notifications

## Deploying Live

The project is now structured for common Python hosts such as Render, Railway, or similar services that can:

- install dependencies from `requirements.txt`
- start the app with `gunicorn --bind 0.0.0.0:$PORT wsgi:app`
- provide the `FIRE_API_URL` environment variable

Recommended deployment settings:

- Runtime: Python 3.11 or newer
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn --bind 0.0.0.0:$PORT wsgi:app`

## Notes

- `webcam_python_code.py` is a standalone desktop script and is not required for web deployment.
- Browsers will still ask the end user for camera permission when using the live scanner.
