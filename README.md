# CalendarTransformer

CalendarTransformer is a Python tool for synchronizing, transforming, and deduplicating calendar events between Fastmail CalDAV calendars. It reads a TOML config file to filter, transform, and copy events from multiple source calendars into a destination calendar, ensuring no duplicates and supporting advanced filtering and transformation rules.

## Features

- Sync events from multiple Fastmail CalDAV calendars
- Filter events by calendar name, event name, location, and substring match (with negation)
- Transform event name, location, RSVP status, and more
- Save transformed events to a destination calendar, avoiding duplicates
- Delete events from the destination calendar if declined or marked for removal
- Supports all-day and timed events, preserving original timezones
- Configurable max age for event processing

## Requirements

- Python 3.8+
- [toml](https://pypi.org/project/toml/)
- [caldav](https://pypi.org/project/caldav/)
- [vobject](https://pypi.org/project/vobject/)

Install dependencies:
```sh
pip install toml caldav vobject
```

## Usage

1. Configure your Fastmail app password and calendar names in `config.toml`.
2. Run the script:
   ```sh
   python calendar_transformer.py
   ```
3. The script will sync, transform, and deduplicate events as specified in your config.

## Configuration (`config.toml`)

### Fastmail Credentials

```toml
[fastmail]
username = "your_fastmail_username"
password = "your_fastmail_app_password"
url = "https://caldav.fastmail.com/dav/"
```

### Destination Calendar

```toml
dest_calendar = "DestinationCalendarName"
```

### Future Scan Days (Optional)

Limits how far into the future to scan for events (number of days from now).
```toml
future_scan_days = 30
```

### Past Keep Days (Optional)

Determines how many days in the past to keep events (number of days before now).
- Omit to keep full history
- Use 0 to not keep history

```toml
past_keep_days = 30
```

### Filter Sets

Define multiple filter sets to control which events are selected and how they are transformed.
```toml
[[filter_sets]]
filters = { calendar_name = "Work", event_name_contains = ["Meeting"], location_not_contains = ["Cafeteria"] }
transformations = {
   set_event_name = "Busy",
   strip_location = true,
   strip_if_location_contains = ["HQ"],
   strip_if_location_not_contains = ["Remote"],
   strip_name = true,
   strip_if_event_name_contains = ["Private"],
   strip_if_event_name_not_contains = ["Public"]
}
```

#### Transformation Options

- `set_event_name`: Set the event name to a specific value.
- `set_location`: Set the event location to a specific value.
- `set_rsvp_status`: Set RSVP status.
- `strip_name`: Remove the event name (configurable with filters below).
- `strip_location`: Remove the event location (configurable with filters below).
- `strip_if_event_name_contains`: If any listed substring is present in the event name, strip the name.
- `strip_if_event_name_not_contains`: If any listed substring is **not** present in the event name, do **not** strip the name.
- `strip_if_location_contains`: If any listed substring is present in the location, strip the location.
- `strip_if_location_not_contains`: If any listed substring is **not** present in the location, do **not** strip the location.

#### Filter Options

- `calendar_name`: Only include events from this calendar
- `not_calendar_name`: Exclude events from this calendar
- `event_name_contains`: Only include events whose name contains any of these substrings
- `event_name_not_contains`: Exclude events whose name contains any of these substrings
- `location_contains`: Only include events whose location contains any of these substrings
- `location_not_contains`: Exclude events whose location contains any of these substrings

## How It Works

- The script loads events from source calendars defined in your config
- Filters and transforms events according to your rules
- Deduplicates using the original event UID (not the transformed name/time)
- Preserves original timezones and all-day/timed event status
- Writes new events to the destination calendar with a random UID, storing the original UID in `X-ORIGINAL-UID` for future deduplication
- Deletes events from the destination calendar if declined or marked for removal

## Notes

- The script is designed to run once and exit; use a scheduler (e.g., systemd) for periodic sync
- Only events from calendars listed in your config are processed
- All-day events and timezones are handled automatically
- For best results, use a dedicated destination calendar

## Systemd How-To

This project can be scheduled to run automatically every hour using systemd.
The setup uses a oneshot service (runs once and exits) together with a systemd timer (triggers it hourly).

1. Create a dedicated system user

For security, do not run the script as root. Create a special user:

```
sudo useradd -r -s /usr/sbin/nologin calendar
sudo chown -R calendar:calendar /opt/CalendarTransformer
```

2. Service unit file

Create `/etc/systemd/system/calendar-transformer.service`:

```
[Unit]
Description=Calendar Transformer Job

[Service]
Type=oneshot
User=calendar
Group=calendar
WorkingDirectory=/opt/CalendarTransformer
ExecStart=/opt/CalendarTransformer/venv/bin/python /opt/CalendarTransformer/calendar_transformer.py
TimeoutStartSec=180
```

3. Timer unit file

Create `/etc/systemd/system/calendar-transformer.timer`:

```
[Unit]
Description=Run Calendar Transformer every hour

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

- OnCalendar=hourly → runs at the start of every hour
- Persistent=true → runs missed jobs after reboot

4. Enable and start

Reload systemd, enable the timer, and start it:

```
sudo systemctl daemon-reload
sudo systemctl enable --now calendar-transformer.timer
```

5. Useful commands

- Check when it will run next:

`systemctl list-timers | grep calendar-transformer`


- Manually run the script immediately:

`sudo systemctl start calendar-transformer.service`


- Check logs of last run:

`journalctl -u calendar-transformer.service -e`


- Stop automatic scheduling:

`sudo systemctl disable --now calendar-transformer.timer`


- Show unit status:

```
systemctl status calendar-transformer.service
systemctl status calendar-transformer.timer
```

6. File overview

| Path | Purpose |
|--------|-------------|
| /etc/systemd/system/calendar-transformer.service | Runs the Python script once |
| /etc/systemd/system/calendar-transformer.timer | Triggers the service every hour |
| /opt/CalendarTransformer/calendar_transformer.py | Your project’s main script |
| /opt/CalendarTransformer/config.toml | Configuration file |
| /opt/CalendarTransformer/venv/ | Python virtual environment |

## License

MIT
