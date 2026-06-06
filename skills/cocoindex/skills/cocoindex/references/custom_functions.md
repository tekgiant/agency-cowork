# Custom Functions Reference

Complete guide for creating custom functions in CocoIndex.

## Overview

Custom functions allow creating data transformation logic that can be used within flows. Two approaches:

1. **Standalone function** - Simple, no configuration or setup logic
2. **Function spec + executor** - Advanced, with configuration and setup logic

## Standalone Functions

### Basic Example

```python
@cocoindex.op.function(behavior_version=1)
def compute_word_count(text: str) -> int:
    """Count words in text."""
    return len(text.split())
```

**Requirements:**
- Decorate with `@cocoindex.op.function()`
- Type annotations required for all arguments and return value
- Supports basic types, structs, tables, and numpy arrays

### With Optional Parameters

```python
@cocoindex.op.function(behavior_version=1)
def extract_info(content: str, filename: str, max_length: int | None = None) -> dict:
    info = {
        "filename": filename,
        "length": len(content),
        "word_count": len(content.split())
    }
    if max_length and len(content) > max_length:
        info["truncated"] = True
    return info
```

### Using in Flows

```python
@cocoindex.flow_def(name="MyFlow")
def my_flow(flow_builder: cocoindex.FlowBuilder, data_scope: cocoindex.DataScope):
    data_scope["documents"] = flow_builder.add_source(
        cocoindex.sources.LocalFile(path="documents")
    )

    collector = data_scope.add_collector()

    with data_scope["documents"].row() as doc:
        doc["word_count"] = doc["content"].transform(compute_word_count)
        doc["info"] = doc["content"].transform(
            extract_info, filename=doc["filename"], max_length=1000
        )

        collector.collect(
            filename=doc["filename"],
            word_count=doc["word_count"],
            info=doc["info"]
        )

    collector.export("documents", cocoindex.targets.Postgres(), primary_key_fields=["filename"])
```

## Function Spec + Executor

Use for functions that need configuration or setup logic (e.g., loading models).

### Basic Structure

```python
class ComputeSomething(cocoindex.op.FunctionSpec):
    """Configuration for the ComputeSomething function."""
    param1: str
    param2: int = 10

@cocoindex.op.executor_class(behavior_version=1)
class ComputeSomethingExecutor:
    spec: ComputeSomething

    def prepare(self) -> None:
        """Optional: Setup logic run once before execution."""
        pass

    def __call__(self, input_data: str) -> dict:
        """Required: Execute for each data row."""
        return {"result": f"{input_data}-{self.spec.param1}"}
```

### Example: Custom Embedding Function

```python
from sentence_transformers import SentenceTransformer
import numpy as np
from numpy.typing import NDArray

class CustomEmbed(cocoindex.op.FunctionSpec):
    model_name: str
    normalize: bool = True

@cocoindex.op.executor_class(cache=True, behavior_version=1)
class CustomEmbedExecutor:
    spec: CustomEmbed
    model: SentenceTransformer | None = None

    def prepare(self) -> None:
        self.model = SentenceTransformer(self.spec.model_name)

    def __call__(self, text: str) -> NDArray[np.float32]:
        assert self.model is not None
        embedding = self.model.encode(text, normalize_embeddings=self.spec.normalize)
        return embedding.astype(np.float32)
```

### Example: PDF Processing

```python
import pymupdf

class PdfToMarkdown(cocoindex.op.FunctionSpec):
    extract_images: bool = False
    page_range: tuple[int, int] | None = None

@cocoindex.op.executor_class(cache=True, behavior_version=1)
class PdfToMarkdownExecutor:
    spec: PdfToMarkdown

    def __call__(self, pdf_bytes: bytes) -> str:
        doc = pymupdf.Document(stream=pdf_bytes, filetype="pdf")
        start, end = 0, doc.page_count
        if self.spec.page_range:
            start, end = max(0, self.spec.page_range[0]), min(doc.page_count, self.spec.page_range[1])

        markdown_parts = []
        for page_num in range(start, end):
            page = doc[page_num]
            text = page.get_text()
            markdown_parts.append(f"# Page {page_num + 1}\n\n{text}")

        return "\n\n".join(markdown_parts)
```

## Function Parameters

### cache (bool)

Enable caching of function results for reuse during reprocessing.

```python
@cocoindex.op.function(cache=True, behavior_version=1)
def expensive_computation(text: str) -> dict:
    return {"result": analyze(text)}
```

**When to use:** LLM API calls, model inference, external API calls, computationally expensive operations.

### behavior_version (int)

Required when `cache=True`. Increment when function behavior changes to invalidate cache.

### gpu (bool)

Indicates the function uses GPU resources, affecting scheduling.

### arg_relationship

Specifies metadata about argument relationships for tools like CocoInsight.

**Supported relationships:**
- `ArgRelationship.CHUNKS_BASE_TEXT` - Output is chunks of input text
- `ArgRelationship.EMBEDDING_ORIGIN_TEXT` - Output is embedding of input text
- `ArgRelationship.RECTS_BASE_IMAGE` - Output is rectangles on input image

## Supported Data Types

### Basic Types
- `str`, `int`, `float`, `bool`, `bytes`, `None`

### Collection Types
- `list[T]`, `dict[str, T]`, `cocoindex.Json`

### Numpy Types
- `NDArray[np.float32]`, `NDArray[np.float64]`, `NDArray[np.int32]`, `NDArray[np.int64]`

### CocoIndex Types
- `cocoindex.Range` - Text range with location info
- Dataclasses - Become Struct types

### Optional Types
- `T | None` or `Optional[T]`

## Common Patterns

### Pattern: LLM-based Extraction

```python
from openai import OpenAI

class ExtractStructuredInfo(cocoindex.op.FunctionSpec):
    model: str = "gpt-4"
    system_prompt: str = "Extract key information from the text."

@cocoindex.op.executor_class(cache=True, behavior_version=1)
class ExtractStructuredInfoExecutor:
    spec: ExtractStructuredInfo
    client: OpenAI | None = None

    def prepare(self) -> None:
        self.client = OpenAI()

    def __call__(self, text: str) -> dict:
        assert self.client is not None
        response = self.client.chat.completions.create(
            model=self.spec.model,
            messages=[
                {"role": "system", "content": self.spec.system_prompt},
                {"role": "user", "content": text}
            ]
        )
        return {"extracted": response.choices[0].message.content}
```

### Pattern: External API Call

```python
import requests

class FetchEnrichmentData(cocoindex.op.FunctionSpec):
    api_endpoint: str
    api_key: str

@cocoindex.op.executor_class(cache=True, behavior_version=1)
class FetchEnrichmentDataExecutor:
    spec: FetchEnrichmentData

    def __call__(self, entity_id: str) -> dict:
        response = requests.get(
            f"{self.spec.api_endpoint}/entities/{entity_id}",
            headers={"Authorization": f"Bearer {self.spec.api_key}"}
        )
        response.raise_for_status()
        return response.json()
```

### Pattern: Multi-step Processing

```python
class ProcessDocument(cocoindex.op.FunctionSpec):
    min_quality_score: float = 0.7

@cocoindex.op.executor_class(cache=True, behavior_version=1)
class ProcessDocumentExecutor:
    spec: ProcessDocument
    nlp_model = None

    def prepare(self) -> None:
        import spacy
        self.nlp_model = spacy.load("en_core_web_sm")

    def __call__(self, text: str) -> dict:
        cleaned = text.strip()
        doc = self.nlp_model(cleaned)
        entities = [ent.text for ent in doc.ents]
        quality_score = len(cleaned) / 1000.0

        return {
            "cleaned_text": cleaned if quality_score >= self.spec.min_quality_score else None,
            "entities": entities,
            "quality_score": quality_score
        }
```

## Best Practices

1. **Use caching for expensive operations** - Enable `cache=True` for LLM calls, model inference, or external APIs
2. **Type annotations required** - All arguments and return types must be annotated
3. **Increment behavior_version** - When changing cached function logic
4. **Use prepare() for initialization** - Load models, establish connections once
5. **Keep functions focused** - Each function should do one thing well
6. **Handle errors gracefully** - Consider edge cases and invalid inputs
