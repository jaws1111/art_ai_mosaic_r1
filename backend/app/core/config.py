from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(project_root() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    xai_api_key: str = Field(default="", validation_alias="XAI_API_KEY")
    xai_base_url: str = "https://api.x.ai/v1"
    xai_model: str = "grok-imagine-image-quality"

    comfyui_host: str = Field(default="127.0.0.1", validation_alias="COMFYUI_HOST")
    comfyui_port: int = Field(default=8188, validation_alias="COMFYUI_PORT")
    comfyui_enabled: bool = Field(default=True, validation_alias="COMFYUI_ENABLED")
    comfyui_upscale_model: str = Field(
        default="RealESRGAN_x4plus.pth",
        validation_alias="COMFYUI_UPSCALE_MODEL",
    )

    data_dir: Path = Field(default_factory=lambda: project_root() / "data", validation_alias="DATA_DIR")

    base_tile_px: int = 2048
    local_upscale_factor: int = 2
    overlap_fraction: float = 0.25
    placeholder_size: int = 512
    # Threshold scales with upscale_factor² because MSE is pixel-space distance;
    # a 2× upscale raises raw MSE ~4×.  Default 3600 = 900 × 4 for 2× upscale.
    overlap_mse_threshold: float = Field(default=3600.0, validation_alias="OVERLAP_MSE_THRESHOLD")
    # How many blueprint crops to send to xAI per tile (1–3).
    # 1 = only this tile's crop; 2 = + left neighbour; 3 = + left + top neighbours.
    max_blueprint_crops: int = Field(default=3, ge=1, le=3, validation_alias="MAX_BLUEPRINT_CROPS")
    max_tile_retries: int = Field(default=1, ge=0, le=3, validation_alias="MAX_TILE_RETRIES")
    quality_review_max_px: int = Field(default=2048, validation_alias="QUALITY_REVIEW_MAX_PX")
    quality_ai_critique_enabled: bool = Field(default=True, validation_alias="QUALITY_AI_CRITIQUE_ENABLED")
    quality_ai_max_tokens: int = Field(default=400, validation_alias="QUALITY_AI_MAX_TOKENS")
    xai_critique_model: str = Field(default="grok-4-1-fast-non-reasoning", validation_alias="XAI_CRITIQUE_MODEL")

    @property
    def comfyui_url(self) -> str:
        return f"http://{self.comfyui_host}:{self.comfyui_port}"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def placeholder_path(self) -> Path:
        return self.cache_dir / "placeholders" / f"black_{self.placeholder_size}.png"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.runs_dir, self.cache_dir, self.cache_dir / "placeholders"):
            path.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()
