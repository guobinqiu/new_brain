# Search Accuracy Benchmark

- document: 梁文锋投资者交流会.pdf
- database: chroma
- query_name: simple_semantic
- query: 他们怎么看国产算力和英伟达的差距？
- target_text: 国产算力是比较乐观的
- scenario_count: 48

| database | dense | sparse | sparse_impl | mode | rerank | top_k | target_rank |
| --- | --- | --- | --- | --- | --- | --- | --- |
| chroma | bge-base | bm25 | app | dense | none | 5 | 1 |
| chroma | bge-base | bm25 | app | dense | none | 20 | 1 |
| chroma | bge-base | bm25 | app | sparse | none | 5 | 3 |
| chroma | bge-base | bm25 | app | sparse | none | 20 | 3 |
| chroma | bge-base | bm25 | app | hybrid | none | 5 | 1 |
| chroma | bge-base | bm25 | app | hybrid | none | 20 | 1 |
| chroma | bge-base | bm25 | app | dense | bge-reranker-base | 5 | 1 |
| chroma | bge-base | bm25 | app | dense | bge-reranker-base | 20 | 1 |
| chroma | bge-base | bm25 | app | sparse | bge-reranker-base | 5 | 1 |
| chroma | bge-base | bm25 | app | sparse | bge-reranker-base | 20 | 1 |
| chroma | bge-base | bm25 | app | hybrid | bge-reranker-base | 5 | 1 |
| chroma | bge-base | bm25 | app | hybrid | bge-reranker-base | 20 | 1 |
| chroma | bge-base | bm25 | app | dense | bge-reranker-large | 5 | 1 |
| chroma | bge-base | bm25 | app | dense | bge-reranker-large | 20 | 1 |
| chroma | bge-base | bm25 | app | sparse | bge-reranker-large | 5 | 1 |
| chroma | bge-base | bm25 | app | sparse | bge-reranker-large | 20 | 1 |
| chroma | bge-base | bm25 | app | hybrid | bge-reranker-large | 5 | 1 |
| chroma | bge-base | bm25 | app | hybrid | bge-reranker-large | 20 | 1 |
| chroma | bge-base | bm25 | app | dense | bge-reranker-v2-m3 | 5 | 1 |
| chroma | bge-base | bm25 | app | dense | bge-reranker-v2-m3 | 20 | 1 |
| chroma | bge-base | bm25 | app | sparse | bge-reranker-v2-m3 | 5 | 1 |
| chroma | bge-base | bm25 | app | sparse | bge-reranker-v2-m3 | 20 | 1 |
| chroma | bge-base | bm25 | app | hybrid | bge-reranker-v2-m3 | 5 | 1 |
| chroma | bge-base | bm25 | app | hybrid | bge-reranker-v2-m3 | 20 | 1 |
| chroma | bge-m3 | bm25 | app | dense | none | 5 | 1 |
| chroma | bge-m3 | bm25 | app | dense | none | 20 | 1 |
| chroma | bge-m3 | bm25 | app | sparse | none | 5 | 3 |
| chroma | bge-m3 | bm25 | app | sparse | none | 20 | 3 |
| chroma | bge-m3 | bm25 | app | hybrid | none | 5 | 1 |
| chroma | bge-m3 | bm25 | app | hybrid | none | 20 | 1 |
| chroma | bge-m3 | bm25 | app | dense | bge-reranker-base | 5 | 1 |
| chroma | bge-m3 | bm25 | app | dense | bge-reranker-base | 20 | 1 |
| chroma | bge-m3 | bm25 | app | sparse | bge-reranker-base | 5 | 1 |
| chroma | bge-m3 | bm25 | app | sparse | bge-reranker-base | 20 | 1 |
| chroma | bge-m3 | bm25 | app | hybrid | bge-reranker-base | 5 | 1 |
| chroma | bge-m3 | bm25 | app | hybrid | bge-reranker-base | 20 | 1 |
| chroma | bge-m3 | bm25 | app | dense | bge-reranker-large | 5 | 1 |
| chroma | bge-m3 | bm25 | app | dense | bge-reranker-large | 20 | 1 |
| chroma | bge-m3 | bm25 | app | sparse | bge-reranker-large | 5 | 1 |
| chroma | bge-m3 | bm25 | app | sparse | bge-reranker-large | 20 | 1 |
| chroma | bge-m3 | bm25 | app | hybrid | bge-reranker-large | 5 | 1 |
| chroma | bge-m3 | bm25 | app | hybrid | bge-reranker-large | 20 | 1 |
| chroma | bge-m3 | bm25 | app | dense | bge-reranker-v2-m3 | 5 | 1 |
| chroma | bge-m3 | bm25 | app | dense | bge-reranker-v2-m3 | 20 | 1 |
| chroma | bge-m3 | bm25 | app | sparse | bge-reranker-v2-m3 | 5 | 1 |
| chroma | bge-m3 | bm25 | app | sparse | bge-reranker-v2-m3 | 20 | 1 |
| chroma | bge-m3 | bm25 | app | hybrid | bge-reranker-v2-m3 | 5 | 1 |
| chroma | bge-m3 | bm25 | app | hybrid | bge-reranker-v2-m3 | 20 | 1 |
