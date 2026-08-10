# Search Benchmark Summary

- generated_at: 2026-08-07T15:34:41+08:00
- document: 梁文锋投资者交流会.pdf
- query: 有多少华为卡
- target_text: 一万六千张卡
- scenario_count: 12

| database | dense | sparse | sparse_impl | mode | rerank | top_k | fetch_k | warmup_runs | runs | samples | p50_ms | p95_ms | p99_ms | avg_ms | min_ms | max_ms | errors | target_found | target_rank |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| chroma | bge-base | bm25 | app | dense | none | 5 | - | 2 | 30 | 30 | 44.0 | 53.1 | 55.3 | 45.4 | 38.5 | 56.1 | 0 | False | - |
| chroma | bge-base | bm25 | app | dense | none | 20 | - | 2 | 30 | 30 | 41.9 | 48.6 | 53.8 | 42.5 | 38.4 | 55.8 | 0 | True | 6 |
| chroma | bge-base | bm25 | app | sparse | none | 5 | - | 2 | 30 | 30 | 137.8 | 151.0 | 165.0 | 140.8 | 132.1 | 169.7 | 0 | True | 2 |
| chroma | bge-base | bm25 | app | sparse | none | 20 | - | 2 | 30 | 30 | 135.8 | 171.2 | 198.5 | 141.6 | 132.7 | 209.2 | 0 | True | 2 |
| chroma | bge-base | bm25 | app | hybrid | none | 5 | - | 2 | 30 | 30 | 174.4 | 212.3 | 235.3 | 181.8 | 168.4 | 243.3 | 0 | True | 4 |
| chroma | bge-base | bm25 | app | hybrid | none | 20 | - | 2 | 30 | 30 | 175.9 | 257.8 | 310.3 | 187.0 | 169.5 | 329.0 | 0 | True | 4 |
| chroma | bge-m3 | bm25 | app | dense | none | 5 | - | 2 | 30 | 30 | 40.6 | 49.0 | 53.4 | 42.3 | 38.7 | 55.1 | 0 | False | - |
| chroma | bge-m3 | bm25 | app | dense | none | 20 | - | 2 | 30 | 30 | 42.6 | 47.8 | 56.6 | 43.4 | 39.6 | 60.1 | 0 | True | 6 |
| chroma | bge-m3 | bm25 | app | sparse | none | 5 | - | 2 | 30 | 30 | 136.7 | 177.8 | 218.3 | 142.5 | 131.8 | 226.3 | 0 | True | 2 |
| chroma | bge-m3 | bm25 | app | sparse | none | 20 | - | 2 | 30 | 30 | 136.6 | 152.7 | 159.7 | 138.6 | 132.4 | 161.3 | 0 | True | 2 |
| chroma | bge-m3 | bm25 | app | hybrid | none | 5 | - | 2 | 30 | 30 | 175.8 | 189.2 | 231.4 | 178.9 | 166.5 | 247.5 | 0 | True | 4 |
| chroma | bge-m3 | bm25 | app | hybrid | none | 20 | - | 2 | 30 | 30 | 174.9 | 181.1 | 211.9 | 176.5 | 169.1 | 224.4 | 0 | True | 4 |
