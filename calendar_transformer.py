import toml
import caldav
from caldav.elements import dav, cdav
import datetime
from dateutil.tz import gettz
import vobject
import logging
import uuid


CONFIG_PATH = "config.toml"

logging.basicConfig(level=logging.INFO)

def ensure_list(val):
    if val is None:
        return []
    if isinstance(val, str):
        return [val]
    return list(val)

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
        self.history_keep_days = config.get("history_keep_days", None)

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
        if not match_substring(summary, ensure_list(f.get("event_name_contains", [])), False):
            return False
        if not match_substring(summary, ensure_list(f.get("event_name_not_contains", [])), True):
            return False
        if not match_substring(location, ensure_list(f.get("location_contains", [])), False):
            return False
        if not match_substring(location, ensure_list(f.get("location_not_contains", [])), True):
            return False
        return True

    def transform_event(self, event, transformation):
        # Apply transformation rules from config only
        t = transformation

        def match_substring(val, substrings, negate=False):
            if not substrings:
                return False
            # Normalize the input string by removing all newlines
            val = val or ""
            normalized_val = val.replace('\n', ' ').strip()
            for s in substrings:
                # Normalize the config string as well, in case it has unintended newlines
                normalized_s = s.replace('\n', ' ').strip()
                if (normalized_s in normalized_val) != negate:
                    return True
            return False

        if t.get("set_event_name") is not None:
            event["summary"] = t["set_event_name"]
        if t.get("set_location") is not None:
            event["location"] = t["set_location"]
        if t.get("set_rsvp_status") is not None:
            event["rsvp"] = t["set_rsvp_status"]

        # Conditional stripping for event name
        strip_name = t.get("strip_name", False)
        do_strip_name = strip_name
        if strip_name or t.get("strip_if_event_name_contains") or t.get("strip_if_event_name_not_contains"):
            # If substring found in event name, strip
            if match_substring(event.get("summary", ""), ensure_list(t.get("strip_if_event_name_contains", [])), False):
                do_strip_name = True
            # If substring found in event name _not_, skip stripping
            if match_substring(event.get("summary", ""), ensure_list(t.get("strip_if_event_name_not_contains", [])), True):
                do_strip_name = False
        if do_strip_name:
            event["summary"] = ""


        # Conditional stripping for location
        strip_location = t.get("strip_location", False)
        do_strip_location = strip_location
        if strip_location or t.get("strip_if_location_contains") or t.get("strip_if_location_not_contains"):
            # If substring found in location, strip
            if match_substring(event.get("location", ""), ensure_list(t.get("strip_if_location_contains", [])), False):
                do_strip_location = True
            # If substring found in location _not_, skip stripping
            if match_substring(event.get("location", ""), ensure_list(t.get("strip_if_location_not_contains", [])), False):
                do_strip_location = False
        if do_strip_location:
            event["location"] = ""
        return event

    def event_uid(self, event):
        # Use original_uid for duplicate detection
        return event.get('original_uid') or event.get('uid')

    def sanitize_text(self, text):
        if not text:
            return ""
        # Escape backslashes, semicolons, and commas
        text = text.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,')
        # Replace newlines with escaped n
        text = text.replace('\n', '\\n')
        # You may need to fold long lines if they exceed 75 characters, but for newlines, the above is the key fix
        return text

    def run(self, client):
        # Load all calendars
        calendars = client.principal().calendars()
        cal_map = {c.name: c for c in calendars}
        dest_cal = cal_map.get(self.dest_calendar)
        if not dest_cal:
            raise Exception(f"Destination calendar '{self.dest_calendar}' not found.")
        now = datetime.datetime.now(datetime.timezone.utc)
        if self.max_age_days is not None and self.max_age_days > 0:
            start_time = now - datetime.timedelta(days=self.max_age_days)
            end_time = now + datetime.timedelta(days=self.max_age_days)
        else:
            start_time = now - datetime.timedelta(days=365)
            end_time = now + datetime.timedelta(days=365)

        # Delete old events from the destination calendar based on history_keep_days
        if self.history_keep_days is not None:
            dest_events_to_delete = []
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            dest_events = dest_cal.events()
            
            for e in dest_events:
                try:
                    vevent = e.vobject_instance.vevent
                    dtend = getattr(vevent, "dtend", None) and vevent.dtend.value
                    
                    if self.history_keep_days == 0:
                        # Case 1: Delete all past events (history_keep_days = 0)
                        if dtend:
                            # Normalize dtend for comparison with now_utc
                            dtend_aware = dtend.astimezone(datetime.timezone.utc) if isinstance(dtend, datetime.datetime) else datetime.datetime.combine(dtend, datetime.time.min, tzinfo=datetime.timezone.utc)
                            if dtend_aware < now_utc:
                                dest_events_to_delete.append(e)
                    elif self.history_keep_days > 0:
                        # Case 2: Delete events older than history_keep_days
                        dtstart = vevent.dtstart.value
                        dtstart_aware = dtstart.astimezone(datetime.timezone.utc) if isinstance(dtstart, datetime.datetime) else datetime.datetime.combine(dtstart, datetime.time.min, tzinfo=datetime.timezone.utc)
                        history_limit = now_utc - datetime.timedelta(days=self.history_keep_days)
                        if dtstart_aware < history_limit:
                            dest_events_to_delete.append(e)
                except Exception as ex:
                    logging.error(f"Failed to parse or process destination event for deletion: {ex}")
                    continue

            for e in dest_events_to_delete:
                logging.info(f"Deleting old event: {e.vobject_instance.vevent.summary.value} from {self.dest_calendar}")
                e.delete()

        # For each filter set, process only events from its source calendar
        transformed = []
        source_events_by_cal = {}
        for filter_obj in self.filter_sets:
            cal_name = filter_obj["filters"].get("calendar_name")
            if not cal_name or cal_name == self.dest_calendar:
                continue
            if cal_name not in source_events_by_cal:
                cal = cal_map.get(cal_name)
                if not cal:
                    print(f"Warning: Source calendar '{cal_name}' not found.")
                    source_events_by_cal[cal_name] = []
                    continue
                events = cal.search(
                    start=start_time,
                    end=end_time,
                    event=True,
                    expand=True
                )
                event_list = []
                for e in events:
                    vevent = None
                    if hasattr(e, 'vobject_instance') and e.vobject_instance:
                        vevent = e.vobject_instance.vevent
                    else:
                        try:
                            vcal = vobject.readOne(e.data)
                            vevent = vcal.vevent
                        except Exception as ex:
                            print(f"Failed to parse event data: {ex}")
                            continue
                    # Extract dtstart, dtend, duration
                    dtstart = vevent.dtstart.value
                    dtend = getattr(vevent, "dtend", None) and vevent.dtend.value
                    duration = getattr(vevent, "duration", None) and vevent.duration.value
                    # If duration is present and dtend is missing, calculate dtend
                    if duration and not dtend:
                        if isinstance(dtstart, datetime.datetime):
                            dtend = dtstart + duration
                        elif isinstance(dtstart, datetime.date):
                            # For all-day events, duration should be timedelta
                            dtend = dtstart + duration
                    event = {
                        "calendar": cal.name,
                        "uid": getattr(vevent, "uid", None) and vevent.uid.value,
                        "summary": vevent.summary.value,
                        "dtstart": dtstart,
                        "dtend": dtend,
                        "location": getattr(vevent, "location", None) and vevent.location.value,
                        "rsvp": (
                            getattr(vevent, "partstat", None) and vevent.partstat.value
                            if hasattr(vevent, "partstat")
                            else ""
                        ),
                    }

                    # Use a default timezone if the event is naive
                    local_tz = datetime.datetime.now().astimezone().tzinfo
                    
                    if isinstance(event['dtstart'], datetime.datetime) and event['dtstart'].tzinfo is None:
                        # Assume naive events are in the local system timezone
                        event['dtstart'] = event['dtstart'].replace(tzinfo=local_tz)
                        if event['dtend'] and isinstance(event['dtend'], datetime.datetime) and event['dtend'].tzinfo is None:
                            event['dtend'] = event['dtend'].replace(tzinfo=local_tz)

                    # Now, convert all timezone-aware timed events to UTC for internal consistency
                    if isinstance(event['dtstart'], datetime.datetime):
                        event['dtstart'] = event['dtstart'].astimezone(datetime.timezone.utc)
                        if event['dtend'] and isinstance(event['dtend'], datetime.datetime):
                            event['dtend'] = event['dtend'].astimezone(datetime.timezone.utc)
                    
                    # Fix: ensure both datetimes are offset-aware for subtraction
                    dtstart = event["dtstart"]

                    if self.max_age_days is not None and self.max_age_days > 0:
                        if isinstance(dtstart, datetime.date) and not isinstance(dtstart, datetime.datetime):
                            dtstart = datetime.datetime.combine(dtstart, datetime.time.min, tzinfo=datetime.timezone.utc)
                        elif isinstance(dtstart, datetime.datetime) and dtstart.tzinfo is None:
                            dtstart = dtstart.replace(tzinfo=datetime.timezone.utc)
                        age = (now - dtstart).days
                        if age > self.max_age_days:
                            continue
                        event["dtstart"] = dtstart
                    event_list.append(event)
                source_events_by_cal[cal_name] = event_list
            # Only process events from this filter's calendar
            filtered = [e for e in source_events_by_cal[cal_name] if self.match_event(e, filter_obj)]
            for e in filtered:
                if self.should_delete_event(e):
                    continue
                e_copy = e.copy()
                e_copy['original_uid'] = e.get('uid')
                transformed.append(
                    self.transform_event(
                        e_copy, filter_obj.get("transformations", {})
                    )
                )

        # Deletion phase: remove declined/❌ events from dest
        dest_events = dest_cal.events()
        for e in dest_events:
            vevent = e.vobject_instance.vevent
            uid = getattr(vevent, "uid", None) and vevent.uid.value
            summary = vevent.summary.value
            dtstart = vevent.dtstart.value
            # Find matching source event
            src_event = next(
                (
                    ev
                    for ev in transformed
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

        # Prevent duplicates in dest_calendar using original_uid
        dest_events = dest_cal.events()
        dest_keys = set()
        for e in dest_events:
            vevent = e.vobject_instance.vevent
            original_uid = getattr(vevent, "x_original_uid", None)
            if original_uid:
                key = original_uid.value
            else:
                key = vevent.uid.value
            dest_keys.add(key)
        # Print count of events we're about to add
        logging.info(f"Found {len(transformed)} eligible events, will add to '{self.dest_calendar}'.")
        # Save transformed events
        for e in transformed:
            key = self.event_uid(e)
            if key in dest_keys:
                continue  # Skip duplicate
            logging.info(f"Adding event: {e['summary']} on {e['dtstart']} to {self.dest_calendar}")
            ical = self.event_to_ical(e)
            dest_cal.save_event(ical, no_overwrite=True)

    def event_to_ical(self, event):

        dtstart = event["dtstart"]
        dtend = event.get("dtend")

        ical_parts = [
            "BEGIN:VCALENDAR\nVERSION:2.0\n",
            "BEGIN:VEVENT\n",
            f"UID:{str(uuid.uuid4())}\n",
            f"DTSTAMP:{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S')}Z\n",
            f"SUMMARY:{event.get('summary', '')}\n",
        ]

        # All-day event detection
        is_all_day = isinstance(dtstart, datetime.date) and not isinstance(dtstart, datetime.datetime)

        if is_all_day:
            dtstart_date = dtstart.date() if isinstance(dtstart, datetime.datetime) else dtstart
            if dtend:
                dtend_date = dtend.date() if isinstance(dtend, datetime.datetime) else dtend
            else:
                dtend_date = dtstart_date + datetime.timedelta(days=1)
            ical_parts.append(f"DTSTART;VALUE=DATE:{dtstart_date.strftime('%Y%m%d')}\n")
            ical_parts.append(f"DTEND;VALUE=DATE:{dtend_date.strftime('%Y%m%d')}\n")
        else:
            # Timed events (UTC)
            if dtend is None:
                # Try to use duration if present
                duration = event.get("duration")
                if duration:
                    dtend = dtstart + duration
                else:
                    dtend = dtstart + datetime.timedelta(hours=1)
            # Use the UTC times for iCalendar output
            dtstart_str = dtstart.strftime('%Y%m%dT%H%M%S') + 'Z'
            dtend_str = dtend.strftime('%Y%m%dT%H%M%S') + 'Z'
            ical_parts.append(f"DTSTART:{dtstart_str}\n")
            ical_parts.append(f"DTEND:{dtend_str}\n")

        if event.get("location"):
            sanitized_location = self.sanitize_text(event['location'])
            ical_parts.append(f"LOCATION:{sanitized_location}\n")
        if event.get("original_uid"):
            ical_parts.append(f"X-ORIGINAL-UID:{event['original_uid']}\n")
        if event.get("rsvp"):
            ical_parts.append(f"RSVP:{event['rsvp']}\n")

        ical_parts.append("END:VEVENT\nEND:VCALENDAR")
        return "".join(ical_parts)


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
