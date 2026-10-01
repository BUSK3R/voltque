from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Switch DB by changing DATABASE_URL only, e.g.
    postgresql+psycopg://voltqueue:voltqueue@localhost:5432/voltqueue
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./voltqueue.db"


settings = Settings()
