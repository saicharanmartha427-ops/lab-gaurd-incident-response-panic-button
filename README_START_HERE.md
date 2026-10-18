# LabGuard — Complete Project Package

LabGuard is a **software-only college laboratory incident reporting and tracking dashboard**. The webpage's Emergency Alert button opens a prefilled critical incident report. The user must complete and submit the form; the dashboard then records it.

## What is included

- `LabGuard_Emergency_Incident_Response/` — responsive HTML/CSS/JavaScript dashboard with Overview, Report Incident, Incident History, Lab Status, Notifications, System Logs, and Settings. Includes demo records, filters, incident details, status changes, CSV export, local notifications/audit logs, local browser persistence, and the new Emergency Alert shortcut.
- `labguard-backend/` — existing AWS SAM/Python backend scaffold, API handler, shared helpers, requirements, tests, template, and example payloads.
- `PROJECT_GUIDE.md` — how to run the project, test the emergency workflow, understand the architecture, and what remains before live deployment.

## Run the webpage (no hardware required)

1. Extract this ZIP.
2. Open `LabGuard_Emergency_Incident_Response` in VS Code.
3. Open `index.html` using the Live Server extension, or open it directly in a modern browser.
4. Click **Emergency Alert** on Overview. It opens Report Incident with emergency type and Critical severity preselected.
5. Fill in the incident description and reporter name, then submit.
6. Open Incident History and Notifications to see the local demo record.

## Important status

The frontend starts in **demo mode**. Submissions and notifications are stored/simulated in this browser only. No real SMS, email, emergency-services call, or AWS alert is sent in demo mode. The AWS backend is included as a scaffold but is **not deployed or configured** by this ZIP. A real deployment requires AWS account setup, API Gateway/Lambda/DynamoDB configuration, Cognito authentication, appropriate notification configuration, and end-to-end testing. Do not use the demo as a real emergency dispatch system. In a real emergency, contact local emergency services or campus security directly.

See `PROJECT_GUIDE.md` and the frontend `INTEGRATION_GUIDE.md` for more details.
