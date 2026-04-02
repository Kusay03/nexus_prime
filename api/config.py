from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str
    redis_url: str = "redis://localhost:6379"
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60
    allowed_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    rate_limit_enabled: bool = True
    rate_limit_api_max_requests: int = 120
    rate_limit_api_window_seconds: int = 60
    rate_limit_auth_max_requests: int = 5
    rate_limit_auth_window_seconds: int = 60


settings = Settings()
