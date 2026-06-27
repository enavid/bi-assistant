from __future__ import annotations

_active_dsn: str | None = None
_active_ollama_base_url: str | None = None
_active_model: str | None = None
_model_configs: dict[str, dict] = {}


def get_active_dsn() -> str | None:
    return _active_dsn


def set_active_dsn(dsn: str | None) -> None:
    global _active_dsn
    _active_dsn = dsn


def get_active_ollama_base_url() -> str | None:
    return _active_ollama_base_url


def set_active_ollama_base_url(url: str | None) -> None:
    global _active_ollama_base_url
    _active_ollama_base_url = url


def get_active_model() -> str | None:
    return _active_model


def get_model_config(model_name: str) -> dict:
    return _model_configs.get(model_name, {})


def set_model_config(model_name: str, config: dict) -> None:
    global _active_model
    _model_configs[model_name] = config
    if _active_model is None:
        _active_model = model_name


def remove_model_config(model_name: str) -> None:
    global _active_model
    _model_configs.pop(model_name, None)
    if _active_model == model_name:
        _active_model = next(iter(_model_configs), None)


def get_all_model_configs() -> dict[str, dict]:
    return dict(_model_configs)
