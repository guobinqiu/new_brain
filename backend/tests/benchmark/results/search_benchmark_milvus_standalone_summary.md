# Search Benchmark Summary

- generated_at: 2026-08-10T10:29:17+08:00
- document: 梁文锋投资者交流会.pdf
- query: 有多少华为卡
- target_text: 一万六千张卡
- scenario_count: 30

| database | dense | sparse | sparse_impl | mode | rerank | top_k | fetch_k | warmup_runs | runs | samples | p50_ms | p95_ms | p99_ms | avg_ms | min_ms | max_ms | errors | target_found | target_rank |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| milvus-standalone | bge-base | bm25 | app | dense | none | 5 | - | 2 | 30 | 30 | 51.0 | 86.3 | 92.9 | 56.3 | 43.5 | 93.0 | 0 | False | - |
| milvus-standalone | bge-base | bm25 | app | dense | none | 20 | - | 2 | 30 | 30 | 46.9 | 54.9 | 55.8 | 47.7 | 43.3 | 56.0 | 0 | True | 15 |
| milvus-standalone | bge-base | bm25 | app | sparse | none | 5 | - | 2 | 30 | 30 | 183.3 | 281.3 | 291.5 | 198.7 | 162.6 | 292.9 | 0 | True | 2 |
| milvus-standalone | bge-base | bm25 | app | sparse | none | 20 | - | 2 | 30 | 30 | 189.9 | 454.0 | 657.7 | 236.8 | 170.0 | 706.7 | 0 | True | 2 |
| milvus-standalone | bge-base | bm25 | app | hybrid | none | 5 | - | 2 | 30 | 30 | 310.0 | 502.4 | 938.3 | 349.3 | 211.9 | 1112.7 | 0 | True | 4 |
| milvus-standalone | bge-base | bm25 | app | hybrid | none | 20 | - | 2 | 30 | 30 | 259.9 | 544.2 | 580.2 | 297.5 | 208.4 | 582.8 | 0 | True | 4 |
| milvus-standalone | bge-m3 | bm25 | app | dense | none | 5 | - | 2 | 30 | 30 | 76.8 | 362.9 | 506.6 | 119.4 | 59.7 | 522.0 | 0 | False | - |
| milvus-standalone | bge-m3 | bm25 | app | dense | none | 20 | - | 2 | 30 | 30 | 65.3 | 171.3 | 259.1 | 86.0 | 50.7 | 287.4 | 0 | True | 15 |
| milvus-standalone | bge-m3 | bm25 | app | sparse | none | 5 | - | 2 | 30 | 30 | 337.9 | 585.2 | 676.4 | 367.4 | 196.1 | 713.5 | 0 | True | 2 |
| milvus-standalone | bge-m3 | bm25 | app | sparse | none | 20 | - | 2 | 30 | 30 | 260.8 | 683.7 | 810.0 | 316.1 | 167.9 | 810.5 | 0 | True | 2 |
| milvus-standalone | bge-m3 | bm25 | app | hybrid | none | 5 | - | 2 | 30 | 30 | 281.8 | 762.4 | 1323.7 | 382.8 | 223.7 | 1515.1 | 0 | True | 4 |
| milvus-standalone | bge-m3 | bm25 | app | hybrid | none | 20 | - | 2 | 30 | 30 | 272.7 | 385.4 | 461.4 | 285.3 | 209.1 | 492.0 | 0 | True | 4 |
| milvus-standalone | bge-m3 | bge-m3 | store | dense | none | 5 | - | 2 | 30 | 30 | 63.7 | 88.9 | 124.5 | 68.2 | 47.7 | 138.0 | 0 | False | - |
| milvus-standalone | bge-m3 | bge-m3 | store | dense | none | 20 | - | 2 | 30 | 30 | 69.3 | 205.6 | 2014.8 | 172.0 | 54.3 | 2742.0 | 0 | True | 6 |
| milvus-standalone | bge-m3 | bge-m3 | store | sparse | none | 5 | - | 2 | 30 | 30 | 126.1 | 192.5 | 229.9 | 134.3 | 106.3 | 240.4 | 0 | True | 3 |
| milvus-standalone | bge-m3 | bge-m3 | store | sparse | none | 20 | - | 2 | 30 | 30 | 117.8 | 159.4 | 164.1 | 121.7 | 100.8 | 165.7 | 0 | True | 3 |
| milvus-standalone | bge-m3 | bge-m3 | store | hybrid | none | 5 | - | 2 | 30 | 30 | 201.0 | 273.0 | 474.7 | 212.4 | 135.9 | 550.4 | 0 | True | 5 |
| milvus-standalone | bge-m3 | bge-m3 | store | hybrid | none | 20 | - | 2 | 30 | 30 | 191.3 | 308.6 | 444.4 | 213.8 | 157.8 | 497.9 | 0 | True | 5 |
| milvus-standalone | bge-base | bm25 | store | dense | none | 5 | - | 2 | 30 | 30 | 59.8 | 103.7 | 137.2 | 69.0 | 48.1 | 148.8 | 0 | False | - |
| milvus-standalone | bge-base | bm25 | store | dense | none | 20 | - | 2 | 30 | 30 | 58.3 | 111.9 | 143.9 | 68.4 | 50.1 | 150.3 | 0 | True | 6 |
| milvus-standalone | bge-base | bm25 | store | sparse | none | 5 | - | 2 | 30 | 30 | 7.7 | 19.2 | 83.4 | 11.8 | 5.7 | 106.6 | 0 | False | - |
| milvus-standalone | bge-base | bm25 | store | sparse | none | 20 | - | 2 | 30 | 30 | 9.4 | 12.2 | 12.5 | 9.8 | 7.5 | 12.5 | 0 | True | 10 |
| milvus-standalone | bge-base | bm25 | store | hybrid | none | 5 | - | 2 | 30 | 30 | 53.3 | 67.6 | 69.6 | 56.0 | 47.3 | 69.8 | 0 | False | - |
| milvus-standalone | bge-base | bm25 | store | hybrid | none | 20 | - | 2 | 30 | 30 | 59.8 | 120.9 | 139.1 | 71.4 | 50.9 | 144.3 | 0 | True | 8 |
| milvus-standalone | bge-m3 | bm25 | store | dense | none | 5 | - | 2 | 30 | 30 | 68.6 | 277.3 | 296.7 | 93.0 | 47.9 | 300.8 | 0 | False | - |
| milvus-standalone | bge-m3 | bm25 | store | dense | none | 20 | - | 2 | 30 | 30 | 82.7 | 190.8 | 244.3 | 98.1 | 57.5 | 263.7 | 0 | True | 6 |
| milvus-standalone | bge-m3 | bm25 | store | sparse | none | 5 | - | 2 | 30 | 30 | 8.6 | 15.9 | 37.7 | 10.4 | 6.5 | 45.6 | 0 | False | - |
| milvus-standalone | bge-m3 | bm25 | store | sparse | none | 20 | - | 2 | 30 | 30 | 13.3 | 155.0 | 222.6 | 29.8 | 9.2 | 227.2 | 0 | True | 10 |
| milvus-standalone | bge-m3 | bm25 | store | hybrid | none | 5 | - | 2 | 30 | 30 | 87.5 | 262.3 | 384.4 | 110.1 | 48.4 | 432.4 | 0 | False | - |
| milvus-standalone | bge-m3 | bm25 | store | hybrid | none | 20 | - | 2 | 30 | 30 | 57.4 | 99.2 | 108.3 | 63.0 | 45.1 | 110.7 | 0 | True | 8 |
