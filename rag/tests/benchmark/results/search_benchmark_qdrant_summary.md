# Search Benchmark Summary

- generated_at: 2026-08-07T15:30:16+08:00
- document: 梁文锋投资者交流会.pdf
- query: 有多少华为卡
- target_text: 一万六千张卡
- scenario_count: 18

| database | dense | sparse | sparse_impl | mode | rerank | top_k | fetch_k | warmup_runs | runs | samples | p50_ms | p95_ms | p99_ms | avg_ms | min_ms | max_ms | errors | target_found | target_rank |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| qdrant | bge-base | bm25 | app | dense | none | 5 | - | 2 | 30 | 30 | 49.3 | 69.6 | 87.6 | 52.1 | 41.3 | 94.0 | 0 | False | - |
| qdrant | bge-base | bm25 | app | dense | none | 20 | - | 2 | 30 | 30 | 48.8 | 71.2 | 83.9 | 52.6 | 43.0 | 87.2 | 0 | True | 6 |
| qdrant | bge-base | bm25 | app | sparse | none | 5 | - | 2 | 30 | 30 | 151.4 | 214.7 | 232.0 | 163.0 | 137.4 | 238.2 | 0 | True | 2 |
| qdrant | bge-base | bm25 | app | sparse | none | 20 | - | 2 | 30 | 30 | 149.9 | 214.2 | 234.8 | 161.8 | 131.9 | 240.8 | 0 | True | 2 |
| qdrant | bge-base | bm25 | app | hybrid | none | 5 | - | 2 | 30 | 30 | 185.9 | 216.2 | 217.7 | 190.1 | 173.0 | 217.8 | 0 | False | - |
| qdrant | bge-base | bm25 | app | hybrid | none | 20 | - | 2 | 30 | 30 | 186.1 | 212.7 | 264.4 | 191.3 | 176.5 | 282.9 | 0 | True | 2 |
| qdrant | bge-m3 | bm25 | app | dense | none | 5 | - | 2 | 30 | 30 | 64.1 | 142.0 | 165.5 | 73.5 | 48.4 | 168.1 | 0 | False | - |
| qdrant | bge-m3 | bm25 | app | dense | none | 20 | - | 2 | 30 | 30 | 62.6 | 118.5 | 223.3 | 73.2 | 44.9 | 265.1 | 0 | True | 6 |
| qdrant | bge-m3 | bm25 | app | sparse | none | 5 | - | 2 | 30 | 30 | 151.3 | 202.1 | 250.0 | 159.1 | 135.7 | 266.9 | 0 | True | 2 |
| qdrant | bge-m3 | bm25 | app | sparse | none | 20 | - | 2 | 30 | 30 | 147.4 | 165.3 | 171.5 | 149.4 | 135.6 | 172.8 | 0 | True | 2 |
| qdrant | bge-m3 | bm25 | app | hybrid | none | 5 | - | 2 | 30 | 30 | 183.9 | 253.5 | 260.6 | 192.5 | 169.3 | 261.0 | 0 | False | - |
| qdrant | bge-m3 | bm25 | app | hybrid | none | 20 | - | 2 | 30 | 30 | 188.7 | 237.2 | 486.4 | 206.2 | 177.4 | 585.8 | 0 | True | 2 |
| qdrant | bge-m3 | bge-m3 | vector | dense | none | 5 | - | 2 | 30 | 30 | 49.9 | 65.1 | 66.9 | 52.2 | 44.2 | 67.6 | 0 | False | - |
| qdrant | bge-m3 | bge-m3 | vector | dense | none | 20 | - | 2 | 30 | 30 | 49.4 | 65.0 | 71.9 | 51.0 | 44.1 | 72.3 | 0 | True | 6 |
| qdrant | bge-m3 | bge-m3 | vector | sparse | none | 5 | - | 2 | 30 | 30 | 98.8 | 113.4 | 123.6 | 98.8 | 71.8 | 127.6 | 0 | True | 3 |
| qdrant | bge-m3 | bge-m3 | vector | sparse | none | 20 | - | 2 | 30 | 30 | 104.4 | 123.9 | 155.1 | 107.5 | 79.7 | 167.5 | 0 | True | 3 |
| qdrant | bge-m3 | bge-m3 | vector | hybrid | none | 5 | - | 2 | 30 | 30 | 147.6 | 180.4 | 212.5 | 152.4 | 120.7 | 223.0 | 0 | True | 5 |
| qdrant | bge-m3 | bge-m3 | vector | hybrid | none | 20 | - | 2 | 30 | 30 | 136.7 | 165.5 | 504.2 | 152.4 | 111.5 | 641.8 | 0 | True | 5 |
