from app.errors import InvalidRequestError


def validate_path(path: str | None, *, allow_root: bool = False) -> str:
    """
        Normalize and check a caller-supplied file path before any storage call.

        Every route that takes a path uses this, so a bad path gets the same
        400 everywhere and never reaches the provider. A valid path is
        returned in canonical absolute form, with exactly one leading slash.

        Args:
            path: The path from the request, with or without a
                leading slash, e.g. "docs/report.pdf" or "/docs/report.pdf".
            allow_root: Whether the canonical root path is valid. This is
                enabled only by the List operation.
        Returns:
            str: The canonical absolute path.
        Raises:
            InvalidRequestError: If the path is missing, has a control character,
                identifies the root when ``allow_root`` is false, ends with
                "/", or has an empty, "." or ".." segment.
    """
    if not path:
        raise InvalidRequestError("path is required")

    # Newlines, null bytes and other control characters are never valid in a
    # file name, and a newline would split a log line in two.
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        raise InvalidRequestError("path must not contain control characters")

    canonical_path = path if path.startswith("/") else f"/{path}"

    # Root is valid only for List. File and destructive operations keep the
    # default and therefore continue to reject it.
    if canonical_path == "/":
        if allow_root:
            return canonical_path
        raise InvalidRequestError(
            f"path must identify a resource below root: {path}"
        )

    if canonical_path.endswith("/"):
        raise InvalidRequestError(
            f"path must identify a resource below root: {path}"
        )

    for part in canonical_path[1:].split("/"):
        if part in ("", ".", ".."):
            raise InvalidRequestError(f"Invalid path: {path}")

    return canonical_path
