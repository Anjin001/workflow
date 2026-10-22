"""网页接口输入与模型连接检查；密钥使用 SecretStr，避免出现在对象打印中。"""

from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .config import Settings, normalize_base_url
from .errors import ModelError


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr = SecretStr("")
    base_url: str = Field(default="https://api.deepseek.com", max_length=2000)
    model: str = Field(default="deepseek-flash", min_length=1, max_length=200)
    timeout: int = Field(default=60, ge=5, le=300, strict=True)
    json_mode: bool = True

    def settings(self) -> Settings:
        base_url = normalize_base_url(self.base_url)
        key = self.api_key.get_secret_value().strip()
        local = urlsplit(base_url).hostname in {"localhost", "127.0.0.1", "::1"}
        if not key and not local:
            raise ValueError("请在模型设置中填写 API Key")
        if len(key) > 4096 or any(not 33 <= ord(character) <= 126 for character in key):
            raise ValueError("API Key 包含无效字符，请检查是否复制了空格或换行")
        model = self.model.strip()
        if not model or any(ord(character) < 32 for character in model):
            raise ValueError("请填写有效的模型名称")
        return Settings(
            api_key=key or "local",
            base_url=base_url,
            model=model,
            request_timeout=self.timeout,
            json_mode=self.json_mode,
        )


class PrepareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement: str = Field(min_length=1, max_length=10_000)
    connection: ConnectionInput


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: dict[str, Any]
    mode: Literal["real", "mock"] = "real"
    connection: ConnectionInput | None = None
    scenario: Literal["repair", "pass", "stuck"] = "repair"
    max_repairs: int = Field(default=2, ge=0, le=10, strict=True)


def check_connection(settings: Settings) -> dict:
    """读取模型列表，不发送聊天请求，不消耗聊天生成额度。"""
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.get(
                settings.base_url + "/models",
                headers={"Authorization": f"Bearer {settings.api_key}"},
            )
    except httpx.TransportError as exc:
        raise ModelError("无法连接模型服务，请检查网址、网络和本地服务是否已启动") from exc
    if response.status_code != 200:
        messages = {
            401: "API Key 无效，请检查密钥是否正确",
            403: "当前密钥没有访问权限",
            404: "服务没有提供模型列表，可手动填写模型名称后尝试运行",
            429: "服务暂时限流，请稍后重试",
        }
        raise ModelError(
            messages.get(
                response.status_code, f"服务返回 HTTP {response.status_code}，请检查接口地址"
            )
        )
    try:
        data = response.json()["data"]
        if not isinstance(data, list):
            raise ValueError("invalid model list")
        models = [
            item["id"]
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str) and len(item["id"]) <= 200
        ][:200]
    except (ValueError, TypeError, KeyError) as exc:
        raise ModelError("接口已响应，但没有返回兼容的模型列表；可以手动填写模型名称") from exc
    return {
        "models": models,
        "base_url": settings.base_url,
        "message": f"连接成功，读取到 {len(models)} 个模型。实际运行时仍会检查模型输出。",
    }
