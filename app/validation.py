from app.errors import InvalidRequestError


def validate_path(path: str | None) -> str:
    """
        Check a caller-supplied file path before any storage call.

        Every route that takes a path uses this, so a bad path gets the same
        400 everywhere and never reaches the provider.

        Args:
            path (str | None): The path from the request, e.g. "/docs/report.pdf".
        Returns:
            str: The same path, unchanged.
        Raises:
            InvalidRequestError: If the path is missing, has a control character,
                does not start with "/", ends with "/", or has an empty, "."
                or ".." segment.
    """
    if not path:
        raise InvalidRequestError("path is required")

    # Newlines, null bytes and other control characters are never valid in a
    # file name, and a newline would split a log line in two.
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        raise InvalidRequestError("path must not contain control characters")

    if not path.startswith("/") or path.endswith("/"):
        raise InvalidRequestError(
            f"path must start with / and end with a file name: {path}"
        )

    for part in path[1:].split("/"):
        if part in ("", ".", ".."):
            raise InvalidRequestError(f"Invalid path: {path}")

    return path
