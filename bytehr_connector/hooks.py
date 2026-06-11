app_name = "bytehr_connector"
app_title = "ByteHR Connector"
app_publisher = "K Garden"
app_description = "Pull ByteHR employees and timesheets into ERPNext"
app_email = "ai.developer@kgarden.local"
app_license = "MIT"

# Show ByteHR as a tile on the /apps screen.
add_to_apps_screen = [
    {
        "name": "bytehr_connector",
        "logo": "/assets/bytehr_connector/images/bytehr-logo.svg",
        "title": "ByteHR",
        "route": "/app/bytehr-timesheet",
    }
]

# Daily (not hourly): ByteHR caps the key at 1,000 requests/month, so every
# call has to be budgeted. See bytehr/client.py for the persistent counter.
scheduler_events = {
    "daily": [
        "bytehr_connector.bytehr.sync.pull_all",
    ]
}
