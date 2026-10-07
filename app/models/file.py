from datetime import datetime

from pydantic import BaseModel


class FileResource(BaseModel):
    id: str
    name: str
    path: str
    size: int
    modified_at: datetime | None = None