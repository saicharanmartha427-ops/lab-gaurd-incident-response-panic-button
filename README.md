# LabGuard — Emergency Incident Response System

A beginner-friendly, responsive college laboratory incident-management dashboard built with **HTML5, CSS3, and vanilla JavaScript**. Chart.js is used for the incident activity chart.

## Run the project

1. Extract `LabGuard_Emergency_Incident_Response.zip`.
2. Open `index.html` in a modern browser.
3. For a more consistent local development experience, use VS Code's **Live Server** extension and open `index.html` with it.

No Node.js build step is required. Google Fonts and Chart.js are loaded from CDNs; if the internet is unavailable, the dashboard still works, but the chart or custom fonts may not load.

## What is implemented

- Seven working navigation pages: Overview, Report Incident, Incident History, Lab Status, Notifications, System Logs, Settings.
- Responsive dark navy sidebar, light operations workspace, red emergency actions, and severity/status colors.
- Overview cards for total, active, and resolved incidents; lab network; ESP32 panic button.
- Lab status for network, computers, and device heartbeat, with simulated telemetry controls.
- Prominent Emergency Alert shortcut on Overview; it opens a prefilled Critical incident form and requires the user to review and submit it.
- Incident form with validation, unique demo incident IDs, descriptions, severity, asset ID, room, reporter, and immediate actions.
- Searchable/filterable incident history, detail modal, status updates, and CSV export.
- Local demo notifications with unread/read handling.
- Local audit logs with filters and JSON export.
- Configurable college name, lab name, administrator contact, and default reporter.
- Demo role selector for Lab Assistant and IT Administrator.
- Local persistence with browser `localStorage`.
- Explicit labels that sample data is simulated and that no AWS request is made in demo mode.

## Safety and demo behavior

**This project starts in demo mode.** The initial incidents, statuses, heartbeat, notifications, and logs are sample data. Form submission, status updates, simulated status controls, and exports operate on browser-local data only. No real incident is sent to AWS; no MQTT message is published; no SNS message is delivered; no S3 object is written; and no CloudWatch log is created.

The demo role selector is not real authentication. Do not deploy this static dashboard publicly with sensitive information or treat the browser's local storage as trusted storage.

## Integration map

Read [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) for recommended API contracts, AWS service responsibilities, security notes, and integration steps.

- **ESP32 → AWS IoT Core (MQTT/TLS):** publish signed/authorized device events to a controlled topic.
- **AWS Lambda:** validate payloads and device identity, generate/record the incident, and initiate the workflow.
- **API Gateway → Lambda:** authenticated dashboard API for incident list/detail/status updates and health status.
- **Amazon SNS:** notify subscribed IT administrators after validation.
- **Amazon S3:** retain incident records with encryption, access control, and lifecycle/retention policies.
- **Amazon CloudWatch:** server-side logs, metrics, alarms, and operational diagnostics.
- **Amazon Cognito:** replace the demo role selector with actual sign-in and role-based authorization.

Do not put AWS access keys, IoT private keys, Cognito secrets, or other credentials in frontend JavaScript.
