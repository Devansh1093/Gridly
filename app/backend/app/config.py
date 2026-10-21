from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    database_url: str = "sqlite:///./app/backend/data/demo.sqlite3"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    frontend_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    rpc_url: str = "http://127.0.0.1:8545"
    chain_id: int = 31337
    contract_address: str = ""
    trade_auth_signer_private_key: str = ""
    preview_token_signing_key: str = ""
    preview_token_ttl_seconds: int = Field(default=300, ge=30, le=1800)
    carbon_data_mode: str = "fixture"
    confirmation_blocks: int = Field(default=1, ge=1)

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value):
        # Render provides postgres:// URLs. Pin SQLAlchemy to the installed
        # psycopg v3 driver instead of its default psycopg2 driver.
        if isinstance(value, str) and value.startswith("postgres://"):
            return "postgresql+psycopg://" + value.removeprefix("postgres://")
        if isinstance(value, str) and value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value.removeprefix("postgresql://")
        return value

    @model_validator(mode="after")
    def validate_local_security(self):
        if self.preview_token_signing_key and len(self.preview_token_signing_key) < 32:
            raise ValueError("PREVIEW_TOKEN_SIGNING_KEY must contain at least 32 characters; run npm run setup:local.")
        if self.carbon_data_mode != "fixture":
            raise ValueError("Only CARBON_DATA_MODE=fixture is implemented in this demo.")
        return self


settings = Settings()
