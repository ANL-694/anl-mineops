import os
from datetime import UTC, datetime
from typing import Any

import httpx

from .schemas import ProviderProbeResult, ProviderProfile


class ProviderError(RuntimeError):
    pass


def build_model(profile: ProviderProfile) -> Any:
    """Build a PydanticAI OpenAI-compatible model without persisting secrets."""
    try:
        from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
        from pydantic_ai.providers.openai import OpenAIProvider
    except ImportError as exc:
        raise ProviderError("pydantic_ai_not_installed") from exc

    api_key = os.getenv(profile.api_key_env)
    if not api_key:
        raise ProviderError(f"missing_api_key_env:{profile.api_key_env}")
    model_class = (
        OpenAIResponsesModel
        if profile.protocol.value == "openai-compatible-responses"
        else OpenAIChatModel
    )
    return model_class(
        profile.model,
        provider=OpenAIProvider(base_url=str(profile.base_url), api_key=api_key),
    )


def probe_environment(profile: ProviderProfile) -> ProviderProbeResult:
    return ProviderProbeResult(
        provider_id=profile.id,
        base_url=str(profile.base_url),
        model=profile.model,
        api_key_configured=bool(os.getenv(profile.api_key_env)),
        protocol=profile.protocol,
        checked_at=datetime.now(UTC),
        capabilities={"tool_calling": "not_probed", "streaming": "not_probed"},
    )


async def probe_provider(profile: ProviderProfile, *, live: bool = False) -> ProviderProbeResult:
    result = probe_environment(profile)
    if not live:
        return result
    if not result.api_key_configured:
        return result.model_copy(update={"live": True, "error": f"missing_api_key_env:{profile.api_key_env}"})

    headers = {"Authorization": f"Bearer {os.environ[profile.api_key_env]}"}
    models_url = f"{str(profile.base_url).rstrip('/')}/models"
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            response = await client.get(models_url, headers=headers)
    except httpx.RequestError:
        return result.model_copy(
            update={"live": True, "reachable": False, "error": "provider_unreachable"}
        )

    model_available: bool | None = None
    capabilities = dict(result.capabilities)
    if response.is_success:
        try:
            payload = response.json()
            models = payload.get("data", []) if isinstance(payload, dict) else []
            model_items = [item for item in models if isinstance(item, dict)]
            model_available = any(item.get("id") == profile.model for item in model_items)
            model_record = next((item for item in model_items if item.get("id") == profile.model), None)
            if model_record:
                metadata = model_record.get("capabilities")
                if isinstance(metadata, dict):
                    for key in ("tool_calling", "streaming"):
                        value = metadata.get(key)
                        if isinstance(value, bool):
                            capabilities[key] = "supported" if value else "unsupported"
                        elif isinstance(value, str) and value:
                            capabilities[key] = value
        except ValueError:
            model_available = None
    return result.model_copy(
        update={
            "live": True,
            "reachable": True,
            "http_status": response.status_code,
            "model_available": model_available,
            "capabilities": capabilities,
            "error": None if response.is_success else "provider_models_request_failed",
        }
    )
