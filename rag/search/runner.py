from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar


T = TypeVar("T")


class SearchRunner:
    def run_common_and_scoped(
        self,
        common_fn: Callable[[], list[T]],
        scoped_fn: Callable[[], list[T]] | None = None,
    ) -> tuple[list[T], list[T]]:
        with ThreadPoolExecutor(max_workers=2) as executor:
            common_future = executor.submit(common_fn)
            scoped_future = executor.submit(scoped_fn) if scoped_fn is not None else None

            common_items = common_future.result()
            scoped_items = scoped_future.result() if scoped_future is not None else []
            if scoped_items is None:
                scoped_items = []
        return common_items, scoped_items

    def run_dense_and_sparse(
        self,
        dense_fn: Callable[[], list[T]],
        sparse_fn: Callable[[], list[T]],
    ) -> tuple[list[T], list[T]]:
        with ThreadPoolExecutor(max_workers=2) as executor:
            dense_future = executor.submit(dense_fn)
            sparse_future = executor.submit(sparse_fn)

            dense_items = dense_future.result()
            sparse_items = sparse_future.result()
        return dense_items, sparse_items
