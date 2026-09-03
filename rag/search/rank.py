from __future__ import annotations


def weighted_reciprocal_rank(weighted_parts, limit: int, rrf_k: int) -> list[dict]:
    by_id: dict[str, dict] = {}
    scores: dict[str, float] = {}
    for weight, items in weighted_parts:
        for rank, item in enumerate(items, start=1):
            item_id = item["id"]
            by_id.setdefault(item_id, item)
            scores[item_id] = scores.get(item_id, 0.0) + weight / (rrf_k + rank)
    fused = []
    for item_id, score in scores.items():
        item = dict(by_id[item_id])
        item["_score"] = score
        fused.append(item)
    fused.sort(key=lambda item: item["_score"], reverse=True)
    return fused[:limit]
