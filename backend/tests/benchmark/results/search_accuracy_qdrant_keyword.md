# Search Accuracy Benchmark

- document: 梁文锋投资者交流会.pdf
- database: qdrant
- query_name: keyword
- query: 有多少华为卡
- target_text: 一万六千张卡
- scenario_count: 72

| database | dense | sparse | sparse_impl | mode | rerank | top_k | target_rank |
| --- | --- | --- | --- | --- | --- | --- | --- |
| qdrant | bge-base | bm25 | app | dense | none | 5 | - |
| qdrant | bge-base | bm25 | app | dense | none | 20 | 6 |
| qdrant | bge-base | bm25 | app | sparse | none | 5 | 2 |
| qdrant | bge-base | bm25 | app | sparse | none | 20 | 2 |
| qdrant | bge-base | bm25 | app | hybrid | none | 5 | - |
| qdrant | bge-base | bm25 | app | hybrid | none | 20 | 2 |
| qdrant | bge-base | bm25 | app | dense | bge-reranker-base | 5 | 3 |
| qdrant | bge-base | bm25 | app | dense | bge-reranker-base | 20 | 3 |
| qdrant | bge-base | bm25 | app | sparse | bge-reranker-base | 5 | 3 |
| qdrant | bge-base | bm25 | app | sparse | bge-reranker-base | 20 | 3 |
| qdrant | bge-base | bm25 | app | hybrid | bge-reranker-base | 5 | 3 |
| qdrant | bge-base | bm25 | app | hybrid | bge-reranker-base | 20 | 3 |
| qdrant | bge-base | bm25 | app | dense | bge-reranker-large | 5 | - |
| qdrant | bge-base | bm25 | app | dense | bge-reranker-large | 20 | 6 |
| qdrant | bge-base | bm25 | app | sparse | bge-reranker-large | 5 | - |
| qdrant | bge-base | bm25 | app | sparse | bge-reranker-large | 20 | 6 |
| qdrant | bge-base | bm25 | app | hybrid | bge-reranker-large | 5 | - |
| qdrant | bge-base | bm25 | app | hybrid | bge-reranker-large | 20 | 6 |
| qdrant | bge-base | bm25 | app | dense | bge-reranker-v2-m3 | 5 | 3 |
| qdrant | bge-base | bm25 | app | dense | bge-reranker-v2-m3 | 20 | 3 |
| qdrant | bge-base | bm25 | app | sparse | bge-reranker-v2-m3 | 5 | 3 |
| qdrant | bge-base | bm25 | app | sparse | bge-reranker-v2-m3 | 20 | 3 |
| qdrant | bge-base | bm25 | app | hybrid | bge-reranker-v2-m3 | 5 | 3 |
| qdrant | bge-base | bm25 | app | hybrid | bge-reranker-v2-m3 | 20 | 3 |
| qdrant | bge-m3 | bm25 | app | dense | none | 5 | - |
| qdrant | bge-m3 | bm25 | app | dense | none | 20 | 6 |
| qdrant | bge-m3 | bm25 | app | sparse | none | 5 | 2 |
| qdrant | bge-m3 | bm25 | app | sparse | none | 20 | 2 |
| qdrant | bge-m3 | bm25 | app | hybrid | none | 5 | - |
| qdrant | bge-m3 | bm25 | app | hybrid | none | 20 | 2 |
| qdrant | bge-m3 | bm25 | app | dense | bge-reranker-base | 5 | 3 |
| qdrant | bge-m3 | bm25 | app | dense | bge-reranker-base | 20 | 3 |
| qdrant | bge-m3 | bm25 | app | sparse | bge-reranker-base | 5 | 3 |
| qdrant | bge-m3 | bm25 | app | sparse | bge-reranker-base | 20 | 3 |
| qdrant | bge-m3 | bm25 | app | hybrid | bge-reranker-base | 5 | 3 |
| qdrant | bge-m3 | bm25 | app | hybrid | bge-reranker-base | 20 | 3 |
| qdrant | bge-m3 | bm25 | app | dense | bge-reranker-large | 5 | - |
| qdrant | bge-m3 | bm25 | app | dense | bge-reranker-large | 20 | 6 |
| qdrant | bge-m3 | bm25 | app | sparse | bge-reranker-large | 5 | - |
| qdrant | bge-m3 | bm25 | app | sparse | bge-reranker-large | 20 | 6 |
| qdrant | bge-m3 | bm25 | app | hybrid | bge-reranker-large | 5 | - |
| qdrant | bge-m3 | bm25 | app | hybrid | bge-reranker-large | 20 | 6 |
| qdrant | bge-m3 | bm25 | app | dense | bge-reranker-v2-m3 | 5 | 3 |
| qdrant | bge-m3 | bm25 | app | dense | bge-reranker-v2-m3 | 20 | 3 |
| qdrant | bge-m3 | bm25 | app | sparse | bge-reranker-v2-m3 | 5 | 3 |
| qdrant | bge-m3 | bm25 | app | sparse | bge-reranker-v2-m3 | 20 | 3 |
| qdrant | bge-m3 | bm25 | app | hybrid | bge-reranker-v2-m3 | 5 | 3 |
| qdrant | bge-m3 | bm25 | app | hybrid | bge-reranker-v2-m3 | 20 | 3 |
| qdrant | bge-m3 | bge-m3 | store | dense | none | 5 | - |
| qdrant | bge-m3 | bge-m3 | store | dense | none | 20 | 6 |
| qdrant | bge-m3 | bge-m3 | store | sparse | none | 5 | 3 |
| qdrant | bge-m3 | bge-m3 | store | sparse | none | 20 | 3 |
| qdrant | bge-m3 | bge-m3 | store | hybrid | none | 5 | 5 |
| qdrant | bge-m3 | bge-m3 | store | hybrid | none | 20 | 5 |
| qdrant | bge-m3 | bge-m3 | store | dense | bge-reranker-base | 5 | 3 |
| qdrant | bge-m3 | bge-m3 | store | dense | bge-reranker-base | 20 | 3 |
| qdrant | bge-m3 | bge-m3 | store | sparse | bge-reranker-base | 5 | 3 |
| qdrant | bge-m3 | bge-m3 | store | sparse | bge-reranker-base | 20 | 3 |
| qdrant | bge-m3 | bge-m3 | store | hybrid | bge-reranker-base | 5 | 3 |
| qdrant | bge-m3 | bge-m3 | store | hybrid | bge-reranker-base | 20 | 3 |
| qdrant | bge-m3 | bge-m3 | store | dense | bge-reranker-large | 5 | - |
| qdrant | bge-m3 | bge-m3 | store | dense | bge-reranker-large | 20 | 6 |
| qdrant | bge-m3 | bge-m3 | store | sparse | bge-reranker-large | 5 | - |
| qdrant | bge-m3 | bge-m3 | store | sparse | bge-reranker-large | 20 | 6 |
| qdrant | bge-m3 | bge-m3 | store | hybrid | bge-reranker-large | 5 | - |
| qdrant | bge-m3 | bge-m3 | store | hybrid | bge-reranker-large | 20 | 6 |
| qdrant | bge-m3 | bge-m3 | store | dense | bge-reranker-v2-m3 | 5 | 3 |
| qdrant | bge-m3 | bge-m3 | store | dense | bge-reranker-v2-m3 | 20 | 3 |
| qdrant | bge-m3 | bge-m3 | store | sparse | bge-reranker-v2-m3 | 5 | 3 |
| qdrant | bge-m3 | bge-m3 | store | sparse | bge-reranker-v2-m3 | 20 | 3 |
| qdrant | bge-m3 | bge-m3 | store | hybrid | bge-reranker-v2-m3 | 5 | 3 |
| qdrant | bge-m3 | bge-m3 | store | hybrid | bge-reranker-v2-m3 | 20 | 3 |
