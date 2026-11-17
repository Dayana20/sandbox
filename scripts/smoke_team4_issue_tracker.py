import os
import uuid

from app.integrations.issue_tracker import get_issue_provider


def main() -> None:
    required_settings = ("TRELLO_API_KEY", "TRELLO_TOKEN", "TRELLO_LIST_ID")
    trello_settings = {name: os.getenv(name) for name in required_settings}
    if os.getenv("TRACKER_IMPL") != "team4" or any(
        not value or not value.strip() for value in trello_settings.values()
    ):
        print("Skipped: set TRACKER_IMPL=team4 and all TRELLO settings to run.")
        return

    provider = get_issue_provider()
    issue = None

    try:
        issue = provider.create_issue(f"Issue tracker smoke test {uuid.uuid4().hex}")
        print("create: passed")

        observed = provider.get_issue(issue.id, fresh=True)
        if observed.id != issue.id:
            raise RuntimeError("Issue tracker smoke read returned the wrong issue.")
        print("read: passed")
    except Exception as error:
        step = "read" if issue is not None else "create"
        print(f"{step}: failed ({type(error).__name__})")
        raise SystemExit(1) from None
    finally:
        if issue is not None:
            try:
                provider.delete_issue(issue.id)
                print("delete: passed")
            except Exception as error:
                print(f"delete: failed ({type(error).__name__})")
                raise SystemExit(1) from None


if __name__ == "__main__":
    main()
