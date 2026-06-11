app_name = "bytehr_connector"
app_title = "ByteHR Connector"
app_publisher = "K Garden"
app_description = "Pull ByteHR employees and timesheets into ERPNext"
app_email = "ai.developer@kgarden.local"
app_license = "MIT"

# Daily (not hourly): ByteHR caps the key at 1,000 requests/month, so every
# call has to be budgeted. See bytehr/client.py for the persistent counter.
scheduler_events = {
    "daily": [
        "bytehr_connector.bytehr.sync.pull_all",
    ]
}
