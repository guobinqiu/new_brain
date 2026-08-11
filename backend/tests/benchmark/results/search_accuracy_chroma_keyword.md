# Search Accuracy Benchmark

- document: 梁文锋投资者交流会.pdf
- database: chroma
- query_name: keyword
- query: 有多少华为卡
- target_text: 一万六千张卡
- scenario_count: 48

| database | dense | sparse | sparse_impl | mode | rerank | top_k | target_rank |
| --- | --- | --- | --- | --- | --- | --- | --- |
| chroma | bge-base | bm25 | app | dense | none | 5 | - |
| chroma | bge-base | bm25 | app | dense | none | 20 | 6 |
| chroma | bge-base | bm25 | app | sparse | none | 5 | 2 |
| chroma | bge-base | bm25 | app | sparse | none | 20 | 2 |
| chroma | bge-base | bm25 | app | hybrid | none | 5 | 4 |
| chroma | bge-base | bm25 | app | hybrid | none | 20 | 4 |
| chroma | bge-base | bm25 | app | dense | bge-reranker-base | 5 | 3 |
| chroma | bge-base | bm25 | app | dense | bge-reranker-base | 20 | 3 |
| chroma | bge-base | bm25 | app | sparse | bge-reranker-base | 5 | 3 |
| chroma | bge-base | bm25 | app | sparse | bge-reranker-base | 20 | 3 |
| chroma | bge-base | bm25 | app | hybrid | bge-reranker-base | 5 | 5 |
| chroma | bge-base | bm25 | app | hybrid | bge-reranker-base | 20 | 5 |
| chroma | bge-base | bm25 | app | dense | bge-reranker-large | 5 | - |
| chroma | bge-base | bm25 | app | dense | bge-reranker-large | 20 | 6 |
| chroma | bge-base | bm25 | app | sparse | bge-reranker-large | 5 | - |
| chroma | bge-base | bm25 | app | sparse | bge-reranker-large | 20 | 6 |
| chroma | bge-base | bm25 | app | hybrid | bge-reranker-large | 5 | - |
| chroma | bge-base | bm25 | app | hybrid | bge-reranker-large | 20 | 11 |
| chroma | bge-base | bm25 | app | dense | bge-reranker-v2-m3 | 5 | 3 |
| chroma | bge-base | bm25 | app | dense | bge-reranker-v2-m3 | 20 | 3 |
| chroma | bge-base | bm25 | app | sparse | bge-reranker-v2-m3 | 5 | 3 |
| chroma | bge-base | bm25 | app | sparse | bge-reranker-v2-m3 | 20 | 3 |
| chroma | bge-base | bm25 | app | hybrid | bge-reranker-v2-m3 | 5 | 5 |
| chroma | bge-base | bm25 | app | hybrid | bge-reranker-v2-m3 | 20 | 5 |
| chroma | bge-m3 | bm25 | app | dense | none | 5 | - |
| chroma | bge-m3 | bm25 | app | dense | none | 20 | 6 |
| chroma | bge-m3 | bm25 | app | sparse | none | 5 | 2 |
| chroma | bge-m3 | bm25 | app | sparse | none | 20 | 2 |
| chroma | bge-m3 | bm25 | app | hybrid | none | 5 | 4 |
| chroma | bge-m3 | bm25 | app | hybrid | none | 20 | 4 |
| chroma | bge-m3 | bm25 | app | dense | bge-reranker-base | 5 | 3 |
| chroma | bge-m3 | bm25 | app | dense | bge-reranker-base | 20 | 3 |
| chroma | bge-m3 | bm25 | app | sparse | bge-reranker-base | 5 | 3 |
| chroma | bge-m3 | bm25 | app | sparse | bge-reranker-base | 20 | 3 |
| chroma | bge-m3 | bm25 | app | hybrid | bge-reranker-base | 5 | 5 |
| chroma | bge-m3 | bm25 | app | hybrid | bge-reranker-base | 20 | 5 |
| chroma | bge-m3 | bm25 | app | dense | bge-reranker-large | 5 | - |
| chroma | bge-m3 | bm25 | app | dense | bge-reranker-large | 20 | 6 |
| chroma | bge-m3 | bm25 | app | sparse | bge-reranker-large | 5 | - |
| chroma | bge-m3 | bm25 | app | sparse | bge-reranker-large | 20 | 6 |
| chroma | bge-m3 | bm25 | app | hybrid | bge-reranker-large | 5 | - |
| chroma | bge-m3 | bm25 | app | hybrid | bge-reranker-large | 20 | 11 |
| chroma | bge-m3 | bm25 | app | dense | bge-reranker-v2-m3 | 5 | 3 |
| chroma | bge-m3 | bm25 | app | dense | bge-reranker-v2-m3 | 20 | 3 |
| chroma | bge-m3 | bm25 | app | sparse | bge-reranker-v2-m3 | 5 | 3 |
| chroma | bge-m3 | bm25 | app | sparse | bge-reranker-v2-m3 | 20 | 3 |
| chroma | bge-m3 | bm25 | app | hybrid | bge-reranker-v2-m3 | 5 | 5 |
| chroma | bge-m3 | bm25 | app | hybrid | bge-reranker-v2-m3 | 20 | 5 |
