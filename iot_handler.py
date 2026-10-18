import json
import os
import hashlib
from datetime import datetime, timezone
from botocore.exceptions import ClientError
from common import (
    INCIDENTS, HEARTBEATS, DEDUP, ddb, create_incident, put_incident,
    notify_admin, utc_now, log_event
)

def _parse_time(value):
    if not isinstance(value, str):
        raise ValueError("occurredAt must be an ISO-8601 timestamp.")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("occurredAt must include a timezone.")
        return dt.astimezone(timezone.utc)
    except ValueError:
        raise ValueError("occurredAt must be a valid ISO-8601 timestamp with timezone.")

def handler(event, context):
    payload = event or {}
    dedup_created = False
    incident_persisted = False
    dedup_key = None
    try:
        raw_size = len(json.dumps(payload))
        if raw_size > 8192:
            raise ValueError("IoT payload exceeds 8 KB.")
        topic = str(payload.get("mqttTopic", ""))
        device_id = str(payload.get("deviceId", "")).strip()
        lab_id = str(payload.get("labId", "")).strip()
        if not device_id or len(device_id) > 80 or not lab_id or len(lab_id) > 40:
            raise ValueError("deviceId and labId are required.")
        try:
            allow_map = json.loads(os.environ.get("ALLOWED_DEVICE_MAP", "{}"))
        except json.JSONDecodeError:
            allow_map = {}
        # Both payload and topic must agree with the server-side allowlist.
        if allow_map.get(device_id) != lab_id:
            raise PermissionError("Device is not allowlisted for this lab.")
        if topic:
            parts = topic.split("/")
            if len(parts) != 4 or parts[:2] != ["labguard", "labs"] or parts[2] != lab_id:
                raise PermissionError("MQTT topic does not match the allowlisted lab.")
            if parts[3] not in ("events", "heartbeat"):
                raise ValueError("Unsupported MQTT topic.")
        event_type = payload.get("eventType")
        if topic.endswith("/heartbeat") or event_type == "HEARTBEAT":
            observed = _parse_time(payload.get("occurredAt")) if payload.get("occurredAt") else datetime.now(timezone.utc)
            age = abs((datetime.now(timezone.utc) - observed).total_seconds())
            if age > 600:
                raise ValueError("Heartbeat timestamp is outside the 10-minute acceptance window.")
            ddb.Table(HEARTBEATS).put_item(Item={"deviceId": device_id, "labId": lab_id, "observedAt": observed.isoformat().replace("+00:00", "Z"), "receivedAt": utc_now(), "firmwareVersion": str(payload.get("firmwareVersion", ""))[:40]})
            log_event("INFO", "device_heartbeat_received", deviceId=device_id, labId=lab_id)
            return {"ok": True, "kind": "heartbeat"}
        if event_type != "PANIC_BUTTON_PRESSED":
            raise ValueError("eventType must be PANIC_BUTTON_PRESSED or HEARTBEAT.")
        event_id = str(payload.get("eventId", "")).strip()
        if not event_id or len(event_id) > 128:
            raise ValueError("eventId is required and must be at most 128 characters.")
        occurred = _parse_time(payload.get("occurredAt"))
        if abs((datetime.now(timezone.utc) - occurred).total_seconds()) > 600:
            raise ValueError("Event timestamp is outside the 10-minute acceptance window.")
        expiry = int(datetime.now(timezone.utc).timestamp()) + 30 * 24 * 60 * 60
        dedup_key = f"{device_id}#{event_id}"
        ddb.Table(DEDUP).put_item(Item={"eventId": dedup_key, "deviceId": device_id, "receivedAt": utc_now(), "expiresAt": expiry, "state": "PROCESSING"}, ConditionExpression="attribute_not_exists(eventId)")
        dedup_created = True
        body = {
            "type": "ESP32 panic button triggered", "room": lab_id,
            "reporter": device_id, "severity": "Critical",
            "description": "Physical panic button event received from the allowlisted ESP32.",
            "asset": device_id, "action": "", "eventId": event_id
        }
        incident = create_incident(body, device_id, source="iot", device_id=device_id)
        incident["deviceOccurredAt"] = occurred.isoformat().replace("+00:00", "Z")
        incident = put_incident(incident)
        incident_persisted = True
        ddb.Table(DEDUP).update_item(Key={"eventId": dedup_key}, UpdateExpression="SET #state=:state, incidentId=:id", ExpressionAttributeNames={"#state": "state"}, ExpressionAttributeValues={":state": "COMPLETED", ":id": incident["incidentId"]})
        notification_status = notify_admin(incident)
        ddb.Table(INCIDENTS).update_item(Key={"incidentId": incident["incidentId"]}, UpdateExpression="SET notificationStatus=:s", ExpressionAttributeValues={":s": notification_status})
        log_event("INFO", "iot_incident_created", eventId=event_id, incidentId=incident["incidentId"], deviceId=device_id)
        return {"ok": True, "incidentId": incident["incidentId"]}
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            log_event("INFO", "iot_duplicate_event_ignored")
            return {"ok": True, "duplicate": True}
        log_event("ERROR", "iot_ingestion_failed", errorType=type(exc).__name__, error=str(exc))
        raise
    except Exception as exc:
        if dedup_created and not incident_persisted and dedup_key:
            try:
                ddb.Table(DEDUP).delete_item(Key={"eventId": dedup_key})
            except Exception as cleanup_exc:
                log_event("ERROR", "iot_dedup_cleanup_failed", error=str(cleanup_exc))
        log_event("ERROR", "iot_ingestion_failed", errorType=type(exc).__name__, error=str(exc))
        raise
