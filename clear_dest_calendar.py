import toml
import caldav
import logging

CONFIG_PATH = "config.toml"

logging.basicConfig(level=logging.INFO)

def main():
    config = toml.load(CONFIG_PATH)
    username = config["fastmail"]["username"]
    password = config["fastmail"]["password"]
    url = config["fastmail"]["url"]
    dest_calendar_name = config["dest_calendar"]

    client = caldav.DAVClient(url=url, username=username, password=password)
    calendars = client.principal().calendars()
    cal_map = {c.name: c for c in calendars}
    dest_cal = cal_map.get(dest_calendar_name)
    if not dest_cal:
        raise Exception(f"Destination calendar '{dest_calendar_name}' not found.")

    events = dest_cal.events()
    logging.info(f"Found {len(events)} events in destination calendar '{dest_calendar_name}'. Deleting...")
    for e in events:
        try:
            e.delete()
            logging.info(f"Deleted event UID: {getattr(e.vobject_instance.vevent, 'uid', None) and e.vobject_instance.vevent.uid.value}")
        except Exception as ex:
            logging.error(f"Failed to delete event: {ex}")
    logging.info("All events deleted from destination calendar.")

if __name__ == "__main__":
    main()
