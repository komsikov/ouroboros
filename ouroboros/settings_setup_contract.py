"""Shared Settings/Onboarding setup contract and payload validation."""

from __future__ import annotations

import math
from typing import Any, Dict, Tuple

from ouroboros.config import SETTINGS_DEFAULTS, VALID_RUNTIME_MODES
from ouroboros.provider_models import (
    ANTHROPIC_DIRECT_DEFAULTS,
    CLOUDRU_DIRECT_DEFAULTS,
    OPENAI_DIRECT_DEFAULTS,
)


def _rows(keys: tuple[str, ...], specs: tuple[tuple[Any, ...], ...]) -> list[dict]:
    rows = []
    for spec in specs:
        if len(spec) != len(keys):
            raise ValueError(f"setup contract row has {len(spec)} fields, expected {len(keys)}")
        rows.append(dict(zip(keys, spec)))
    return rows


_MODEL_DEFAULTS = {
    "openrouter": {
        "main": str(SETTINGS_DEFAULTS["OUROBOROS_MODEL"]),
        "heavy": str(SETTINGS_DEFAULTS["OUROBOROS_MODEL_HEAVY"]),
        "light": str(SETTINGS_DEFAULTS["OUROBOROS_MODEL_LIGHT"]),
        "consciousness": str(SETTINGS_DEFAULTS["OUROBOROS_MODEL_CONSCIOUSNESS"]),
        "fallback": str(SETTINGS_DEFAULTS["OUROBOROS_MODEL_FALLBACKS"]),
    },
    "openai": dict(OPENAI_DIRECT_DEFAULTS),
    "cloudru": dict(CLOUDRU_DIRECT_DEFAULTS),
    "anthropic": dict(ANTHROPIC_DIRECT_DEFAULTS),
    # No defaults: model names are server-specific; user must fill all slots.
    "openai-compatible": {"main": "", "heavy": "", "light": "", "fallback": ""},
}
_MODEL_DEFAULTS["local"] = dict(_MODEL_DEFAULTS["openrouter"])
for _profile_defaults in _MODEL_DEFAULTS.values():
    _profile_defaults.setdefault("consciousness", "")

_STEPS = _rows(("id", "title", "railCopy", "copy", "footer"), (
    ("providers", "Добавьте доступ", "Ключи + локальная", "Заполните хотя бы один удалённый ключ или источник локальной модели. Следующий шаг адаптируется к тому, что вы настроили здесь.", "Вставляйте только то, что у вас уже есть. OpenRouter, прямые ключи провайдеров и необязательная локальная модель могут сосуществовать."),
    ("models", "Выберите модели", "5 слотов моделей", "Просмотрите видимые настройки моделей по умолчанию, полученные из вашей текущей конфигурации, затем измените всё, что нужно, перед запуском.", "Значения вида openai/... или anthropic/... остаются в стиле роутера. Прямые значения используют openai::... и anthropic::...."),
    ("review_mode", "Выберите режим проверки", "Рекомендательный / Блокирующий", "Определите строгость проверки перед коммитом до того, как Ouroboros начнёт самомодификацию.", "Выберите режим проверки и начальный режим среды выполнения до запуска Ouroboros."),
    ("budget", "Установите бюджет", "Ограничения сессии", "Бюджет — отдельный шаг, потому что он напрямую определяет, насколько далеко Ouroboros может зайти за одну сессию и в одной задаче.", "Общий бюджет — глобальный. Лимит затрат на задачу — мягкое напоминание, а не жёсткий выключатель."),
    ("summary", "Проверьте перед запуском", "Финальная проверка", "Проверьте итоговую картину по провайдерам, моделям, проверке и бюджету. Ouroboros сохранит эти значения перед запуском.", "Те же параметры останутся доступными для редактирования в Настройках."),
))
_STEP_ORDER = [step["id"] for step in _STEPS]

_PROVIDER_FIELDS = _rows(("id", "stateKey", "settingKey", "settingsInputId", "label", "placeholder", "note", "inputType"), (
    ("openrouter-key", "openrouterKey", "OPENROUTER_API_KEY", "s-openrouter", "OpenRouter API Key", "sk-or-v1-...", "Необязательно. Лучший вариант, если нужен один роутер для OpenAI, Anthropic, Google и других.", "password"),
    ("openai-key", "openaiKey", "OPENAI_API_KEY", "s-openai", "OpenAI API Key", "sk-...", "Необязательно. Если это единственный удалённый ключ, на следующем шаге будут предзаполнены прямые модели openai::...", "password"),
    ("cloudru-key", "cloudruKey", "CLOUDRU_FOUNDATION_MODELS_API_KEY", "s-cloudru-key", "Cloud.ru Foundation Models API Key", "Ключ Cloud.ru API", "Необязательно. Если это единственный удалённый ключ, на следующем шаге будут предзаполнены прямые модели cloudru::...", "password"),
    ("anthropic-key", "anthropicKey", "ANTHROPIC_API_KEY", "s-anthropic", "Anthropic API Key", "sk-ant-...", "Необязательно. Сохраняется для прямых моделей anthropic::... и инструментов Claude.", "password"),
    ("openai-compatible-url", "compatibleBaseUrl", "OPENAI_COMPATIBLE_BASE_URL", "s-compatible-url", "OpenAI-compatible Base URL", "http://localhost:11434/v1", "Базовый URL вашего OpenAI-совместимого эндпоинта (например, Ollama, LM Studio, vLLM). Требуется для моделей openai-compatible::.", "url"),
    ("openai-compatible-key", "compatibleApiKey", "OPENAI_COMPATIBLE_API_KEY", "s-compatible-key", "OpenAI-compatible API Key", "Оставьте пустым, если авторизация не нужна", "Ключ API для эндпоинта. Оставьте пустым, если ваш сервер не требует авторизации.", "password"),
))

_PROFILE_SPECS = {
    "openrouter": ("OpenRouter", "OpenRouter настроен, поэтому на следующем шаге сохранятся настройки по умолчанию в стиле роутера, а дополнительные прямые ключи также будут сохранены.", "Маршрутизация в стиле OpenRouter остаётся активной. ID провайдеров без префикса, такие как openai/gpt-5.5 или anthropic/claude-sonnet-4.6, продолжают маршрутизироваться через OpenRouter."),
    "openai": ("OpenAI", "Настроен OpenAI, поэтому на следующем шаге будут предзаполнены прямые значения openai:: моделей.", "Обнаружена конфигурация только OpenAI. Значения по умолчанию явные и официальные."),
    "cloudru": ("Cloud.ru Foundation Models", "Настроен Cloud.ru, поэтому на следующем шаге будут предзаполнены прямые значения cloudru:: моделей.", "Обнаружена конфигурация только Cloud.ru. Значения по умолчанию используют явные ID моделей cloudru::."),
    "anthropic": ("Anthropic", "Настроен Anthropic, поэтому на следующем шаге будут предзаполнены прямые значения anthropic:: моделей.", "Обнаружена конфигурация только Anthropic. Значения по умолчанию явные и официальные."),
    "openai-compatible": ("OpenAI-совместимый эндпоинт", "Настроен OpenAI-совместимый базовый URL. Укажите имена моделей, которые предоставляет ваш сервер, на следующем шаге.", "Обнаружен OpenAI-совместимый эндпоинт. Используйте openai-compatible::имя-вашей-модели для каждого слота. Список моделей — это всё, что поддерживает ваш сервер."),
    "direct-multi": ("Несколько прямых провайдеров", "Настроено несколько прямых провайдеров, поэтому на следующем шаге значения моделей остаются редактируемыми без привязки к одному семейству провайдеров.", "Настроено несколько прямых провайдеров. Начните здесь, затем при необходимости распределите слоты моделей между ними."),
    "local": ("Локальный-первый", "Удалённый ключ ещё не добавлен, поэтому ниже доступна только-локальная конфигурация.", "Обнаружена только-локальная конфигурация. Проверьте значения моделей и локальную маршрутизацию перед запуском."),
}

_MODEL_SLOTS = _rows(("slot", "stateKey", "settingKey", "inputId", "label", "note", "settingsInputId", "settingsToggleId"), (
    ("main", "mainModel", "OUROBOROS_MODEL", "main-model", "Основная модель", "Основная модель для рассуждений и длинных задач.", "s-model", "s-local-main"),
    ("heavy", "heavyModel", "OUROBOROS_MODEL_HEAVY", "heavy-model", "Тяжёлая модель", "Сильная модель для first-level субагентов с активными правками кода. Пусто — используется Основная.", "s-model-heavy", "s-local-heavy"),
    ("light", "lightModel", "OUROBOROS_MODEL_LIGHT", "light-model", "Лёгкая модель", "Быстрые резюме, лёгкие задачи и все глубокие субагенты. Пусто — используется Основная.", "s-model-light", "s-local-light"),
    ("consciousness", "consciousnessModel", "OUROBOROS_MODEL_CONSCIOUSNESS", "consciousness-model", "Модель сознания", "Высокоуровневое фоновое сознание. Пусто — используется Основная.", "s-model-consciousness", "s-local-consciousness"),
    ("fallback", "fallbackModel", "OUROBOROS_MODEL_FALLBACKS", "fallback-model", "Запасная модель", "Путь устойчивости и переключения при проблемах с основной.", "s-model-fallback", "s-local-fallback"),
))

_REVIEW_MODES = _rows(("value", "label", "tone", "className", "copy"), (
    ("advisory", "Рекомендательный", "Гибкий", "advisory", "Быстрее и дешевле. Проверка всё равно выполняется, но вы сами решаете, что делать с замечаниями. Лучший выбор, когда важна скорость итераций."),
    ("blocking", "Блокирующий", "Строгий", "blocking", "Медленнее и дороже, но намного безопаснее. Критические замечания останавливают коммиты, что значительно снижает риск постепенной деградации кода."),
))

_RUNTIME_MODES = _rows(("value", "label", "tone", "className", "copy"), (
    ("light", "Light", "Безопаснее", "light", "Самомодификация основного репозитория отключена. Лучший вариант для знакомства с Ouroboros без самомодификации."),
    ("advanced", "Advanced", "По умолчанию", "advanced", "Самомодификация эволюционного слоя разрешена (текущее поведение). Защищённые файлы ядра/контрактов/релизов охраняются в режиме Advanced."),
    ("pro", "Pro", "Расширенный", "pro", "Прямой режим защищённых поверхностей. Редактирование защищённых файлов ядра/контрактов/релизов разрешено, но коммиты по-прежнему проходят через триаду и проверку области."),
))

_LOCAL_ROUTING_MODES = _rows(("value", "buttonLabel", "label", "flags"), (
    ("cloud", "Только облако", "Только облачные модели", (False, False, False, False, False)),
    ("fallback", "Запасная локальная", "Запасная модель локальная", (False, False, False, False, True)),
    ("all", "Все локальные", "Все модели локальные", (True, True, True, True, True)),
))

_BUDGET_FIELDS = [
    {
        "stateKey": "totalBudget",
        "settingKey": "TOTAL_BUDGET",
        "inputId": "total-budget",
        "settingsInputId": "s-total-budget",
        "title": "Общий бюджет",
        "label": "Общий бюджет (USD)",
        "note": "Глобальный бюджет расходов для всей среды. Оставляйте редактируемым даже после настройки.",
        "default": float(SETTINGS_DEFAULTS["TOTAL_BUDGET"]),
        "min": "0.01",
        "step": "any",
    },
    {
        "stateKey": "perTaskCostUsd",
        "settingKey": "OUROBOROS_PER_TASK_COST_USD",
        "inputId": "per-task-budget",
        "settingsInputId": "s-settings-per-task-cost",
        "title": "Мягкий порог на задачу",
        "label": "Лимит затрат на задачу (USD)",
        "note": "Это не останавливает задачу жёстко. Вставляется напоминание о бюджете, когда задача становится дорогой.",
        "default": float(SETTINGS_DEFAULTS.get("OUROBOROS_PER_TASK_COST_USD", 20.0)),
        "min": "0.01",
        "step": "any",
    },
]
_BUDGET_FIELDS_BY_KEY = {field["settingKey"]: field for field in _BUDGET_FIELDS}
BUDGET_SETTING_KEYS = tuple(_BUDGET_FIELDS_BY_KEY)

_LOCAL_PRESETS: Dict[str, Dict[str, Any]] = {
    "qwen25-7b": {"label": "Qwen2.5-7B Instruct Q3_K_M", "source": "Qwen/Qwen2.5-7B-Instruct-GGUF", "filename": "qwen2.5-7b-instruct-q3_k_m.gguf", "contextLength": 16384, "chatFormat": ""},
    "qwen3-14b": {"label": "Qwen3-14B Instruct Q4_K_M", "source": "Qwen/Qwen3-14B-GGUF", "filename": "Qwen3-14B-Q4_K_M.gguf", "contextLength": 16384, "chatFormat": ""},
    "qwen3-32b": {"label": "Qwen3-32B Instruct Q4_K_M", "source": "Qwen/Qwen3-32B-GGUF", "filename": "Qwen3-32B-Q4_K_M.gguf", "contextLength": 32768, "chatFormat": ""},
}

_MODEL_SUGGESTIONS = list(dict.fromkeys(("google/gemini-3.5-flash", "anthropic/claude-sonnet-4.6", "anthropic/claude-opus-4.8", "anthropic/claude-opus-4.7", "anthropic/claude-opus-4.6", "anthropic::claude-opus-4-8", "anthropic::claude-opus-4-7", "anthropic::claude-opus-4-6", "anthropic::claude-sonnet-4-6", "openai/gpt-5.5", "openai::gpt-5.5", "openai::gpt-5.5-mini", "openai-compatible::meta-llama/compatible", "cloudru::zai-org/GLM-4.7")))


def _string(value: Any) -> str:
    return str(value or "").strip()


_truthy = lambda value: value is True or _string(value).lower() in {"1", "true", "yes", "on"}


def parse_budget_setting(
    key: str,
    raw_value: Any,
    *,
    use_default_for_blank: bool = False,
) -> Tuple[float | None, str | None]:
    """Разбор бюджетного параметра для онбординга и сохранения в Настройках."""
    field = _BUDGET_FIELDS_BY_KEY[key]
    name = "Бюджет" if key == "TOTAL_BUDGET" else "Мягкий порог на задачу"
    if raw_value is None or raw_value == "":
        if use_default_for_blank:
            raw_value = field["default"]
        else:
            return None, f"{name}: укажите число."
    if isinstance(raw_value, bool):
        return None, f"{name}: укажите число."
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None, f"{name}: укажите число."
    if not math.isfinite(value):
        return None, f"{name}: укажите число."
    if value <= 0:
        return None, f"{name}: значение должно быть больше нуля."
    min_value = float(field.get("min") or 0)
    if min_value > 0 and value < min_value:
        return None, f"{name}: минимум {field['min']}."
    return value, None


def derive_provider_profile(settings: dict) -> str:
    flags = {field["settingKey"]: bool(_string(settings.get(field["settingKey"]))) for field in _PROVIDER_FIELDS}
    if flags["OPENROUTER_API_KEY"]:
        return "openrouter"
    if flags["OPENAI_COMPATIBLE_BASE_URL"]:
        return "openai-compatible"
    direct = [
        ("OPENAI_API_KEY", "openai"),
        ("CLOUDRU_FOUNDATION_MODELS_API_KEY", "cloudru"),
        ("ANTHROPIC_API_KEY", "anthropic"),
    ]
    configured = [name for key, name in direct if flags[key]]
    if len(configured) > 1:
        return "direct-multi"
    return configured[0] if configured else ("local" if _string(settings.get("LOCAL_MODEL_SOURCE")) else "openrouter")


def derive_local_routing_mode(settings: dict) -> str:
    flags = tuple(_truthy(settings.get(key)) for key in ("USE_LOCAL_MAIN", "USE_LOCAL_HEAVY", "USE_LOCAL_LIGHT", "USE_LOCAL_CONSCIOUSNESS", "USE_LOCAL_FALLBACK"))
    if flags == (True, True, True, True, True):
        return "all"
    return "fallback" if flags == (False, False, False, False, True) else "cloud"


def local_routing_flags(mode: str, has_local: bool = True) -> tuple[bool, bool, bool, bool, bool]:
    if not has_local:
        return (False, False, False, False, False)
    for item in _LOCAL_ROUTING_MODES:
        if item["value"] == mode:
            return tuple(bool(flag) for flag in item["flags"])  # type: ignore[return-value]
    return (False, False, False, False, False)


def model_defaults_for_profile(profile: str) -> dict:
    return dict(_MODEL_DEFAULTS.get(profile) or _MODEL_DEFAULTS["openrouter"])


def build_setup_contract(host_mode: str = "desktop") -> dict:
    return {
        "version": 1,
        "hostMode": "web" if host_mode == "web" else "desktop",
        "steps": [dict(item) for item in _STEPS],
        "providerFields": [dict(item) for item in _PROVIDER_FIELDS],
        "providerProfiles": {key: {"label": spec[0], "providerCopy": spec[1], "modelCopy": spec[2]} for key, spec in _PROFILE_SPECS.items()},
        "modelSlots": [dict(item) for item in _MODEL_SLOTS],
        "reviewModes": [dict(item) for item in _REVIEW_MODES],
        "runtimeModes": [dict(item) for item in _RUNTIME_MODES],
        "localRoutingModes": [dict(item) for item in _LOCAL_ROUTING_MODES],
        "budgetFields": [dict(item) for item in _BUDGET_FIELDS],
    }


def build_initial_setup_state(settings: dict, host_mode: str = "desktop") -> dict:
    profile = derive_provider_profile(settings)
    defaults = model_defaults_for_profile(profile)
    local_source = _string(settings.get("LOCAL_MODEL_SOURCE"))
    local_filename = _string(settings.get("LOCAL_MODEL_FILENAME"))
    local_preset = next(
        (preset_id for preset_id, preset in _LOCAL_PRESETS.items() if local_source == preset["source"] and local_filename == preset["filename"]),
        "custom" if local_source else "",
    )
    try:
        raw_context_length = settings.get("LOCAL_MODEL_CONTEXT_LENGTH", SETTINGS_DEFAULTS["LOCAL_MODEL_CONTEXT_LENGTH"])
        local_context_length = int(raw_context_length if raw_context_length not in (None, "") else SETTINGS_DEFAULTS["LOCAL_MODEL_CONTEXT_LENGTH"])
    except (TypeError, ValueError):
        local_context_length = int(SETTINGS_DEFAULTS["LOCAL_MODEL_CONTEXT_LENGTH"])
    try:
        raw_gpu_layers = settings.get("LOCAL_MODEL_N_GPU_LAYERS", -1)
        local_gpu_layers = int(raw_gpu_layers if raw_gpu_layers not in (None, "") else -1)
    except (TypeError, ValueError):
        local_gpu_layers = -1
    budget_state: dict[str, float] = {}
    for field in _BUDGET_FIELDS:
        value, error = parse_budget_setting(field["settingKey"], settings.get(field["settingKey"]), use_default_for_blank=True)
        budget_state[field["stateKey"]] = float(field["default"] if error or value is None else value)
    state = {
        "providerProfile": profile,
        "reviewEnforcement": _string(settings.get("OUROBOROS_REVIEW_ENFORCEMENT")) or str(SETTINGS_DEFAULTS["OUROBOROS_REVIEW_ENFORCEMENT"]),
        "runtimeMode": _string(settings.get("OUROBOROS_RUNTIME_MODE")) or str(SETTINGS_DEFAULTS["OUROBOROS_RUNTIME_MODE"]),
        "skillsRepoPath": _string(settings.get("OUROBOROS_SKILLS_REPO_PATH")),
        "localPreset": local_preset,
        "localSource": local_source,
        "localFilename": local_filename,
        "localContextLength": local_context_length,
        "localGpuLayers": local_gpu_layers,
        "localChatFormat": _string(settings.get("LOCAL_MODEL_CHAT_FORMAT")),
        "localRoutingMode": derive_local_routing_mode(settings),
    }
    state.update({field["stateKey"]: _string(settings.get(field["settingKey"])) for field in _PROVIDER_FIELDS})
    state.update(budget_state)
    state.update({slot["stateKey"]: _string(settings.get(slot["settingKey"])) or defaults[slot["slot"]] for slot in _MODEL_SLOTS})
    return state


def build_setup_bootstrap(settings: dict, host_mode: str = "desktop") -> dict:
    normalized_host = "web" if host_mode == "web" else "desktop"
    return {
        "hostMode": normalized_host,
        "supportsLocalRuntimeControls": normalized_host == "web",
        "stepOrder": list(_STEP_ORDER),
        "modelDefaults": {key: dict(value) for key, value in _MODEL_DEFAULTS.items()},
        "localPresets": {key: dict(value) for key, value in _LOCAL_PRESETS.items()},
        "modelSuggestions": list(_MODEL_SUGGESTIONS),
        "contract": build_setup_contract(normalized_host),
        "initialState": build_initial_setup_state(settings, normalized_host),
    }


def validate_setup_payload(data: dict, current_settings: dict) -> Tuple[dict, str | None]:
    keys = {field["settingKey"]: _string(data.get(field["settingKey"])) for field in _PROVIDER_FIELDS}
    local_source = _string(data.get("LOCAL_MODEL_SOURCE"))
    local_filename = _string(data.get("LOCAL_MODEL_FILENAME"))
    local_chat_format = _string(data.get("LOCAL_MODEL_CHAT_FORMAT"))
    local_routing_mode = _string(data.get("LOCAL_ROUTING_MODE")) or "cloud"
    review_enforcement = _string(data.get("OUROBOROS_REVIEW_ENFORCEMENT")) or "advisory"
    raw_runtime_mode = _string(data.get("OUROBOROS_RUNTIME_MODE"))
    runtime_mode = raw_runtime_mode.lower() if raw_runtime_mode else _string(current_settings.get("OUROBOROS_RUNTIME_MODE")) or str(SETTINGS_DEFAULTS["OUROBOROS_RUNTIME_MODE"])

    for field in _PROVIDER_FIELDS:
        value = keys[field["settingKey"]]
        if value and field.get("inputType") != "url" and len(value) < 10:
            return {}, f"{field['label'].replace(' API Key', '')} API key looks too short."

    has_remote = any(
        value
        for setting_key, value in keys.items()
        if setting_key != "OPENAI_COMPATIBLE_API_KEY"
    )
    has_local = bool(local_source)
    if not has_remote and not has_local:
        return {}, "Перед продолжением настройте OpenRouter, OpenAI, OpenAI-compatible, Cloud.ru, Anthropic или локальную модель."
    if has_local and "/" in local_source and not local_source.startswith(("/", "~")) and not local_filename:
        return {}, "Local HuggingFace sources need a GGUF filename."
    if review_enforcement not in {"advisory", "blocking"}:
        return {}, "Выберите рекомендательный или блокирующий режим проверки."
    if runtime_mode not in VALID_RUNTIME_MODES:
        return {}, f"Выберите режим среды из {sorted(VALID_RUNTIME_MODES)}."

    models = {slot["settingKey"]: _string(data.get(slot["settingKey"])) for slot in _MODEL_SLOTS}
    # Role-model (v6.39): only Main is required. Heavy/Light/Consciousness fall back to
    # Main when empty, and Fallbacks carries a resilience default (empty = no cross-model
    # fallback) — so the owner is not forced to fill every slot. Mirrors the relaxed
    # onboarding-wizard validateModelsStep.
    if not models.get("OUROBOROS_MODEL"):
        return {}, "Подтвердите Основную модель перед запуском Ouroboros."

    parsed_budget: dict[str, float] = {}
    for field in _BUDGET_FIELDS:
        key = field["settingKey"]
        value, error = parse_budget_setting(key, data.get(key), use_default_for_blank=True)
        if error:
            return {}, error
        parsed_budget[key] = float(value)

    try:
        local_context_length = int(data.get("LOCAL_MODEL_CONTEXT_LENGTH") or SETTINGS_DEFAULTS["LOCAL_MODEL_CONTEXT_LENGTH"])
        local_gpu_layers = int(data.get("LOCAL_MODEL_N_GPU_LAYERS") if data.get("LOCAL_MODEL_N_GPU_LAYERS") is not None else -1)
    except (TypeError, ValueError):
        return {}, "Длина контекста локальной модели и GPU-слои должны быть целыми числами."

    use_local = local_routing_flags(local_routing_mode, has_local)
    if has_local and not has_remote and not any(use_local):
        return {}, "Для только-локальных конфигураций хотя бы одна модель должна маршрутизироваться в локальную среду."

    prepared = dict(current_settings)
    prepared.update(models)
    prepared.update(keys)
    prepared.update(parsed_budget)
    prepared.update({
        "OUROBOROS_REVIEW_ENFORCEMENT": review_enforcement,
        "OUROBOROS_RUNTIME_MODE": runtime_mode,
        "OUROBOROS_SKILLS_REPO_PATH": _string(data.get("OUROBOROS_SKILLS_REPO_PATH")),
        "LOCAL_MODEL_SOURCE": local_source if has_local else "",
        "LOCAL_MODEL_FILENAME": local_filename if has_local else "",
        "LOCAL_MODEL_CONTEXT_LENGTH": local_context_length,
        "LOCAL_MODEL_N_GPU_LAYERS": local_gpu_layers,
        "LOCAL_MODEL_CHAT_FORMAT": local_chat_format if has_local else "",
        "USE_LOCAL_MAIN": use_local[0],
        "USE_LOCAL_HEAVY": use_local[1],
        "USE_LOCAL_LIGHT": use_local[2],
        "USE_LOCAL_CONSCIOUSNESS": use_local[3],
        "USE_LOCAL_FALLBACK": use_local[4],
    })
    return prepared, None
