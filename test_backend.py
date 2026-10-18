import json
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("INCIDENTS_TABLE", "incidents")
os.environ.setdefault("NOTIFICATIONS_TABLE", "notifications")
os.environ.setdefault("HEARTBEATS_TABLE", "heartbeats")
os.environ.setdefault("DEDUP_TABLE", "dedup")
os.environ.setdefault("ARCHIVE_BUCKET", "bucket")
os.environ.setdefault("SNS_TOPIC_ARN", "")

import common
import api
import iot_handler

class ValidationTests(unittest.TestCase):
    def test_severity_compatibility(self):
        self.assertEqual(common.normalize_severity("Critical"), "Critical")
        self.assertEqual(common.normalize_severity("low"), "Low")
        with self.assertRaises(ValueError):
            common.normalize_severity("urgent")

    def test_status_values(self):
        self.assertEqual(common.normalize_status("In Progress"), "In Progress")
        self.assertEqual(common.normalize_status("Resolved"), "Resolved")
        with self.assertRaises(ValueError):
            common.normalize_status("Closed")

    def test_create_incident_keeps_dashboard_fields(self):
        item = common.create_incident({
            "type": "Lab network unavailable", "room": "Computer Lab 01",
            "reporter": "Lab Assistant", "severity": "High",
            "description": "Network unavailable", "asset": "SW-LAB01", "action": "Checked switch"
        }, "test-user")
        for key in ("incidentId", "id", "type", "room", "reporter", "severity", "description", "status", "createdAt", "updatedAt", "source", "timeline"):
            self.assertIn(key, item)
        self.assertEqual(item["status"], "Open")

    def test_body_rejects_invalid_json(self):
        with self.assertRaises(ValueError):
            common.parse_body({"body": "{bad json"})

    def test_body_size_limit(self):
        with self.assertRaises(ValueError):
            common.parse_body({"body": " " * 16385})

    def test_dashboard_mapping(self):
        result = common.dashboard_incident({"incidentId": "INC-1", "type": "Power outage", "reporter": "Assistant", "status": "Open"})
        self.assertEqual(result["id"], "INC-1")
        self.assertEqual(result["type"], "Power outage")

    def test_health_route(self):
        response = api.handler({"rawPath": "/health", "requestContext": {"http": {"method": "GET"}}}, MagicMock(aws_request_id="unit"))
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["source"], "aws")

    def test_protected_route_without_claims(self):
        response = api.handler({"rawPath": "/incidents", "requestContext": {"http": {"method": "GET"}}}, MagicMock(aws_request_id="unit"))
        self.assertEqual(response["statusCode"], 401)

    def test_valid_jwt_without_required_group_is_forbidden(self):
        event = {"rawPath": "/incidents", "requestContext": {"http": {"method": "GET"}, "authorizer": {"jwt": {"claims": {"sub": "u1"}}}}}
        response = api.handler(event, MagicMock(aws_request_id="unit"))
        self.assertEqual(response["statusCode"], 403)

    def test_resolve_requires_notes(self):
        event = {
            "rawPath": "/incidents/INC-1", "requestContext": {
                "http": {"method": "PATCH"},
                "authorizer": {"jwt": {"claims": {"sub": "u1", "cognito:groups": ["ITAdministrator"]}}}
            }, "body": json.dumps({"status": "Resolved"})
        }
        with patch("api.get_incident", return_value={"incidentId": "INC-1", "status": "Open", "timeline": [], "createdAt": "2026-01-01T00:00:00Z"}):
            response = api.handler(event, MagicMock(aws_request_id="unit"))
        self.assertEqual(response["statusCode"], 400)

    def test_invalid_incident_input_returns_400(self):
        event = {
            "rawPath": "/incidents", "requestContext": {
                "http": {"method": "POST"},
                "authorizer": {"jwt": {"claims": {"sub": "u1", "email": "assistant@example.edu", "cognito:groups": ["LabAssistant"]}}}
            }, "body": json.dumps({"type": "", "room": "Computer Lab 01", "reporter": "Assistant", "severity": "High", "description": "Failure"})
        }
        response = api.handler(event, MagicMock(aws_request_id="unit"))
        self.assertEqual(response["statusCode"], 400)

    def test_sns_publish_failure_is_recorded(self):
        incident = {"incidentId": "INC-TEST", "severity": "Critical", "type": "Panic button", "room": "LAB01", "description": "test", "createdAt": "2026-10-09T00:00:00Z"}
        with patch.object(common, "TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:topic"), \
             patch.object(common.sns, "publish", side_effect=RuntimeError("SNS unavailable")), \
             patch.object(common, "write_notification") as write_notification:
            result = common.notify_admin(incident)
        self.assertEqual(result, "PUBLISH_FAILED")
        write_notification.assert_called_once()

    def test_s3_archive_failure_does_not_erase_incident(self):
        item = common.create_incident({"type": "Power outage", "room": "Computer Lab 01", "reporter": "Assistant", "severity": "High", "description": "Power loss"}, "Assistant")
        table = MagicMock()
        with patch.object(common.ddb, "Table", return_value=table), patch.object(common, "save_snapshot", side_effect=RuntimeError("S3 unavailable")):
            saved = common.put_incident(item)
        table.put_item.assert_called_once()
        self.assertEqual(saved.get("archiveStatus"), "FAILED")

    def test_dynamodb_failure_is_not_reported_as_success(self):
        item = common.create_incident({"type": "Power outage", "room": "Computer Lab 01", "reporter": "Assistant", "severity": "High", "description": "Power loss"}, "Assistant")
        table = MagicMock()
        table.put_item.side_effect = RuntimeError("DynamoDB unavailable")
        with patch.object(common.ddb, "Table", return_value=table):
            with self.assertRaises(RuntimeError):
                common.put_incident(item)

    def test_duplicate_iot_event_is_ignored(self):
        os.environ["ALLOWED_DEVICE_MAP"] = '{"ESP32-LAB01-001":"LAB01"}'
        table = MagicMock()
        table.put_item.side_effect = ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "duplicate"}}, "PutItem")
        event = {"mqttTopic": "labguard/labs/LAB01/events", "deviceId": "ESP32-LAB01-001", "labId": "LAB01", "eventType": "PANIC_BUTTON_PRESSED", "eventId": "same-event", "occurredAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
        with patch.object(iot_handler.ddb, "Table", return_value=table):
            result = iot_handler.handler(event, MagicMock())
        self.assertTrue(result["duplicate"])

    def test_iot_timestamp_requires_timezone(self):
        with self.assertRaises(ValueError):
            iot_handler._parse_time("2026-10-09T06:15:00")

if __name__ == "__main__":
    unittest.main(verbosity=2)
