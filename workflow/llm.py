"""兼容 Chat Completions 的模型客户端，负责请求、重试和用量统计。"""

import logging
import time
from collections.abc import Callable
from typing import Protocol

import httpx

from .config import Settings
from .errors import ModelError
from .state import ModelUsage

logger = logging.getLogger(__name__)


class Model(Protocol):
    name: str
    usage: ModelUsage

    def complete(self, role: str, messages: list[dict[str, str]]) -> str: ...

    def close(self) -> None: ...


class ChatModel:
    """API 密钥只用于请求头，不进入提示词、报告和日志。"""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not settings.api_key:
            raise ModelError("未配置 LLM_API_KEY；请填写 .env，或使用 --mock 运行离线示例")
        self.name = settings.model
        self.usage = ModelUsage()
        self.settings = settings
        self._sleep = sleeper
        self._http = httpx.Client(
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=settings.request_timeout,
            transport=transport,
            follow_redirects=False,
        )

    def complete(self, role: str, messages: list[dict[str, str]]) -> str:
        body = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": self.settings.max_tokens,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        for attempt in range(self.settings.request_retries + 1):
            self.usage.requests += 1
            try:
                response = self._http.post(self.settings.base_url + "/chat/completions", json=body)
            except httpx.TransportError:
                # 不输出原始异常，避免代理地址或服务信息意外进入日志。
                reason = "模型请求超时或网络连接失败"
            else:
                if response.status_code == 200:
                    return self._read_response(response)
                status = response.status_code
                notes = {
                    400: "请求参数不被服务支持，请检查模型名称和 JSON 模式",
                    401: "API 密钥无效或已失效",
                    402: "模型账户余额不足",
                    403: "当前密钥无访问权限",
                    404: "模型接口地址或模型名称不存在",
                    422: "模型请求参数不合法",
                    429: "模型服务限流",
                }
                reason = f"HTTP {status}：{notes.get(status, '模型服务请求失败')}"
                if status not in {408, 429} and status < 500:
                    raise ModelError(reason)
            if attempt == self.settings.request_retries:
                raise ModelError(f"{reason}；已用完 {attempt} 次重试")
            self.usage.retries += 1
            logger.warning("%s 请求未完成，%s 秒后重试（%s）", role, 2**attempt, reason)
            self._sleep(2**attempt)
        raise ModelError("模型请求未完成")

    def _read_response(self, response: httpx.Response) -> str:
        try:
            data = response.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
            finish_reason = choice["finish_reason"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelError("模型服务返回了无法识别的响应结构") from exc
        usage = data.get("usage")
        if isinstance(usage, dict):
            for key in ("prompt_tokens", "completion_tokens"):
                value = usage.get(key)
                if type(value) is int and value >= 0:
                    setattr(self.usage, key, getattr(self.usage, key) + value)
        if finish_reason == "length":
            raise ModelError("模型输出被截断，请增大 LLM_MAX_TOKENS 或缩小任务")
        if finish_reason != "stop" or not isinstance(content, str):
            raise ModelError("模型未正常完成文本输出，请检查模型能力和服务配置")
        return content

    def close(self) -> None:
        self._http.close()
