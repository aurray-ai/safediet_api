from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SafeDaet API"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    uvicorn_workers: int = 2

    jwt_secret_key: SecretStr = SecretStr("change-this-secret-before-production")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    openai_api_key: SecretStr | None = None
    openai_meal_conversation_model: str = "gpt-5-mini"
    openai_meal_conversation_timeout_seconds: float = 30.0
    openai_meal_search_embedding_model: str = "text-embedding-3-small"
    openai_meal_search_embedding_timeout_seconds: float = 20.0
    openai_grocery_search_embedding_model: str = "text-embedding-3-small"
    openai_grocery_search_embedding_timeout_seconds: float = 20.0
    openai_promotion_generation_model: str = "gpt-5-mini"
    openai_promotion_generation_timeout_seconds: float = 30.0
    apns_key_id: str | None = None
    apns_team_id: str | None = None
    apns_bundle_id: str | None = None
    apns_private_key: SecretStr | None = None
    apns_private_key_path: str | None = None
    apns_use_sandbox_by_default: bool = True
    apns_connect_timeout_seconds: float = 10.0
    apns_read_timeout_seconds: float = 10.0
    stripe_api_key: SecretStr | None = None
    stripe_publishable_key: str | None = None
    stripe_webhook_secret: SecretStr | None = None
    stripe_api_base_url: str = "https://api.stripe.com"
    stripe_webhook_tolerance_seconds: int = 300
    resend_api_key: SecretStr | None = None
    resend_api_base_url: str = "https://api.resend.com"
    resend_timeout_seconds: float = 10.0
    email_from_address: str | None = None
    email_from_name: str = "Safediet"
    email_reply_to: str | None = None
    web_app_base_url: str = "http://localhost:3000"
    api_public_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "api_public_base_url",
            "API_PUBLIC_BASE_URL",
            "BACKEND_PUBLIC_BASE_URL",
            "PUBLIC_API_BASE_URL",
        ),
    )
    password_reset_token_ttl_minutes: int = 30
    household_invitation_token_ttl_days: int = 7
    staff_invitation_token_ttl_days: int = 7

    mongodb_url: str = Field(
        default="mongodb://mongo:27017",
        validation_alias=AliasChoices("MONGODB_URL", "MONGODB_URI"),
    )
    mongodb_database: str = "safedaet"
    mongodb_server_selection_timeout_ms: int = 5000
    mongodb_connect_timeout_ms: int = 10000
    mongodb_socket_timeout_ms: int = 10000
    mongodb_connect_retries: int = 3
    mongodb_connect_retry_delay_seconds: float = 2.0
    redis_url: str | None = None
    redis_socket_timeout_seconds: float = 2.0
    redis_connect_timeout_seconds: float = 2.0
    planner_cache_conversation_ttl_seconds: int = 900
    planner_cache_recent_messages_ttl_seconds: int = 900
    planner_cache_recent_messages_limit: int = 80
    meal_conversation_history_window_messages: int = 40
    meal_semantic_search_candidate_pool_limit: int = 180
    meal_semantic_search_embedding_batch_size: int = 24
    meal_planner_monitoring_enabled: bool = True
    meal_planner_monitoring_capture_payloads: bool = True
    meal_planner_monitoring_event_preview_limit: int = 40
    background_unsaved_plan_scan_interval_seconds: int = 30 * 60
    background_unsaved_plan_scan_batch_limit: int = 500
    background_meal_slot_reminder_scan_interval_seconds: int = 20 * 60
    background_meal_slot_reminder_scan_batch_limit: int = 500
    background_meal_slot_default_timezone: str = "Europe/London"
    background_meal_slot_breakfast_start_hour: int = 5
    background_meal_slot_breakfast_end_hour: int = 10
    background_meal_slot_lunch_start_hour: int = 11
    background_meal_slot_lunch_end_hour: int = 15
    background_meal_slot_dinner_start_hour: int = 17
    background_meal_slot_dinner_end_hour: int = 21
    background_meal_slot_snack_enabled: bool = False
    background_meal_slot_snack_start_hour: int = 16
    background_meal_slot_snack_end_hour: int = 16
    cache_entity_ttl_seconds: int = 3600
    cache_query_ttl_seconds: int = 600
    cache_log_hits: bool = False
    grocery_default_store_id: str = "main_store"
    grocery_checkout_quote_ttl_seconds: int = 900
    grocery_cart_ttl_seconds: int = 7 * 24 * 60 * 60
    grocery_order_cancellation_window_minutes: int = 20
    grocery_default_currency: str = "GBP"
    grocery_free_delivery_subtotal_minor: int = 2000
    grocery_delivery_default_timezone: str = "Europe/London"
    grocery_max_cart_items: int = 100
    grocery_max_quantity_per_line: int = 25
    meal_checkout_quote_ttl_seconds: int = 900
    meal_cart_ttl_seconds: int = 7 * 24 * 60 * 60
    meal_order_cancellation_window_minutes: int = 20
    meal_default_currency: str = "GBP"
    meal_delivery_default_timezone: str = "Europe/London"
    meal_max_servings_per_line: int = 20
    meal_express_delivery_fee_minor: int = 300
    local_media_directory: str = "uploads"
    local_media_url_prefix: str = "/media"
    cloudinary_cloud_name: str | None = None
    cloudinary_api_key: str | None = None
    cloudinary_api_secret: SecretStr | None = None
    cloudinary_upload_preset: str | None = None
    cloudinary_api_base_url: str = "https://api.cloudinary.com/v1_1"
    cloudinary_upload_folder_root: str = "safedaet"
    cloudinary_timeout_seconds: float = 20.0
    aws_s3_bucket_name: str | None = None
    aws_s3_region: str | None = None
    aws_s3_access_key_id: str | None = None
    aws_s3_secret_access_key: SecretStr | None = None
    aws_s3_endpoint_url: str | None = None
    aws_s3_public_base_url: str | None = None
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator(
        "web_app_base_url",
        "api_public_base_url",
        "cloudinary_api_base_url",
        mode="before",
    )
    @classmethod
    def normalize_base_urls(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        return normalized or None

    @field_validator(
        "cloudinary_cloud_name",
        "cloudinary_api_key",
        "cloudinary_upload_preset",
        "cloudinary_upload_folder_root",
        mode="before",
    )
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
