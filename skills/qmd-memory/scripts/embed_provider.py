"""Embedding provider abstraction — supports local GGUF, SentenceTransformer, and Azure OpenAI backends.

Usage:
    from embed_provider import get_provider
    provider = get_provider()             # reads agentconfig.json
    vectors = provider.embed(["text1", "text2"])
    provider.close()                      # free resources (local model)
"""

import json
import os
import sys
from pathlib import Path
from typing import Protocol

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
PROJECT_ROOT = SKILL_ROOT.parent.parent
AGENT_CONFIG = PROJECT_ROOT / "agentconfig.json"
ENV_FILE = PROJECT_ROOT / ".env"


class EmbeddingProvider(Protocol):
    """Minimal interface for embedding providers."""
    name: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
        ...

    def close(self) -> None:
        """Release resources."""
        ...


# ---------------------------------------------------------------------------
# Local GGUF provider (llama-cpp-python)
# ---------------------------------------------------------------------------

class LocalGGUFProvider:
    """Embed via a local GGUF model using llama-cpp-python."""

    def __init__(self, model_path: str, model_name: str = "", dimensions: int = 384):
        from llama_cpp import Llama

        resolved = Path(model_path)
        if not resolved.is_absolute():
            resolved = PROJECT_ROOT / model_path

        if not resolved.exists():
            raise FileNotFoundError(
                f"GGUF model not found at {resolved}.\n"
                f"Download from: https://huggingface.co/CompendiumLabs/bge-small-en-v1.5-gguf"
            )

        self._model = Llama(str(resolved), embedding=True, verbose=False)
        self.name = model_name or resolved.stem
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            vec = self._model.embed(text)
            # embed() may return list-of-lists for a single string
            if vec and isinstance(vec[0], list):
                vec = vec[0]
            results.append(vec)
        return results

    def close(self) -> None:
        del self._model
        self._model = None


# ---------------------------------------------------------------------------
# Local SentenceTransformer provider (pip-installable, no C++ compiler needed)
# ---------------------------------------------------------------------------

class SentenceTransformerProvider:
    """Embed via a HuggingFace SentenceTransformer model (runs locally on CPU)."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", dimensions: int = 384):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self.name = model_name.split("/")[-1] if "/" in model_name else model_name
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings = self._model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return [emb.tolist() for emb in embeddings]

    def close(self) -> None:
        del self._model
        self._model = None


# ---------------------------------------------------------------------------
# Azure OpenAI provider
# ---------------------------------------------------------------------------

class AzureOpenAIProvider:
    """Embed via Azure OpenAI API."""

    def __init__(self, config: dict, api_key: str):
        from openai import AzureOpenAI

        self._client = AzureOpenAI(
            azure_endpoint=config["endpoint"],
            api_key=api_key,
            api_version=config["api_version"],
        )
        self._model = config.get("model", config["deployment"])
        self.name = self._model
        self.dimensions = 3072  # text-embedding-3-large

    def embed(self, texts: list[str], batch_size: int = 16) -> list[list[float]]:
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = self._client.embeddings.create(input=batch, model=self._model)
            for item in response.data:
                all_embeddings.append(item.embedding)
        return all_embeddings

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def _load_env() -> None:
    """Load .env into os.environ."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_FILE)
    except ImportError:
        if ENV_FILE.exists():
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())


def get_provider(force_provider: str | None = None) -> EmbeddingProvider:
    """Instantiate the embedding provider from agentconfig.json.

    Args:
        force_provider: Override the config — ``"local"`` or ``"azure_openai"``.
    """
    if not AGENT_CONFIG.exists():
        raise FileNotFoundError(f"{AGENT_CONFIG} not found.")

    with open(AGENT_CONFIG, "r", encoding="utf-8") as f:
        config = json.load(f)

    mem_cfg = config.get("memory", {}).get("embedding", {})
    provider = force_provider or mem_cfg.get("provider", "local")

    if provider == "local":
        local_cfg = mem_cfg.get("local", {})
        model_path = local_cfg.get("model_path", "skills/qmd-memory/models/bge-small-en-v1.5-f16.gguf")
        return LocalGGUFProvider(
            model_path=model_path,
            model_name=local_cfg.get("model_name", ""),
            dimensions=local_cfg.get("dimensions", 384),
        )

    if provider == "sentence_transformer":
        st_cfg = mem_cfg.get("sentence_transformer", {})
        return SentenceTransformerProvider(
            model_name=st_cfg.get("model_name", "BAAI/bge-small-en-v1.5"),
            dimensions=st_cfg.get("dimensions", 384),
        )

    if provider == "azure_openai":
        _load_env()
        azure_cfg = mem_cfg.get("azure_openai", {})
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
        if not api_key or api_key == "your-api-key-here":
            raise ValueError("AZURE_OPENAI_API_KEY not set in .env or environment.")
        return AzureOpenAIProvider(azure_cfg, api_key)

    raise ValueError(f"Unknown embedding provider: {provider}")
