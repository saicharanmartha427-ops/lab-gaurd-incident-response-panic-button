import json
import logging
from common import (
    INCIDENTS, NOTIFICATIONS, HEARTBEATS, ddb, json_response, parse_body, claims,
    require_user, require_admin, clean_text, normalize_status, create_incident,
    dashboard_incident, put_incident, notify_admin, get_incident, list_entity,
    save_snapshot, utc_now, log_event, safe_filter_status, groups
)

def _query_params(event):
    return event.get("queryStringParameters") or {}

def handler(event, context):
    request_id = getattr(context, "aws_request_id", "local-test")
    method = ((event.get("requestContext") or {}).get("http") or {}).get("method") or event.get("httpMethod", "GET")
    path = event.get("rawPath") or event.get("path") or "/"
    try:
        if method == "GET" and path == "/health":
            return json_response(200, {"data": {"status": "healthy"}, "source": "aws", "generatedAt": utc_now()})
        require_user(event)
        user_claims = claims(event)
        if method == "GET" and path == "/incidents":
            params = _query_params(event)
            items, token = list_entity(INCIDENTS, params.get("pageSize", 50), params.get("nextToken"))
            status_filter = safe_filter_status(params.get("status"))
            severity_filter = params.get("severity")
            if severity_filter:
                from common import normalize_severity
                severity_filter = normalize_severity(severity_filter)
            items = [x for x in items if (not status_filter or x.get("status") == status_filter) and (not severity_filter or x.get("severity") == severity_filter)]
            return json_response(200, {"data": [dashboard_incident(x) for x in items], "nextToken": token, "source": "aws", "generatedAt": utc_now()})
        if method == "GET" and path.startswith("/incidents/"):
            incident_id = path.rsplit("/", 1)[-1]
            item = get_incident(incident_id)
            if not item:
                return json_response(404, {"error": "Incident not found.", "requestId": request_id})
            return json_response(200, {"data": dashboard_incident(item), "source": "aws", "generatedAt": utc_now()})
        if method == "POST" and path == "/incidents":
            body = parse_body(event)
            reporter = user_claims.get("email") or user_claims.get("cognito:username") or "Authenticated user"
            item = create_incident(body, reporter)
            try:
                item = put_incident(item)
            except Exception as exc:
                if getattr(exc, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                    return json_response(409, {"error": "Incident ID conflict. Retry the request.", "requestId": request_id})
                raise
            notification_status = notify_admin(item)
            item["notificationStatus"] = notification_status
            # Keep current state in DynamoDB even if archive/SNS failed.
            ddb.Table(INCIDENTS).update_item(Key={"incidentId": item["incidentId"]}, UpdateExpression="SET notificationStatus=:s", ExpressionAttributeValues={":s": notification_status})
            log_event("INFO", "incident_created", requestId=request_id, incidentId=item["incidentId"], actor=user_claims.get("sub"))
            return json_response(201, {"data": dashboard_incident(item), "source": "aws", "generatedAt": utc_now()})
        if method == "PATCH" and path.startswith("/incidents/"):
            require_user(event)
            incident_id = path.rsplit("/", 1)[-1]
            body = parse_body(event)
            requested_status = normalize_status(body["status"]) if body.get("status") else None
            # Lab assistants may acknowledge an incident; only IT administrators can perform other updates.
            if not (requested_status == "Acknowledged" and "LabAssistant" in groups(event)):
                require_admin(event)
            item = get_incident(incident_id)
            if not item:
                return json_response(404, {"error": "Incident not found.", "requestId": request_id})
            next_status = requested_status or item["status"]
            notes = clean_text(body.get("resolutionNotes", body.get("responseNote", "")), "resolutionNotes", 1000)
            if next_status == "Resolved" and not notes and not item.get("resolutionNotes"):
                return json_response(400, {"error": "resolutionNotes are required when resolving an incident.", "requestId": request_id})
            old_status = item["status"]
            now = utc_now()
            item["status"] = next_status
            item["updatedAt"] = now
            if next_status == "Acknowledged" and not item.get("acknowledgedAt"):
                item["acknowledgedAt"] = now
                item["acknowledgedBy"] = user_claims.get("email") or user_claims.get("sub", "IT Administrator")
            if notes:
                item["resolutionNotes"] = notes
                item["action"] = notes
            if next_status == "Resolved":
                item["resolvedAt"] = now
            timeline = item.get("timeline", [])
            timeline.append({"at": now, "event": f"STATUS_{next_status.upper().replace(' ', '_')}", "by": user_claims.get("email") or user_claims.get("sub"), "previousStatus": old_status, "notes": notes})
            item["timeline"] = timeline[-100:]
            ddb.Table(INCIDENTS).put_item(Item=item)
            try:
                save_snapshot(item, "updated")
            except Exception as exc:
                log_event("ERROR", "incident_snapshot_failed", incidentId=incident_id, error=str(exc))
            log_event("INFO", "incident_status_updated", requestId=request_id, incidentId=incident_id, oldStatus=old_status, newStatus=next_status, actor=user_claims.get("sub"))
            return json_response(200, {"data": dashboard_incident(item), "source": "aws", "generatedAt": utc_now()})
        if method == "GET" and path == "/notifications":
            params = _query_params(event)
            items, token = list_entity(NOTIFICATIONS, params.get("pageSize", 50), params.get("nextToken"))
            return json_response(200, {"data": items, "nextToken": token, "source": "aws", "generatedAt": utc_now()})
        if method == "GET" and path == "/lab/status":
            import os
            from boto3.dynamodb.conditions import Key
            device_id = (_query_params(event).get("deviceId") or "ESP32-LAB01-001")[:80]
            result = ddb.Table(HEARTBEATS).get_item(Key={"deviceId": device_id}, ConsistentRead=True)
            item = result.get("Item")
            from datetime import datetime, timezone
            age = None
            if item and item.get("observedAt"):
                try:
                    age = max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(item["observedAt"].replace("Z", "+00:00"))).total_seconds()))
                except ValueError:
                    age = None
            stale_after = 180
            status = "UNKNOWN" if not item else ("STALE" if age is None or age > stale_after else "ONLINE")
            return json_response(200, {"data": {"status": status, "deviceId": device_id, "observedAt": item.get("observedAt") if item else None, "ageSeconds": age, "staleAfterSeconds": stale_after, "source": "aws-iot-heartbeat" if item else "no-verified-telemetry"}, "source": "aws", "generatedAt": utc_now()})
        return json_response(404, {"error": "Route not found.", "requestId": request_id})
    except PermissionError as exc:
        # API Gateway's Cognito authorizer normally rejects invalid tokens first.
        return json_response(403 if ("ITAdministrator" in str(exc) or "must belong to" in str(exc)) else 401, {"error": str(exc), "requestId": request_id})
    except ValueError as exc:
        return json_response(400, {"error": str(exc), "requestId": request_id})
    except Exception as exc:
        log_event("ERROR", "api_request_failed", requestId=request_id, errorType=type(exc).__name__, error=str(exc))
        return json_response(500, {"error": "Internal server error. Check the Lambda CloudWatch logs.", "requestId": request_id})
