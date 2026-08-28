# Search Benchmark Summary

- generated_at: 2026-08-10T10:37:46+08:00
- document: 梁文锋投资者交流会.pdf
- query: 有多少华为卡
- target_text: 一万六千张卡
- scenario_count: 30

| database | dense | sparse | sparse_impl | mode | rerank | top_k | fetch_k | warmup_runs | runs | samples | p50_ms | p95_ms | p99_ms | avg_ms | min_ms | max_ms | errors | target_found | target_rank |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| milvus-lite | bge-base | bm25 | app | dense | none | 5 | - | 2 | 30 | 30 | 147.1 | 581.4 | 861.5 | 216.7 | 100.8 | 936.9 | 0 | False | - |
| milvus-lite | bge-base | bm25 | app | dense | none | 20 | - | 2 | 30 | 30 | 96.1 | 230.3 | 315.8 | 113.4 | 85.2 | 324.7 | 0 | True | 15 |
| milvus-lite | bge-base | bm25 | app | sparse | none | 5 | - | 2 | 30 | 30 | 270.0 | 456.2 | 744.2 | 316.6 | 244.1 | 859.4 | 0 | True | 2 |
| milvus-lite | bge-base | bm25 | app | sparse | none | 20 | - | 2 | 30 | 30 | 256.6 | 443.2 | 455.8 | 290.6 | 236.3 | 457.3 | 0 | True | 2 |
| milvus-lite | bge-base | bm25 | app | hybrid | none | 5 | - | 2 | 30 | 30 | 369.1 | 632.7 | 798.2 | 410.4 | 319.2 | 855.4 | 0 | True | 4 |
| milvus-lite | bge-base | bm25 | app | hybrid | none | 20 | - | 2 | 30 | 30 | 383.2 | 777.6 | 848.6 | 439.1 | 329.1 | 873.2 | 0 | True | 4 |
| milvus-lite | bge-m3 | bm25 | app | dense | none | 5 | - | 2 | 30 | 30 | 91.0 | 160.9 | 226.8 | 103.5 | 78.7 | 245.0 | 0 | False | - |
| milvus-lite | bge-m3 | bm25 | app | dense | none | 20 | - | 2 | 30 | 30 | 118.5 | 214.5 | 219.4 | 133.2 | 87.8 | 220.5 | 0 | True | 15 |
| milvus-lite | bge-m3 | bm25 | app | sparse | none | 5 | - | 2 | 30 | 30 | 264.6 | 413.6 | 532.3 | 295.6 | 231.9 | 579.6 | 0 | True | 2 |
| milvus-lite | bge-m3 | bm25 | app | sparse | none | 20 | - | 2 | 30 | 30 | 266.6 | 676.1 | 773.1 | 333.3 | 237.4 | 802.2 | 0 | True | 2 |
| milvus-lite | bge-m3 | bm25 | app | hybrid | none | 5 | - | 2 | 30 | 30 | 412.0 | 802.3 | 948.2 | 457.6 | 322.0 | 958.2 | 0 | True | 4 |
| milvus-lite | bge-m3 | bm25 | app | hybrid | none | 20 | - | 2 | 30 | 30 | 453.6 | 839.6 | 873.2 | 497.8 | 329.1 | 886.9 | 0 | True | 4 |
| milvus-lite | bge-m3 | bge-m3 | vector | dense | none | 5 | - | 2 | 30 | 30 | 80.7 | 129.8 | 223.7 | 91.8 | 74.8 | 257.7 | 0 | False | - |
| milvus-lite | bge-m3 | bge-m3 | vector | dense | none | 20 | - | 2 | 30 | 30 | 90.7 | 179.3 | 233.6 | 104.5 | 78.8 | 247.9 | 0 | True | 6 |
| milvus-lite | bge-m3 | bge-m3 | vector | sparse | none | 5 | - | 2 | 30 | 30 | 150.2 | 1021.8 | 1736.2 | 256.8 | 121.8 | 1763.4 | 0 | False | - |
| milvus-lite | bge-m3 | bge-m3 | vector | sparse | none | 20 | - | 2 | 30 | 30 | 153.2 | 342.1 | 407.3 | 184.1 | 132.3 | 432.7 | 0 | True | 7 |
| milvus-lite | bge-m3 | bge-m3 | vector | hybrid | none | 5 | - | 2 | 30 | 30 | 260.1 | 869.1 | 1309.6 | 342.3 | 204.0 | 1467.2 | 0 | False | - |
| milvus-lite | bge-m3 | bge-m3 | vector | hybrid | none | 20 | - | 2 | 30 | 30 | 306.4 | 1432.2 | 1823.5 | 469.5 | 204.6 | 1830.9 | 0 | True | 4 |
| milvus-lite | bge-base | bm25 | vector | dense | none | 5 | - | 2 | 30 | 30 | 83.6 | 112.1 | 118.0 | 90.0 | 77.4 | 120.4 | 0 | False | - |
| milvus-lite | bge-base | bm25 | vector | dense | none | 20 | - | 2 | 30 | 30 | 90.2 | 115.0 | 124.6 | 93.4 | 82.9 | 126.5 | 0 | True | 6 |
| milvus-lite | bge-base | bm25 | vector | sparse | none | 5 | - | 2 | 30 | 30 | 53.6 | 102.6 | 376.9 | 72.6 | 49.2 | 486.4 | 0 | False | - |
| milvus-lite | bge-base | bm25 | vector | sparse | none | 20 | - | 2 | 30 | 30 | 57.8 | 137.1 | 145.3 | 67.5 | 51.7 | 145.8 | 0 | True | 9 |
| milvus-lite | bge-base | bm25 | vector | hybrid | none | 5 | - | 2 | 30 | 30 | 128.7 | 159.0 | 288.9 | 137.6 | 124.1 | 335.8 | 0 | False | - |
| milvus-lite | bge-base | bm25 | vector | hybrid | none | 20 | - | 2 | 30 | 30 | 133.4 | 250.1 | 3847.4 | 314.5 | 123.0 | 5296.6 | 0 | True | 8 |
| milvus-lite | bge-m3 | bm25 | vector | dense | none | 5 | - | 2 | 30 | 30 | 79.7 | 184.8 | 219.1 | 95.0 | 74.3 | 223.1 | 0 | False | - |
| milvus-lite | bge-m3 | bm25 | vector | dense | none | 20 | - | 2 | 30 | 30 | 85.6 | 106.2 | 112.2 | 87.7 | 78.9 | 113.3 | 0 | True | 6 |
| milvus-lite | bge-m3 | bm25 | vector | sparse | none | 5 | - | 2 | 30 | 30 | 49.6 | 56.4 | 66.4 | 50.8 | 46.1 | 70.0 | 0 | False | - |
| milvus-lite | bge-m3 | bm25 | vector | sparse | none | 20 | - | 2 | 30 | 30 | 52.7 | 86.2 | 166.2 | 60.4 | 49.0 | 195.3 | 0 | True | 9 |
| milvus-lite | bge-m3 | bm25 | vector | hybrid | none | 5 | - | 2 | 30 | 30 | 129.3 | 174.7 | 366.9 | 145.2 | 121.3 | 443.8 | 0 | False | - |
| milvus-lite | bge-m3 | bm25 | vector | hybrid | none | 20 | - | 2 | 30 | 30 | 142.0 | 246.0 | 273.3 | 156.8 | 129.6 | 281.5 | 0 | True | 8 |
