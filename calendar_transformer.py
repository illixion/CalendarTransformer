"""
CalendarManager: CalDAV Event Transformer

This script reads a local TOML config, connects to Fastmail CalDAV, filters and transforms events, and saves them to a destination calendar without duplicates.

Requirements:
- toml
- caldav

Install with:
  pip install toml caldav
"""

import toml
import caldav
from caldav.elements import dav, cdav
import datetime
import vobject
import logging
import uuid


CONFIG_PATH = "config.toml"

logging.basicConfig(level=logging.INFO)

class EventTransformer:
    def should_delete_event(self, event):
        # Delete if RSVP is DECLINED or summary starts with ❌
        rsvp = event.get("rsvp", "")
        summary = event.get("summary", "")
        if rsvp and rsvp.upper() == "DECLINED":
            return True
        if summary.startswith("❌"):
            return True
        return False

    def __init__(self, config):
        self.config = config
        self.filter_sets = config.get("filter_sets", [])
        self.dest_calendar = config.get("dest_calendar")
        self.max_age_days = config.get("max_age_days", None)

    def match_event(self, event, filter_obj):
        # Filtering logic: calendar name, event name, location substring, negation
        cal_name = event["calendar"]
        summary = event["summary"]
        location = event.get("location", "")
        f = filter_obj.get("filters", {})

        def match_substring(val, substrings, negate=False):
            if not substrings:
                return True
            for s in substrings:
                if (s in val) == negate:
                    return False
            return True

        if f.get("calendar_name") and cal_name != f["calendar_name"]:
            return False
        if f.get("not_calendar_name") and cal_name == f["not_calendar_name"]:
            return False
        if not match_substring(summary, f.get("event_name_contains", []), False):
            return False
        if not match_substring(summary, f.get("event_name_not_contains", []), True):
            return False
        if not match_substring(location, f.get("location_contains", []), False):
            return False
        if not match_substring(location, f.get("location_not_contains", []), True):
            return False
        return True

    def transform_event(self, event, transformation):
        # Apply transformation rules from config only
        t = transformation
        if t.get("set_event_name") is not None:
            event["summary"] = t["set_event_name"]
        if t.get("set_location") is not None:
            event["location"] = t["set_location"]
        if t.get("set_rsvp_status") is not None:
            event["rsvp"] = t["set_rsvp_status"]
        if t.get("strip_name"):
            event["summary"] = ""
        if t.get("strip_location"):
            event["location"] = ""
        return event

    def event_uid(self, event):
        # Use original_uid for duplicate detection
        return event.get('original_uid') or event.get('uid')

    def run(self, client):
        # Load all calendars
        calendars = client.principal().calendars()
        cal_map = {c.name: c for c in calendars}
        dest_cal = cal_map.get(self.dest_calendar)
        if not dest_cal:
            raise Exception(f"Destination calendar '{self.dest_calendar}' not found.")
        # Only load events from source calendars defined in config
        source_calendar_names = set(fs["filters"].get("calendar_name") for fs in self.filter_sets if fs["filters"].get("calendar_name") and fs["filters"].get("calendar_name") != self.dest_calendar)
        all_events = []
        now = datetime.datetime.now(datetime.timezone.utc)
        for cal_name in source_calendar_names:
            cal = cal_map.get(cal_name)
            if not cal:
                print(f"Warning: Source calendar '{cal_name}' not found.")
                continue
            events = cal.events()
            for e in events:
                vevent = None
                if hasattr(e, 'vobject_instance') and e.vobject_instance:
                    vevent = e.vobject_instance.vevent
                else:
                    # Fallback: parse from raw ICS data
                    try:
                        vcal = vobject.readOne(e.data)
                        vevent = vcal.vevent
                    except Exception as ex:
                        print(f"Failed to parse event data: {ex}")
                        continue  # skip this event if parsing fails

                event = {
                    "calendar": cal.name,
                    "uid": getattr(vevent, "uid", None) and vevent.uid.value,
                    "summary": vevent.summary.value,
                    "dtstart": vevent.dtstart.value,
                    "dtend": getattr(vevent, "dtend", None) and vevent.dtend.value,
                    "location": getattr(vevent, "location", None) and vevent.location.value,
                    "rsvp": (
                        getattr(vevent, "partstat", None) and vevent.partstat.value
                        if hasattr(vevent, "partstat")
                        else ""
                    ),
                }
                # Fix: ensure both datetimes are offset-aware for subtraction
                dtstart = event["dtstart"]
                if self.max_age_days is not None:
                    # If dtstart is a date, convert to datetime
                    if isinstance(dtstart, datetime.date) and not isinstance(dtstart, datetime.datetime):
                        dtstart = datetime.datetime.combine(dtstart, datetime.time.min, tzinfo=datetime.timezone.utc)
                    # If dtstart is naive, make it UTC
                    elif isinstance(dtstart, datetime.datetime) and dtstart.tzinfo is None:
                        dtstart = dtstart.replace(tzinfo=datetime.timezone.utc)
                    age = (now - dtstart).days
                    if age > self.max_age_days:
                        continue
                    event["dtstart"] = dtstart
                all_events.append(event)
        # Deletion phase: remove declined/❌ events from dest
        dest_events = dest_cal.events()
        for e in dest_events:
            vevent = e.vobject_instance.vevent
            uid = getattr(vevent, "uid", None) and vevent.uid.value
            summary = vevent.summary.value
            dtstart = vevent.dtstart.value
            location = getattr(vevent, "location", None) and vevent.location.value
            rsvp = (
                getattr(vevent, "partstat", None) and vevent.partstat.value
                if hasattr(vevent, "partstat")
                else ""
            )
            # Find matching source event
            src_event = next(
                (
                    ev
                    for ev in all_events
                    if (
                        ev.get("uid") == uid
                        or (ev["summary"] == summary and ev["dtstart"] == dtstart)
                    )
                ),
                None,
            )
            if src_event and self.should_delete_event(src_event):
                e.delete()
            elif summary.startswith("❌"):
                e.delete()
        # For each filter set, filter and transform
        transformed = []
        for filter_obj in self.filter_sets:
            filtered = [e for e in all_events if self.match_event(e, filter_obj)]
            for e in filtered:
                # Don't add events that should be deleted
                if self.should_delete_event(e):
                    continue
                # Always preserve original UID for dupe detection and ICS export
                e_copy = e.copy()
                e_copy['original_uid'] = e.get('uid')
                transformed.append(
                    self.transform_event(
                        e_copy, filter_obj.get("transformations", {})
                    )
                )
        # Prevent duplicates in dest_calendar using original_uid
        dest_events = dest_cal.events()
        dest_keys = set()
        for e in dest_events:
            vevent = e.vobject_instance.vevent
            # Try to get X-ORIGINAL-UID if present, else fallback to UID
            original_uid = getattr(vevent, "x_original_uid", None)
            if original_uid:
                key = original_uid.value
            else:
                key = vevent.uid.value
            dest_keys.add(key)
        # Save transformed events
        for e in transformed:
            key = self.event_uid(e)
            if key in dest_keys:
                continue  # Skip duplicate
            # Create iCalendar data
            logging.info(f"Adding event: {e['summary']} on {e['dtstart']} to {self.dest_calendar}")
            ical = self.event_to_ical(e)
            dest_cal.save_event(ical, no_overwrite=True)

    def event_to_ical(self, event):
        dtstart = event["dtstart"]
        dtstamp = datetime.datetime.now(datetime.timezone.utc)
        uid = str(uuid.uuid4())  # Always generate a new UUIDv4
        location = event.get("location", "")
        rsvp = event.get("rsvp", "")
        original_uid = event.get("original_uid", "")
        summary = event.get("summary", "")
        # All-day event detection
        is_all_day = False
        dtend = event.get("dtend")
        if isinstance(dtstart, datetime.date) and not isinstance(dtend, datetime.datetime):
            is_all_day = True
        if is_all_day:
            dtstart_date = dtstart.date() if isinstance(dtstart, datetime.datetime) else dtstart
            dtstart_str = dtstart_date.strftime('%Y%m%d')
            dtend_date = dtstart_date + datetime.timedelta(days=1)
            dtend_str = dtend_date.strftime('%Y%m%d')
            ical = (
                "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\n"
                f"UID:{uid}\nDTSTAMP:{dtstamp.strftime('%Y%m%dT%H%M%S')}Z\nSEQUENCE:0\n"
                f"SUMMARY:{summary}\nDTSTART;VALUE=DATE:{dtstart_str}\nDTEND;VALUE=DATE:{dtend_str}\n"
                f"LOCATION:{location}\n"
            )
        else:
            # Timed event
            tzinfo = dtstart.tzinfo
            dtend = event.get("dtend")
            if dtend is None:
                dtend = dtstart + datetime.timedelta(hours=1)
            if tzinfo is not None and tzinfo != datetime.timezone.utc:
                dtstart_str = dtstart.strftime('%Y%m%dT%H%M%S')
                dtend_str = dtend.strftime('%Y%m%dT%H%M%S')
                tzid = tzinfo.tzname(dtstart) if hasattr(tzinfo, 'tzname') else None
                ical = (
                    "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\n"
                    f"UID:{uid}\nDTSTAMP:{dtstamp.strftime('%Y%m%dT%H%M%S')}Z\nSEQUENCE:0\n"
                    f"SUMMARY:{summary}\nDTSTART;TZID={tzid}:{dtstart_str}\nDTEND;TZID={tzid}:{dtend_str}\n"
                    f"LOCATION:{location}\n"
                )
            else:
                # UTC fallback
                if tzinfo is None:
                    dtstart = dtstart.replace(tzinfo=datetime.timezone.utc)
                    dtend = dtend.replace(tzinfo=datetime.timezone.utc)
                dtstart_str = dtstart.strftime('%Y%m%dT%H%M%S') + 'Z'
                dtend_str = dtend.strftime('%Y%m%dT%H%M%S') + 'Z'
                ical = (
                    "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\n"
                    f"UID:{uid}\nDTSTAMP:{dtstamp.strftime('%Y%m%dT%H%M%S')}Z\nSEQUENCE:0\n"
                    f"SUMMARY:{summary}\nDTSTART:{dtstart_str}\nDTEND:{dtend_str}\n"
                    f"LOCATION:{location}\n"
                )
        if original_uid:
            ical += f"X-ORIGINAL-UID:{original_uid}\n"
        if rsvp:
            ical += f"RSVP:{rsvp}\n"
        ical += "END:VEVENT\nEND:VCALENDAR"
        return ical


def main():
    config = toml.load(CONFIG_PATH)
    username = config["fastmail"]["username"]
    password = config["fastmail"]["password"]
    url = config["fastmail"]["url"]
    client = caldav.DAVClient(url=url, username=username, password=password)
    transformer = EventTransformer(config)
    transformer.run(client)


if __name__ == "__main__":
    main()
