from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    environment: str
    use_mocks: bool
