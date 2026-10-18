import json
import os
import re
import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal
import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)
ddb = boto3.resource("dynamodb")
s3 = boto3.client("s3")
sns = boto3.client("sns")

INCIDENTS = os.environ.get("INCIDENTS_TABLE", "")
NOTIFICATIONS = os.environ.get("NOTIFICATIONS_TABLE", "")
HEARTBEATS = os.environ.get("HEARTBEATS_TABLE", "")
DEDUP = os.environ.get("DEDUP_TABLE", "")
BUCKET = os.environ.get("ARCHIVE_BUCKET", "")
TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def log_event(level, event, **fields):
    payload = {"timestamp": utc_now(), "level": level, "event": event, **fields}
    getattr(logger, level.lower(), logger.info)(json.dumps(payload, default=str))

def json_response(status, body):
    return {"statusCode": status, "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"}, "body": json.dumps(body, default=decimal_default)}

def decimal_default(value):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    raise TypeError(f"Unsupported type: {type(value).__name__}")

def parse_body(event):
    raw = event.get("body")
    if raw is None:
        return {}
    if len(raw) > 16384:
        raise ValueError("Request body exceeds 16 KB.")
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        raise ValueError("Request body must be valid JSON.")

def claims(event):
    return ((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt", {}).get("claims", {}) or {}

def groups(event):
    raw = claims(event).get("cognito:groups", [])
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        return [part.strip().strip('"[]') for part in raw.split(",") if part.strip()]
    return []

def require_user(event):
    if not claims(event).get("sub"):
        raise PermissionError("A valid Cognito JWT is required.")
    if not any(role in groups(event) for role in ("LabAssistant", "ITAdministrator")):
        raise PermissionError("User must belong to the LabAssistant or ITAdministrator Cognito group.")

def require_admin(event):
    require_user(event)
    if "ITAdministrator" not in groups(event):
        raise PermissionError("Only ITAdministrator can change incident status.")

def clean_text(value, name, maximum, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{name} is required.")
    if len(value) > maximum:
        raise ValueError(f"{name} must be at most {maximum} characters.")
    return value

def normalize_severity(value):
    mapping = {"low": "Low", "medium": "Medium", "high": "High", "critical": "Critical"}
    if not isinstance(value, str) or value.lower() not in mapping:
        raise ValueError("severity must be Low, Medium, High, or Critical.")
    return mapping[value.lower()]

def normalize_status(value):
    mapping = {"open": "Open", "in progress": "In Progress", "resolved": "Resolved", "acknowledged": "Acknowledged"}
    if not isinstance(value, str) or value.lower() not in mapping:
        raise ValueError("status must be Open, Acknowledged, In Progress, or Resolved.")
    return mapping[value.lower()]

def dashboard_incident(item):
    # Keep legacy dashboard field names while retaining canonical incidentId.
    result = dict(item)
    result["id"] = result.get("incidentId")
    result["type"] = result.get("type", "Emergency")
    result["reporter"] = result.get("reporter", "Unknown")
    result["asset"] = result.get("asset", result.get("deviceId", ""))
    result["action"] = result.get("action", result.get("resolutionNotes", ""))
    return result

def create_incident(body, reporter_claim, source="dashboard", device_id=None):
    incident_type = clean_text(body.get("type", body.get("incidentType")), "type", 100, True)
    room = clean_text(body.get("room", body.get("labId")), "room", 100, True)
    reporter = clean_text(body.get("reporter", reporter_claim), "reporter", 80, True)
    description = clean_text(body.get("description"), "description", 1000, True)
    asset = clean_text(body.get("asset", body.get("assetId", device_id or "")), "asset", 80)
    action = clean_text(body.get("action", ""), "action", 1000)
    severity = normalize_severity(body.get("severity", "Medium"))
    now = utc_now()
    incident_id = f"INC-{datetime.now(timezone.utc).year}-{uuid.uuid4().hex[:8].upper()}"
    return {
        "incidentId": incident_id, "entityType": "INCIDENT", "id": incident_id,
        "type": incident_type, "room": room, "reporter": reporter,
        "severity": severity, "description": description, "status": "Open",
        "createdAt": now, "updatedAt": now, "acknowledgedBy": "",
        "acknowledgedAt": None, "resolutionNotes": "", "resolvedAt": None,
        "asset": asset, "action": action, "source": source, "deviceId": device_id or "",
        "notificationStatus": "PENDING", "timeline": [{"at": now, "event": "CREATED", "by": reporter, "source": source}]
    }

def save_snapshot(item, reason):
    if not BUCKET:
        raise RuntimeError("S3 archive bucket is not configured.")
    key = f"incidents/{item['createdAt'][:10]}/{item['incidentId']}/{item['updatedAt'].replace(':','').replace('.','')}-{reason}.json"
    s3.put_object(Bucket=BUCKET, Key=key, Body=json.dumps(item, indent=2, default=decimal_default).encode("utf-8"),
                  ContentType="application/json", ServerSideEncryption="AES256")
    return key

def put_incident(item):
    ddb.Table(INCIDENTS).put_item(Item=item, ConditionExpression="attribute_not_exists(incidentId)")
    # If archival fails, incident remains in DynamoDB; caller records/logs partial workflow.
    try:
        key = save_snapshot(item, "created")
        log_event("INFO", "incident_archived", incidentId=item["incidentId"], s3Key=key)
    except Exception as exc:
        log_event("ERROR", "incident_archive_failed", incidentId=item["incidentId"], error=str(exc))
        item["archiveStatus"] = "FAILED"
    return item

def write_notification(item, status, detail=""):
    record = {
        "notificationId": f"NTF-{uuid.uuid4().hex[:10].upper()}",
        "entityType": "NOTIFICATION", "createdAt": utc_now(),
        "incidentId": item["incidentId"], "title": f"{item['severity']} incident reported",
        "message": f"{item['incidentId']} — {item['type']} in {item['room']}. Severity: {item['severity']}. Description: {item['description'][:400]}",
        "level": "critical" if item["severity"] in ("High", "Critical") else "info",
        "deliveryStatus": status, "detail": detail[:500]
    }
    ddb.Table(NOTIFICATIONS).put_item(Item=record)
    return record

def notify_admin(item):
    # Persist the incident first. SNS failure never deletes/rolls back the incident.
    if not TOPIC_ARN:
        write_notification(item, "NOT_CONFIGURED", "SNS topic ARN missing")
        return "NOT_CONFIGURED"
    message = (
        f"LabGuard incident request\nIncident ID: {item['incidentId']}\n"
        f"Type: {item['type']}\nLaboratory: {item['room']}\nSeverity: {item['severity']}\n"
        f"Timestamp (UTC): {item['createdAt']}\nDescription: {item['description'][:600]}\n"
        "Review the authenticated LabGuard dashboard for further details."
    )
    try:
        result = sns.publish(TopicArn=TOPIC_ARN, Subject=f"LabGuard {item['severity']}: {item['incidentId']}"[:100], Message=message)
        status = "PUBLISH_ACCEPTED" if result.get("MessageId") else "PUBLISH_UNKNOWN"
        write_notification(item, status, "SNS accepted publish request; email delivery is not confirmed.")
        return status
    except Exception as exc:
        log_event("ERROR", "sns_publish_failed", incidentId=item["incidentId"], error=str(exc))
        write_notification(item, "PUBLISH_FAILED", str(exc))
        return "PUBLISH_FAILED"

def get_incident(incident_id):
    result = ddb.Table(INCIDENTS).get_item(Key={"incidentId": incident_id}, ConsistentRead=True)
    return result.get("Item")

def list_entity(table_name, page_size=50, next_token=None):
    limit = max(1, min(100, int(page_size or 50)))
    kwargs = {"IndexName": "ByEntityAndCreatedAt", "KeyConditionExpression": Key("entityType").eq("INCIDENT" if table_name == INCIDENTS else "NOTIFICATION"),
              "ScanIndexForward": False, "Limit": limit}
    if next_token:
        import base64
        try:
            kwargs["ExclusiveStartKey"] = json.loads(base64.urlsafe_b64decode(next_token + "=" * (-len(next_token) % 4)))
        except Exception:
            raise ValueError("nextToken is invalid.")
    result = ddb.Table(table_name).query(**kwargs)
    import base64
    token = base64.urlsafe_b64encode(json.dumps(result["LastEvaluatedKey"]).encode()).decode().rstrip("=") if result.get("LastEvaluatedKey") else None
    return result.get("Items", []), token

def safe_filter_status(status):
    return normalize_status(status) if status else None
