from leornian.platform.model_contracts import (
    CHAT_ROLES,
    ModelPresetModel,
    ModelProfileInput,
    ModelProviderPreset,
)

# Official aliases and capacities checked on 2026-11-08; existing profiles stay versioned.
# https://api-docs.deepseek.com/quick_start/pricing
# https://help.aliyun.com/zh/model-studio/models
PRESETS = {
    "deepseek": {
        "label": "DeepSeek",
        "protocol": "chat_completions",
        "base_url": "https://api.deepseek.com",
        "region": "global",
        "api_key_url": "https://platform.deepseek.com/api_keys",
        "profiles": [
            {
                "label": "DeepSeek 教学",
                "model": "deepseek-flash",
                "operation": "chat",
                "roles": list(CHAT_ROLES),
                "context_tokens": 1_048_576,
                "max_output_tokens": 393_216,
                "thinking": "enabled",
                "timeout_seconds": 600,
            },
        ],
    },
    "qwen": {
        "label": "千问",
        "protocol": "dashscope",
        "base_url": "https://dashscope.aliyuncs.com",
        "region": "cn-beijing",
        "api_key_url": "https://bailian.console.aliyun.com/?tab=model#/api-key",
        "profiles": [
            {
                "label": "千问教学",
                "model": "qwen-plus",
                "operation": "chat",
                "roles": list(CHAT_ROLES),
                "context_tokens": 1_000_000,
                "max_output_tokens": 32_768,
                "thinking": "enabled",
                "timeout_seconds": 600,
            },
            {
                "label": "千问文字识别",
                "model": "qwen3.5-ocr",
                "operation": "ocr",
                "roles": ["ocr"],
            },
            {
                "label": "千问文本向量",
                "model": "text-embedding-v4",
                "operation": "embedding",
                "roles": ["embedding"],
                "embedding_dimensions": 1024,
            },
            {
                "label": "千问检索重排",
                "model": "qwen3-rerank",
                "operation": "rerank",
                "roles": ["rerank"],
            },
        ],
    },
}


def provider_presets():
    return [
        ModelProviderPreset(
            id=preset_id,
            label=value["label"],
            base_url=value["base_url"],
            region=value["region"],
            models=[profile["model"] for profile in value["profiles"]],
            api_key_url=value["api_key_url"],
            model_details=[
                ModelPresetModel(**{
                    field: profile[field]
                    for field in ModelPresetModel.model_fields
                    if field in profile
                })
                for profile in value["profiles"]
            ],
        )
        for preset_id, value in PRESETS.items()
    ]


def preset_profiles(preset_id, connection_id, models=None):
    return [
        ModelProfileInput(
            connection_id=connection_id,
            enabled=True,
            allow_private_material=True,
            **profile,
        )
        for profile in PRESETS[preset_id]["profiles"]
        if models is None or profile["model"] in models
    ]
