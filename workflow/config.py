"""从 .env 与环境变量加载配置，不向日志或报告写入密钥。"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} 必须在 {minimum} 至 {maximum} 之间")
    return value


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    request_timeout: int = 60
    request_retries: int = 2
    output_retries: int = 1
    test_timeout: int = 5
    max_tokens: int = 4096

    @classmethod
    def load(cls, root: Path) -> "Settings":
        load_dotenv(root / ".env", override=False)
        base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").strip().rstrip("/")
        url = urlsplit(base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("LLM_BASE_URL 必须是无凭据、查询参数或片段的 HTTP(S) 地址")
        if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("远程模型地址必须使用 HTTPS；HTTP 仅用于本地模型服务")
        model = os.getenv("LLM_MODEL", "deepseek-flash").strip()
        if not model:
            raise ValueError("LLM_MODEL 不能为空")
        return cls(
            api_key=(os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")).strip(),
            base_url=base_url,
            model=model,
            request_timeout=env_int("LLM_TIMEOUT", 60, 1, 300),
            request_retries=env_int("LLM_RETRIES", 2, 0, 5),
            output_retries=env_int("OUTPUT_RETRIES", 1, 0, 3),
            test_timeout=env_int("TEST_TIMEOUT", 5, 1, 60),
            max_tokens=env_int("LLM_MAX_TOKENS", 4096, 256, 32_768),
        )
