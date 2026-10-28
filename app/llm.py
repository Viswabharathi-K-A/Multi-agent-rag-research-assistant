
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import get_settings
from app.metrics import current_measurements


AgentRole = Literal[
    "supervisor",
    "research",
    "code",
    "summary",
]


def get_agent_provider_info(
    agent: AgentRole,
) -> tuple[str, str]:
    """Return the configured provider and model for an agent."""

    settings = get_settings()

    configurations = {
        "supervisor": (
            settings.supervisor_provider,
            settings.supervisor_model,
        ),
        "research": (
            settings.research_provider,
            settings.research_model,
        ),
        "code": (
            settings.code_provider,
            settings.code_model,
        ),
        "summary": (
            settings.summary_provider,
            settings.summary_model,
        ),
    }

    return configurations[agent]


def get_agent_llm(
    agent: AgentRole,
) -> BaseChatModel:
    """Create the LLM assigned to the requested agent."""

    settings = get_settings()
    provider, model = get_agent_provider_info(agent)

    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY is not configured"
            )

        model = ChatOpenAI(
            model=model,
            api_key=settings.openai_api_key,
            temperature=0,
            max_retries=2,
            timeout=30,
        )

    elif provider == "google":
        if not settings.google_api_key:
            raise ValueError(
                "GOOGLE_API_KEY is not configured"
            )

        model = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=settings.google_api_key,
            temperature=0,
            max_retries=2,
            timeout=30,
        )

    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")

    measurements = current_measurements.get()
    if measurements is not None:
        model.callbacks = [measurements]
        model.metadata = {"agent": agent, "provider": provider, "ls_model_name": getattr(settings, f"{agent}_model")}
    return model
