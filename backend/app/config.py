from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ANL_MINEOPS_",
        extra="ignore",
    )

    app_name: str = "ANL MineOps"
    app_version: str = "0.1.0"
    database: str = "./data/mineops.db"
    host: str = "127.0.0.1"
    port: int = 8787
    auth_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
