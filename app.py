import base64
import binascii
import json
import os
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from functools import wraps
from pathlib import Path
from typing import Any

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
import requests
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from authlib.integrations.flask_client import OAuth
except ModuleNotFoundError:
    OAuth = None

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ModuleNotFoundError:
    boto3 = None
    BotoCoreError = ClientError = Exception

from fire_client import get_api_url, send_image_bytes


def load_dotenv_file(dotenv_path: str = ".env") -> None:
    """Load simple KEY=VALUE pairs from a local .env file if present."""
    env_file = Path(dotenv_path)
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key or key in os.environ:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        os.environ[key] = value


load_dotenv_file()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me-in-production")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "").lower() == "true"
app.config["GOOGLE_CLIENT_ID"] = os.getenv("GOOGLE_CLIENT_ID", "")
app.config["GOOGLE_CLIENT_SECRET"] = os.getenv("GOOGLE_CLIENT_SECRET", "")
app.config["AWS_REGION"] = os.getenv("AWS_REGION", "ap-south-1")
app.config["DYNAMODB_USERS_TABLE"] = os.getenv("DYNAMODB_USERS_TABLE", "")
app.config["SNS_TOPIC_ARN"] = os.getenv("SNS_TOPIC_ARN", "")
app.config["SNS_ENABLED"] = bool(app.config["SNS_TOPIC_ARN"])
app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", "587"))
app.config["MAIL_USE_TLS"] = os.getenv("MAIL_USE_TLS", "true").lower() in {"true", "1", "yes"}
app.config["MAIL_USE_SSL"] = os.getenv("MAIL_USE_SSL", "false").lower() in {"true", "1", "yes"}
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME", "")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD", "")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_DEFAULT_SENDER", app.config["MAIL_USERNAME"])
app.config["MAIL_RECIPIENTS"] = [email.strip() for email in os.getenv("MAIL_RECIPIENTS", "").split(",") if email.strip()]

oauth = OAuth(app) if OAuth is not None else None
google_oauth_enabled = bool(
    OAuth is not None and app.config["GOOGLE_CLIENT_ID"] and app.config["GOOGLE_CLIENT_SECRET"]
)
if google_oauth_enabled:
    oauth.register(
        name="google",
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_id=app.config["GOOGLE_CLIENT_ID"],
        client_secret=app.config["GOOGLE_CLIENT_SECRET"],
        client_kwargs={"scope": "openid email profile"},
    )


POSITIVE_FIRE_PHRASES = (
    "fire detected",
    "smoke detected",
    "flame detected",
    "wildfire detected",
    "fire alert",
    "smoke alert",
    "active fire",
)

POSITIVE_FIRE_LABELS = {"fire", "smoke", "flame", "wildfire"}

NEGATIVE_FIRE_PHRASES = (
    "no fire",
    "fire not detected",
    "no smoke",
    "smoke not detected",
    "normal",
    "safe",
    "clear",
    "none",
    "false alarm",
    "fire alarm cleared",
    "resolved",
    "ended",
)

FIRE_KEYS = {"fire", "fire_detected", "has_fire", "smoke", "smoke_detected", "flame_detected"}
TEXT_RESULT_KEYS = {"message", "result", "status", "description"}
LABEL_RESULT_KEYS = {"label", "prediction", "class", "classification", "category"}

def subscribe_user_email_to_sns(email: str) -> bool:
    """Subscribe user email to SNS topic if not already subscribed."""
    if not email or not app.config["SNS_TOPIC_ARN"] or boto3 is None:
        return False

    try:
        sns_client = boto3.client(
            "sns",
            region_name=app.config["AWS_REGION"],
        )
        response = sns_client.subscribe(
            TopicArn=app.config["SNS_TOPIC_ARN"],
            Protocol="email",
            Endpoint=email,
        )
        subscription_arn = response.get("SubscriptionArn")
        print(f"[SNS] User {email} subscribed to SNS topic. Subscription ARN: {subscription_arn}", flush=True)
        if subscription_arn == "PendingConfirmation":
            print(f"[SNS] Confirmation email sent to {email}. User must confirm subscription.", flush=True)
        return True
    except (BotoCoreError, ClientError) as e:
        error_str = str(e)
        if "InvalidParameterException" in error_str and "already" in error_str:
            print(f"[SNS] {email} already subscribed to topic", flush=True)
            return True
        print(f"[SNS] Subscription failed for {email}: {e}", flush=True)
        return False


def send_fire_notification_sns(detection_details: dict[str, Any], is_acknowledgement: bool = False) -> bool:
    """Send notification via AWS SNS to current user's email."""
    if not app.config["SNS_TOPIC_ARN"]:
        print("[SNS] SNS_TOPIC_ARN not configured in environment", flush=True)
        return False

    if boto3 is None:
        print("[SNS] boto3 not available", flush=True)
        return False

    user = current_user()
    if not user:
        print("[SNS] No current user", flush=True)
        return False

    user_email = user.get("email", "").strip().lower()
    if not user_email:
        print(f"[SNS] User '{user['username']}' has no email address in account", flush=True)
        return False

    if is_acknowledgement:
        subject = "Fire Alert Acknowledged - Inferno Vision"
        action = "acknowledged"
    else:
        subject = "Fire Detected - Inferno Vision"
        action = "detected"

    message = f"""Fire alert has been {action}.

Detection Details:
{json.dumps(detection_details, indent=2)}

Timestamp: {datetime.now(timezone.utc).isoformat()}
User: {user['username']}
"""

    try:
        # print(f"[SNS] Subscribing {user_email} to topic...", flush=True)
        # # Subscribe user email first
        # subscribe_result = subscribe_user_email_to_sns(user_email)
        # if not subscribe_result:
        #     print(f"[SNS] Failed to subscribe {user_email}", flush=True)
        #     # Continue anyway - may already be subscribed

        # print(f"[SNS] Publishing notification to {user_email}...", flush=True)
        # Publish to SNS topic
        sns_client = boto3.client(
            "sns",
            region_name=app.config["AWS_REGION"],
        )
        response = sns_client.publish(
            TopicArn=app.config["SNS_TOPIC_ARN"],
            Subject=subject,
            Message=message,
        )
        message_id = response.get("MessageId")
        print(f"[SNS] Notification published successfully. MessageId: {message_id}", flush=True)
        return True
    except (BotoCoreError, ClientError) as e:
        print(f"[SNS] AWS error: {type(e).__name__}: {e}", flush=True)
        return False
    except Exception as e:
        print(f"[SNS] Unexpected error: {type(e).__name__}: {e}", flush=True)
        return False
class UserStoreError(RuntimeError):
    pass


def auth_storage_ready() -> bool:
    return bool(boto3 is not None and app.config["DYNAMODB_USERS_TABLE"])


def auth_storage_message() -> str:
    if boto3 is None:
        return "Authentication storage is unavailable because boto3 is not installed."
    if not app.config["DYNAMODB_USERS_TABLE"]:
        return "Authentication storage is not configured. Set DYNAMODB_USERS_TABLE."
    return "Authentication storage is unavailable."


def get_users_table():
    if not auth_storage_ready():
        raise UserStoreError(auth_storage_message())

    resource = boto3.resource("dynamodb", region_name=app.config["AWS_REGION"])
    return resource.Table(app.config["DYNAMODB_USERS_TABLE"])


def mail_configured() -> bool:
    return bool(app.config["MAIL_SERVER"] and app.config["MAIL_RECIPIENTS"])


def send_notification_email(subject: str, body: str) -> None:
    if not mail_configured():
        raise RuntimeError("Mail is not configured. Set MAIL_SERVER, MAIL_RECIPIENTS, and related environment variables.")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = app.config["MAIL_DEFAULT_SENDER"] or app.config["MAIL_USERNAME"]
    message["To"] = ", ".join(app.config["MAIL_RECIPIENTS"])
    message.set_content(body)

    if app.config["MAIL_USE_SSL"]:
        smtp_class = smtplib.SMTP_SSL
    else:
        smtp_class = smtplib.SMTP

    with smtp_class(app.config["MAIL_SERVER"], app.config["MAIL_PORT"]) as smtp:
        smtp.ehlo()
        if app.config["MAIL_USE_TLS"] and not app.config["MAIL_USE_SSL"]:
            smtp.starttls()
            smtp.ehlo()
        if app.config["MAIL_USERNAME"] and app.config["MAIL_PASSWORD"]:
            smtp.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
        smtp.send_message(message)


def normalize_user(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None

    return {
        "id": str(item.get("id", "")),
        "username": str(item.get("username", "")).strip().lower(),
        "email": str(item.get("email", "")).strip().lower(),
        "password_hash": str(item.get("password_hash", "")),
        "auth_provider": str(item.get("auth_provider", "local")),
        "google_sub": str(item.get("google_sub", "")),
        "email_verified": bool(item.get("email_verified", False)),
        "created_at": str(item.get("created_at", "")),
    }


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    try:
        response = get_users_table().get_item(Key={"id": str(user_id)})
    except (BotoCoreError, ClientError) as exc:
        raise UserStoreError(f"DynamoDB get by id failed: {exc}") from exc
    return normalize_user(response.get("Item"))


def list_all_users() -> list[dict[str, Any]]:
    try:
        table = get_users_table()
        response = table.scan()
        items = response.get("Items", [])
        while "LastEvaluatedKey" in response:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))
    except (BotoCoreError, ClientError) as exc:
        raise UserStoreError(f"DynamoDB scan failed: {exc}") from exc

    users = [normalize_user(item) for item in items]
    return [user for user in users if user is not None]


def find_user_by_username(username: str) -> dict[str, Any] | None:
    normalized = username.strip().lower()
    for user in list_all_users():
        if user["username"] == normalized:
            return user
    return None


def find_user_by_google_identity(google_sub: str, email: str) -> dict[str, Any] | None:
    for user in list_all_users():
        if user["google_sub"] == google_sub:
            return user
        if email and user["email"] == email:
            return user
    return None


def username_exists(username: str, exclude_user_id: str | None = None) -> bool:
    normalized = username.strip().lower()
    for user in list_all_users():
        if user["username"] == normalized and user["id"] != exclude_user_id:
            return True
    return False


def next_user_id() -> str:
    highest = 0
    for user in list_all_users():
        try:
            highest = max(highest, int(user["id"]))
        except (TypeError, ValueError):
            continue
    return str(highest + 1)


def save_user(user: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_user(user)
    if normalized is None:
        raise UserStoreError("Cannot save an empty user record.")

    try:
        get_users_table().put_item(Item=normalized)
    except (BotoCoreError, ClientError) as exc:
        raise UserStoreError(f"DynamoDB put failed: {exc}") from exc

    return normalized


def create_default_user() -> None:
    default_username = os.getenv("ADMIN_USERNAME")
    default_password = os.getenv("ADMIN_PASSWORD")
    if not default_username or not default_password or not auth_storage_ready():
        return

    normalized_username = default_username.strip().lower()
    if find_user_by_username(normalized_username):
        return

    save_user(
        {
            "id": next_user_id(),
            "username": normalized_username,
            "email": "",
            "password_hash": generate_password_hash(default_password),
            "auth_provider": "local",
            "google_sub": "",
            "email_verified": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.before_request
def prepare_app() -> None:
    if auth_storage_ready():
        try:
            create_default_user()
        except UserStoreError:
            pass


def current_user() -> dict[str, Any] | None:
    user_id = session.get("user_id")
    if not user_id:
        return None

    try:
        return get_user_by_id(str(user_id))
    except UserStoreError:
        return None


@app.context_processor
def inject_auth_state() -> dict[str, Any]:
    user = current_user()
    return {
        "current_user": user,
        "google_oauth_enabled": google_oauth_enabled,
        "auth_storage_ready": auth_storage_ready(),
    }


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if current_user() is None:
            if request.path.startswith("/analyze-frame"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped_view


def safe_redirect_target(target: str | None) -> str:
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("index")


def login_user(user: dict[str, Any]) -> None:
    session.clear()
    session["user_id"] = user["id"]
    session["username"] = user["username"]


def upsert_google_user(userinfo: dict[str, Any]) -> dict[str, Any]:
    google_sub = str(userinfo.get("sub", "")).strip()
    email = str(userinfo.get("email", "")).strip().lower()
    email_verified = bool(userinfo.get("email_verified"))
    display_name = str(userinfo.get("name", "")).strip()
    preferred_username = email or display_name.lower().replace(" ", "-") or f"google-{google_sub}"
    user = find_user_by_google_identity(google_sub, email)

    if user is not None:
        user["username"] = preferred_username
        user["email"] = email
        user["auth_provider"] = "google"
        user["google_sub"] = google_sub
        user["email_verified"] = email_verified
        return save_user(user)

    candidate_username = preferred_username
    suffix = 1
    while username_exists(candidate_username):
        suffix += 1
        candidate_username = f"{preferred_username}-{suffix}"

    return save_user(
        {
            "id": next_user_id(),
            "username": candidate_username,
            "email": email,
            "password_hash": "",
            "auth_provider": "google",
            "google_sub": google_sub,
            "email_verified": email_verified,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def is_truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value > 0

    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"true", "1", "yes", "positive"}

    return False


def detect_fire_signal(value: Any) -> bool:
    if isinstance(value, str):
        normalized = value.strip().lower()

        if any(phrase in normalized for phrase in NEGATIVE_FIRE_PHRASES):
            return False

        if any(phrase in normalized for phrase in POSITIVE_FIRE_PHRASES):
            return True

        normalized_words = set(re.findall(r"[a-z]+", normalized))
        if normalized in POSITIVE_FIRE_LABELS:
            return True

        # Only treat a generic string as fire if a fire/smoke/flame label appears.
        return bool(POSITIVE_FIRE_LABELS & normalized_words)

    if isinstance(value, dict):
        for key, nested in value.items():
            normalized_key = str(key).strip().lower()

            if normalized_key in FIRE_KEYS:
                if is_truthy_flag(nested) or detect_fire_signal(nested):
                    return True

            if normalized_key in TEXT_RESULT_KEYS | LABEL_RESULT_KEYS:
                if detect_fire_signal(nested):
                    return True

        return False

    if isinstance(value, list):
        return any(detect_fire_signal(item) for item in value)

    return False


@app.get("/")
@login_required
def index():
    return render_template("index.html", api_url=get_api_url())


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user() is not None:
        return redirect(url_for("index"))

    next_url = safe_redirect_target(request.values.get("next"))
    if not auth_storage_ready():
        flash(auth_storage_message(), "error")
        return render_template("login.html", next_url=next_url), 503

    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        try:
            user = find_user_by_username(username)
        except UserStoreError as exc:
            flash(str(exc), "error")
            return render_template("login.html", next_url=next_url), 503

        if user is not None and user["auth_provider"] == "google":
            flash("This account uses Google Sign-In. Continue with Google instead.", "error")
            return render_template("login.html", next_url=next_url), 400

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid username or password.", "error")
            return render_template("login.html", next_url=next_url), 401

        login_user(user)
        return redirect(next_url)

    return render_template("login.html", next_url=next_url)


@app.get("/login/google")
def login_google():
    if current_user() is not None:
        return redirect(url_for("index"))

    if not google_oauth_enabled:
        message = "Google Sign-In is not configured yet."
        if OAuth is None:
            message = "Google Sign-In is unavailable because Authlib is not installed in this environment."
        flash(message, "error")
        return redirect(url_for("login"))

    if not auth_storage_ready():
        flash(auth_storage_message(), "error")
        return redirect(url_for("login"))

    redirect_uri = url_for("authorize_google", _external=True, _scheme="https")
    next_url = safe_redirect_target(request.args.get("next"))
    session["post_login_redirect"] = next_url
    return oauth.google.authorize_redirect(redirect_uri, prompt="select_account")


@app.get("/auth/google")
def authorize_google():
    if not google_oauth_enabled:
        message = "Google Sign-In is not configured yet."
        if OAuth is None:
            message = "Google Sign-In is unavailable because Authlib is not installed in this environment."
        flash(message, "error")
        return redirect(url_for("login"))

    try:
        token = oauth.google.authorize_access_token()
    except Exception:
        flash("Google Sign-In could not be completed. Please try again.", "error")
        return redirect(url_for("login"))

    userinfo = token.get("userinfo") or {}
    if not userinfo:
        flash("Google did not return profile information.", "error")
        return redirect(url_for("login"))

    if not userinfo.get("email_verified"):
        flash("Only Google accounts with a verified email address can sign in.", "error")
        return redirect(url_for("login"))

    if not userinfo.get("email") or not userinfo.get("sub"):
        flash("Google account details were incomplete. Please try again.", "error")
        return redirect(url_for("login"))

    try:
        user = upsert_google_user(userinfo)
    except UserStoreError as exc:
        flash(str(exc), "error")
        return redirect(url_for("login"))

    login_user(user)
    next_url = safe_redirect_target(session.pop("post_login_redirect", None))
    return redirect(next_url)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user() is not None:
        return redirect(url_for("index"))

    if not auth_storage_ready():
        flash(auth_storage_message(), "error")
        return render_template("register.html"), 503

    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(username) < 3:
            flash("Username must be at least 3 characters.", "error")
            return render_template("register.html"), 400

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("register.html"), 400

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html"), 400

        try:
            if username_exists(username):
                flash("That username is already taken.", "error")
                return render_template("register.html"), 409

            save_user(
                {
                    "id": next_user_id(),
                    "username": username,
                    "email": "",
                    "password_hash": generate_password_hash(password),
                    "auth_provider": "local",
                    "google_sub": "",
                    "email_verified": False,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except UserStoreError as exc:
            flash(str(exc), "error")
            return render_template("register.html"), 503

        flash("Account created. You can sign in now.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/upload")
@login_required
def upload_page():
    return render_template("upload.html")


@app.post("/acknowledge-fire")
@login_required
def acknowledge_fire():
    """Acknowledge fire alert and send SNS notification."""
    payload = request.get_json(silent=True) or {}
    detection_details = payload.get("detection", {})

    notification_sent = send_fire_notification_sns(detection_details, is_acknowledgement=True)

    return jsonify({
        "ok": True,
        "notification_sent": notification_sent,
        "message": "Fire alert acknowledged" + (" and SNS notification sent" if notification_sent else ""),
    })


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "fire-detection-ui",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.get("/diagnostics")
@login_required
def diagnostics():
    """Diagnostic endpoint to check notification configuration."""
    user = current_user()
    
    # Check SNS topic subscriptions
    subscriptions = []
    try:
        if app.config["SNS_TOPIC_ARN"] and boto3 is not None:
            sns_client = boto3.client(
                "sns",
                region_name=app.config["AWS_REGION"],
            )
            response = sns_client.list_subscriptions_by_topic(
                TopicArn=app.config["SNS_TOPIC_ARN"]
            )
            subscriptions = [
                {
                    "endpoint": sub.get("Endpoint"),
                    "protocol": sub.get("Protocol"),
                    "status": sub.get("SubscriptionArn"),
                }
                for sub in response.get("Subscriptions", [])
            ]
    except Exception as e:
        subscriptions = [{"error": str(e)}]
    
    return jsonify(
        {
            "current_user": {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "has_email": bool(user.get("email", "").strip()),
                "email_verified": user.get("email_verified", False),
                "auth_provider": user.get("auth_provider", "unknown"),
            },
            "sns_configuration": {
                "topic_arn": app.config["SNS_TOPIC_ARN"] or "NOT SET",
                "enabled": bool(app.config["SNS_TOPIC_ARN"]),
                "aws_region": app.config["AWS_REGION"],
                "boto3_available": boto3 is not None,
            },
            "sns_subscriptions": subscriptions,
            "dynamodb_configuration": {
                "enabled": auth_storage_ready(),
                "table_name": app.config["DYNAMODB_USERS_TABLE"],
            },
            "troubleshooting": {
                "email_not_set": not user.get("email", "").strip(),
                "sns_not_configured": not app.config["SNS_TOPIC_ARN"],
                "boto3_missing": boto3 is None,
                "pending_confirmation": any(
                    sub.get("status") == "PendingConfirmation"
                    for sub in subscriptions
                    if isinstance(sub, dict) and "status" in sub
                ),
            },
        }
    )


@app.post("/analyze-frame")
@login_required
def analyze_frame():
    image_bytes = None

    try:
        uploaded = request.files.get("frame")
        if uploaded:
            image_bytes = uploaded.read()
        else:
            payload = request.get_json(silent=True) or {}
            frame_data = payload.get("image")
            if frame_data and "," in frame_data:
                _, encoded = frame_data.split(",", 1)
                image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return jsonify({"error": "Invalid frame payload"}), 400

    if not image_bytes:
        return jsonify({"error": "No frame provided"}), 400

    try:
        detection = send_image_bytes(image_bytes)
        fire_detected = detect_fire_signal(detection)
        
        # Send SNS notification on first fire detection
        if fire_detected and not session.get("fire_notification_sent"):
            send_fire_notification_sns(detection, is_acknowledgement=False)
            session["fire_notification_sent"] = True
        elif not fire_detected and session.get("fire_notification_sent"):
            session.pop("fire_notification_sent", None)
        
        # Add helper message if using fallback detection
        message = ""
        if detection.get("fallback_method"):
            message = "⚠️  Using local detection (AWS API unavailable)"
        elif detection.get("method") == "local_hsv_detection":
            message = "ℹ️  Using local color-based detection"
        
        response_data = {
            "ok": True,
            "detection": detection,
            "fire_detected": fire_detected,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        
        if message:
            response_data["message"] = message
            
        return jsonify(response_data)
    except Exception as exc:
        # Even if there's an error, try fallback as last resort
        try:
            detection = send_image_bytes(image_bytes, use_fallback=True)
            fire_detected = detect_fire_signal(detection)
            return jsonify(
                {
                    "ok": True,
                    "detection": detection,
                    "fire_detected": fire_detected,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "message": "⚠️  Using fallback detection method",
                }
            )
        except Exception as fallback_exc:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "Detection service unavailable",
                        "details": str(exc),
                    }
                ),
                502,
            )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )
