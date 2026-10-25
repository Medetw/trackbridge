from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "TrackBridge"
    database_url: str = "postgresql+asyncpg://trackbridge:trackbridge@localhost:5432/trackbridge"
    api_keys: str = ""
    public_base_url: str = ""

    telegram_bot_token: SecretStr | None = None
    telegram_webhook_secret: str = ""
    telegram_manager_chat_ids: str = ""

    whatsapp_access_token: SecretStr | None = None
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v21.0"
    whatsapp_template_name: str = ""
    whatsapp_template_lang: str = "ru"

    @property
    def api_key_list(self) -> list[str]:
        return _split_csv(self.api_keys)

    @property
    def manager_chat_ids(self) -> list[int]:
        return [int(chat_id) for chat_id in _split_csv(self.telegram_manager_chat_ids)]

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_bot_token.get_secret_value())

    @property
    def whatsapp_enabled(self) -> bool:
        return bool(
            self.whatsapp_access_token
            and self.whatsapp_access_token.get_secret_value()
            and self.whatsapp_phone_number_id
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
