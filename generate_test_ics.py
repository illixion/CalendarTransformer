import datetime

def make_ics_event(summary, dtstart, dtend, location="", uid=None, rsvp=None):
    uid = uid or f"{summary}_{dtstart}".replace(" ", "_")
    ical = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"SUMMARY:{summary}",
        f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%S')}",
        f"DTEND:{dtend.strftime('%Y%m%dT%H%M%S')}",
        f"LOCATION:{location}",
    ]
    if rsvp:
        ical.append(f"RSVP:{rsvp}")
    ical.append("END:VEVENT")
    return "\n".join(ical)

dt = datetime.datetime(2025, 9, 14, 10, 0, 0)
events = [
    make_ics_event("Team Meeting", dt, dt + datetime.timedelta(hours=1), "Conference Room", "uid1", "ACCEPTED"),
    make_ics_event("Lunch Meeting", dt, dt + datetime.timedelta(hours=1), "Cafeteria", "uid2", "DECLINED"),
    make_ics_event("❌ Cancelled", dt, dt + datetime.timedelta(hours=1), "Conference Room", "uid3", "ACCEPTED"),
    make_ics_event("Birthday Party", dt, dt + datetime.timedelta(hours=1), "Home", "uid4", "ACCEPTED"),
    make_ics_event("Photo Shoot", dt, dt + datetime.timedelta(hours=1), "Studio", "uid5", "ACCEPTED"),
    make_ics_event("Company Event", dt, dt + datetime.timedelta(hours=1), "HQ", "uid6", "ACCEPTED"),
    make_ics_event("Secret Event", dt, dt + datetime.timedelta(hours=1), "Hidden", "uid7", "ACCEPTED"),
]

ics_content = "BEGIN:VCALENDAR\nVERSION:2.0\n" + "\n".join(events) + "\nEND:VCALENDAR"

with open("test_events.ics", "w") as f:
    f.write(ics_content)