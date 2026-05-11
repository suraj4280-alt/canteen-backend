from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "canteen_db"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    DB_URL: str = ""
    
    SECRET_KEY: str = "secret"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8000"
    ENVIRONMENT: str = "development"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()

# Prevent running with default SECRET_KEY in production or staging
if settings.ENVIRONMENT in ("production", "staging") and settings.SECRET_KEY == "secret":
    raise ValueError(
        "FATAL: SECRET_KEY is set to the default value 'secret'. "
        "Set a strong SECRET_KEY in your .env file before running in production/staging."
    )
