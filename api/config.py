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


settings = Settings()
