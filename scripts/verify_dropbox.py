from app.providers.dropbox.client import create_dropbox_client


def main() -> None:
    client = create_dropbox_client()
    account = client.users_get_current_account()

    print("Dropbox connection successful")
    print(f"Account ID: {account.account_id}")
    print(f"Name: {account.name.display_name}")


if __name__ == "__main__":
    main()
