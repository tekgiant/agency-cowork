# API Operations Reference

Guide for operating CocoIndex flows programmatically using Python APIs.

## Basic Setup

```python
from dotenv import load_dotenv
import cocoindex

load_dotenv()
cocoindex.init()

@cocoindex.flow_def(name="MyFlow")
def my_flow(flow_builder: cocoindex.FlowBuilder, data_scope: cocoindex.DataScope):
    pass
```

## Flow Operations

### Setup / Drop

```python
my_flow.setup(report_to_stdout=True)
await my_flow.setup_async(report_to_stdout=True)

my_flow.drop(report_to_stdout=True)
await my_flow.drop_async(report_to_stdout=True)

cocoindex.setup_all_flows(report_to_stdout=True)
cocoindex.drop_all_flows(report_to_stdout=True)
```

### One-Time Update

```python
stats = my_flow.update()
stats = my_flow.update(reexport_targets=True)
stats = await my_flow.update_async()
```

### Live Update

```python
updater = cocoindex.FlowLiveUpdater(
    my_flow,
    cocoindex.FlowLiveUpdaterOptions(
        live_mode=True,
        print_stats=True,
        reexport_targets=False
    )
)
updater.start()
updater.wait()

# As context manager
with cocoindex.FlowLiveUpdater(my_flow) as updater:
    pass  # Updater runs in background

# Async
async with cocoindex.FlowLiveUpdater(my_flow) as updater:
    pass
```

### Monitoring Status Updates

```python
updater = cocoindex.FlowLiveUpdater(my_flow)
updater.start()

while True:
    updates = updater.next_status_updates()
    for source in updates.updated_sources:
        print(f"Source {source} has new data")
    if not updates.active_sources:
        break
```

### Evaluate Flow (Testing)

```python
my_flow.evaluate_and_dump(
    cocoindex.EvaluateAndDumpOptions(
        output_dir="./eval_output",
        use_cache=True
    )
)
```

## Query Operations

### Transform Flows

```python
@cocoindex.transform_flow()
def text_to_embedding(
    text: cocoindex.DataSlice[str]
) -> cocoindex.DataSlice[list[float]]:
    return text.transform(
        cocoindex.functions.SentenceTransformerEmbed(model="...")
    )

# Use in indexing flow
doc["embedding"] = text_to_embedding(doc["content"])

# Use for querying
query_embedding = text_to_embedding.eval("search query")
```

### Query Handlers

```python
import functools
from psycopg_pool import ConnectionPool

@functools.cache
def connection_pool():
    return ConnectionPool(os.environ["COCOINDEX_DATABASE_URL"])

@my_flow.query_handler(
    result_fields=cocoindex.QueryHandlerResultFields(
        embedding=["embedding"],
        score="score"
    )
)
def search(query: str) -> cocoindex.QueryOutput:
    table_name = cocoindex.utils.get_target_default_name(my_flow, "doc_embeddings")
    query_vector = text_to_embedding.eval(query)

    with connection_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT filename, text, embedding, embedding <=> %s AS distance "
                f"FROM {table_name} ORDER BY distance LIMIT 10",
                (query_vector,)
            )
            return cocoindex.QueryOutput(
                query_info=cocoindex.QueryInfo(
                    embedding=query_vector,
                    similarity_metric=cocoindex.VectorSimilarityMetric.COSINE_SIMILARITY
                ),
                results=[
                    {"filename": r[0], "text": r[1], "embedding": r[2], "score": 1.0 - r[3]}
                    for r in cur.fetchall()
                ]
            )
```

## Application Integration Patterns

### Pattern 1: Simple Application with Update

```python
def main():
    stats = my_app_flow.update()
    while True:
        query = input("Search: ")
        if not query:
            break
        results = search(query)
        for result in results.results:
            print(f"  {result['score']:.3f}: {result['text']}")
```

### Pattern 2: Web Application with Live Updates

```python
from fastapi import FastAPI

app = FastAPI()
updater = None

@app.on_event("startup")
async def startup():
    global updater
    updater = cocoindex.FlowLiveUpdater(
        web_app_flow,
        cocoindex.FlowLiveUpdaterOptions(live_mode=True, print_stats=True)
    )
    await updater.start_async()

@app.on_event("shutdown")
async def shutdown():
    if updater:
        updater.abort()
        await updater.wait_async()

@app.get("/search")
async def search_endpoint(q: str):
    results = search(q)
    return {"query": q, "results": results.results}
```

### Pattern 3: Batch Processing

```python
def process_batch():
    batch_flow.setup()
    stats = batch_flow.update()
    print(f"Batch completed: {stats.total_rows} rows processed")
    return stats
```

### Pattern 4: React to Updates

```python
async def run_with_reactions():
    async with cocoindex.FlowLiveUpdater(reactive_flow) as updater:
        while True:
            updates = await updater.next_status_updates_async()
            if "products" in updates.updated_sources:
                await rebuild_product_index()
            if not updates.active_sources:
                break
```

## Error Handling

```python
try:
    stats = my_flow.update()
except cocoindex.CocoIndexError as e:
    print(f"Update failed: {e}")
```

### Graceful Shutdown

```python
import signal

def signal_handler(sig, frame):
    if updater:
        updater.abort()
        updater.wait()
    exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
```

## Best Practices

1. **Always call cocoindex.init()** before using any CocoIndex APIs
2. **Load environment variables** with dotenv
3. **Use context managers** for live updaters
4. **Cache expensive resources** with `@functools.cache`
5. **Handle signals** for graceful shutdown
6. **Separate concerns** - keep flow definitions, queries, and app logic separate
7. **Use transform flows** to share logic between indexing and querying
8. **Test with evaluate** before running updates
