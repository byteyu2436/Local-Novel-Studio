from pydantic import BaseModel, Field


class MilvusHealth(BaseModel):
    reachable: bool
    status: str
    host: str
    port: int
    health_url: str
    message: str
    hint: str = Field(default="")
