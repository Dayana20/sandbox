from datetime import datetime, timedelta, timezone
import os
import uuid

from app.integrations.calendar import get_calendar_service
from calendar_contract import CreateEvent


def main() -> None:
    if os.getenv("CALENDAR_IMPL") != "team5" or not os.getenv("TEAM5_TOKEN_FILE"):
        print("Skipped: set CALENDAR_IMPL=team5 and TEAM5_TOKEN_FILE to run.")
        return

    calendar = get_calendar_service()
    start = datetime.now(timezone.utc) + timedelta(days=1)
    event = None

    try:
        event = calendar.create(
            CreateEvent(
                title=f"Calendar smoke test {uuid.uuid4().hex}",
                start=start.isoformat(),
                end=(start + timedelta(minutes=15)).isoformat(),
            )
        )
        print("create: passed")

        observed = calendar.get(event.id)
        if observed.id != event.id:
            raise RuntimeError("Calendar smoke read returned the wrong event.")
        print("read: passed")
    except Exception as error:
        step = "read" if event is not None else "create"
        print(f"{step}: failed ({type(error).__name__})")
        raise SystemExit(1) from None
    finally:
        if event is not None:
            try:
                calendar.delete(event.id)
                print("delete: passed")
            except Exception as error:
                print(f"delete: failed ({type(error).__name__})")
                raise SystemExit(1) from None


if __name__ == "__main__":
    main()
