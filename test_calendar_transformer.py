import unittest
import datetime
from unittest.mock import MagicMock, patch
from calendar_transformer import EventTransformer


class MockEvent:
    def __init__(self, summary, dtstart, location="", uid=None, rsvp=None):
        self.vobject_instance = MagicMock()
        self.vobject_instance.vevent = MagicMock()
        self.vobject_instance.vevent.summary.value = summary
        self.vobject_instance.vevent.dtstart.value = dtstart
        self.vobject_instance.vevent.location = MagicMock()
        self.vobject_instance.vevent.location.value = location
        self.vobject_instance.vevent.uid = MagicMock() if uid else None
        if uid:
            self.vobject_instance.vevent.uid.value = uid
        self.vobject_instance.vevent.partstat = MagicMock() if rsvp else None
        if rsvp:
            self.vobject_instance.vevent.partstat.value = rsvp
        self.deleted = False

    def delete(self):
        self.deleted = True


class MockCalendar:
    def __init__(self, name, events):
        self.name = name
        self._events = events

    def events(self):
        return self._events

    def add_event(self, ical):
        self._events.append(ical)


class MockPrincipal:
    def __init__(self, calendars):
        self._calendars = calendars

    def calendars(self):
        return self._calendars


class MockDAVClient:
    def __init__(self, calendars):
        self._principal = MockPrincipal(calendars)

    def principal(self):
        return self._principal


class TestEventTransformerEndToEnd(unittest.TestCase):
    def setUp(self):
        self.config = {
            "filter_sets": [
                {
                    "filters": {"calendar_name": "Personal"},
                    "transformations": {
                        "set_event_name": "Busy",
                        "strip_location": True,
                    },
                },
                {
                    "filters": {"calendar_name": "Work"},
                    "transformations": {
                        "set_event_name": "Busy",
                        "strip_location": True,
                    },
                },
                {
                    "filters": {"calendar_name": "Friends"},
                    "transformations": {
                        "set_event_name": "Busy",
                        "strip_location": True,
                    },
                },
                {
                    "filters": {
                        "calendar_name": "Events",
                        "event_name_not_contains": ["Private", "Secret"],
                        "location_not_contains": ["Hidden"],
                    },
                    "transformations": {},
                },
                {
                    "filters": {"calendar_name": "Photography"},
                    "transformations": {
                        "set_event_name": "Busy",
                        "strip_location": True,
                    },
                },
                {
                    "filters": {"calendar_name": "Company Name"},
                    "transformations": {
                        "set_event_name": "Busy (Work)",
                        "strip_location": True,
                    },
                },
            ],
            "dest_calendar": "dest_calendar",
        }
        self.transformer = EventTransformer(self.config)

    def test_end_to_end(self):
        # Source calendars
        dt = datetime.datetime(2025, 9, 14, 10, 0, 0)
        src_events = [
            MockEvent("Team Meeting", dt, "Conference Room", "uid1", "ACCEPTED"),
            MockEvent("Lunch Meeting", dt, "Cafeteria", "uid2", "DECLINED"),
            MockEvent("❌ Cancelled", dt, "Conference Room", "uid3", "ACCEPTED"),
            MockEvent("Birthday Party", dt, "Home", "uid4", "ACCEPTED"),
            MockEvent("Photo Shoot", dt, "Studio", "uid5", "ACCEPTED"),
            MockEvent("Company Event", dt, "HQ", "uid6", "ACCEPTED"),
            MockEvent("Secret Event", dt, "Hidden", "uid7", "ACCEPTED"),
        ]
        calendars = [
            MockCalendar("Work", [src_events[0], src_events[1], src_events[2]]),
            MockCalendar("Personal", [src_events[3]]),
            MockCalendar("Photography", [src_events[4]]),
            MockCalendar("Company Name", [src_events[5]]),
            MockCalendar("Events", [src_events[6]]),
            MockCalendar("dest_calendar", []),
        ]
        client = MockDAVClient(calendars)

        # Patch add_event to track additions
        dest_cal = calendars[-1]
        added_events = []

        def add_event_patch(ical):
            added_events.append(ical)

        dest_cal.add_event = add_event_patch

        # Patch delete to track deletions
        for cal in calendars:
            for e in cal.events():
                e.delete = MagicMock(side_effect=e.delete)

        self.transformer.run(client)

        # Check that declined and ❌ events are not added
        for ical in added_events:
            self.assertNotIn("Lunch Meeting", ical)
            self.assertNotIn("❌ Cancelled", ical)
        # Check transformation for Personal, Work, Friends
        self.assertTrue(any("SUMMARY:Busy" in ical for ical in added_events))
        # Check transformation for Photography
        self.assertTrue(any("SUMMARY:Busy" in ical for ical in added_events))
        # Check transformation for Company Name
        self.assertTrue(any("SUMMARY:Busy (Work)" in ical for ical in added_events))
        # Check Events calendar exclusion
        self.assertFalse(any("SUMMARY:Secret Event" in ical for ical in added_events))
        self.assertFalse(any("LOCATION:Hidden" in ical for ical in added_events))


if __name__ == "__main__":
    unittest.main()
