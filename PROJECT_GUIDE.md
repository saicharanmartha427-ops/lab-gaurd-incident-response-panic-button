# LabGuard Project Guide

## 1. Purpose
LabGuard provides a centralized webpage for reporting, monitoring, and tracking laboratory incidents. Intended users include students, lab assistants, IT administrators, and college management. It addresses delays in reporting, fragmented incident records, and difficulty tracking incident status.

## 2. Main features
- Overview dashboard with incident metrics and activity visualizations.
- Emergency Alert shortcut that opens the incident form and preselects an emergency type and Critical severity. It does not auto-submit.
- Incident reporting form with room, type, severity, reporter, optional asset ID, description, and immediate action.
- Incident history, search/filter, detail view, status updates, CSV export.
- Lab status, simulated notifications, system logs, settings, and local persistence.
- AWS backend scaffold for a future live integration.

## 3. Architecture
**Demo path:** Browser UI → JavaScript validation → browser local storage → dashboard/history/notifications.

**Intended live path (requires deployment):** Browser UI → HTTPS API Gateway → Python AWS Lambda → DynamoDB; optionally Lambda → SNS for configured notifications. Cognito is intended for authentication. This live path is not activated just by extracting the ZIP.

## 4. Suggested test cases
1. Launch `index.html`; verify the dashboard loads.
2. Click Emergency Alert; confirm Report Incident opens with Emergency and Critical selected.
3. Submit with a blank required description; verify validation prevents submission.
4. Submit a complete demo report; verify a new incident ID appears in Incident History.
5. Check Notifications for the simulated local notification.
6. Change the incident status and verify it persists after refreshing the page.
7. Export incident history to CSV.
8. Test on a narrow/mobile viewport.

## 5. Backend checks (optional; requires tools installed)
From `labguard-backend/`, use Python 3.12 and install the packages in `src/requirements.txt` in a virtual environment. Run tests with `python -m unittest discover -s tests -v`. If AWS SAM CLI is installed, validate with `sam validate --lint` and build with `sam build`. Deployment requires an AWS account and configuration; do not deploy until authentication, IAM permissions, API routes, database table settings, and notification destinations have been reviewed.

## 6. Safety, privacy, and limitations
- The browser demo is not an emergency service and does not alert campus staff automatically.
- Demo role selection is not real authentication; localStorage is not secure storage. Do not enter passwords, confidential records, or sensitive personal information.
- The sample dashboard data is illustrative. It does not represent live sensors or physical device telemetry. No hardware is required for this software-only project.
- Before live use, add real authentication and authorization, server-side validation, secure secret handling, rate limiting, logging/monitoring, retention policies, and verified notification delivery. Test with non-emergency sample data first.

## 7. Presentation summary
“LabGuard is a web-based emergency incident response system that helps college laboratories report, monitor, and track incidents through a centralized dashboard.”
