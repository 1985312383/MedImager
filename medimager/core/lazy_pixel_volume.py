"""Memory-bounded, frame-addressable pixel storage for DICOM series.

The viewer only needs one (or a handful of) frames at a time.  Keeping this
small sequence-like object in the model avoids retaining every Dataset's
``PixelData`` and a second, float32 copy of the complete volume.
"""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from threading import RLock
from typing import Callable, Iterable, Iterator, Optional, Union

import numpy as np


Index = Union[int, slice, tuple]


class LazyPixelVolume:
    """A NumPy-compatible, lazily decoded stack with a byte-bounded LRU.

    Integer indexing decodes one frame.  Slice/advanced access and explicit
    ``np.asarray(volume)`` remain available for compatibility, but may
    materialise multiple frames and should therefore be reserved for export or
    tests rather than the interactive display path.
    """

    def __init__(
        self,
        frame_count: int,
        decoder: Callable[[int], np.ndarray],
        *,
        cache_limit_bytes: int = 128 * 1024 * 1024,
        prefetch_radius: int = 2,
    ) -> None:
        if frame_count <= 0:
            raise ValueError("frame_count must be positive")
        self._frame_count = int(frame_count)
        self._decoder = decoder
        self._cache_limit_bytes = max(1, int(cache_limit_bytes))
        self._prefetch_radius = max(0, int(prefetch_radius))
        self._cache: "OrderedDict[int, np.ndarray]" = OrderedDict()
        self._cache_bytes = 0
        self._lock = RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="medimager-dicom-prefetch",
        )
        self._prefetch_futures: dict[int, Future] = {}
        self._closed = False

        first = self._decode_and_cache(0)
        self._frame_shape = tuple(first.shape)
        self._dtype = first.dtype

    @property
    def shape(self) -> tuple[int, ...]:
        return (self._frame_count, *self._frame_shape)

    @property
    def ndim(self) -> int:
        return 1 + len(self._frame_shape)

    @property
    def dtype(self) -> np.dtype:
        return np.dtype(self._dtype)

    @property
    def size(self) -> int:
        return int(np.prod(self.shape, dtype=np.int64))

    @property
    def nbytes(self) -> int:
        """Logical decoded size; actual resident bytes are ``cache_bytes``."""
        return self.size * self.dtype.itemsize

    @property
    def cache_bytes(self) -> int:
        with self._lock:
            return self._cache_bytes

    @property
    def cache_limit_bytes(self) -> int:
        return self._cache_limit_bytes

    def __len__(self) -> int:
        return self._frame_count

    def __iter__(self) -> Iterator[np.ndarray]:
        for index in range(self._frame_count):
            yield self[index]

    def __getitem__(self, index: Index):
        if isinstance(index, tuple):
            if not index:
                return self
            head, *tail = index
            selected = self[head]
            return selected[tuple(tail)] if tail else selected

        if isinstance(index, slice):
            indices = range(*index.indices(self._frame_count))
            frames = [self._get_frame(i, schedule_prefetch=False) for i in indices]
            if not frames:
                return np.empty((0, *self._frame_shape), dtype=self._dtype)
            return np.stack(frames, axis=0)

        if isinstance(index, (int, np.integer)):
            normalized = int(index)
            if normalized < 0:
                normalized += self._frame_count
            if not 0 <= normalized < self._frame_count:
                raise IndexError("frame index out of range")
            return self._get_frame(normalized, schedule_prefetch=True)

        # NumPy-style advanced indexing is intentionally compatible, while
        # making the materialisation explicit in this uncommon path.
        return np.asarray(self)[index]

    def __array__(self, dtype=None, copy=None) -> np.ndarray:
        frames = [
            self._get_frame(i, schedule_prefetch=False)
            for i in range(self._frame_count)
        ]
        result = np.stack(frames, axis=0)
        if dtype is not None:
            result = result.astype(dtype, copy=False)
        if copy:
            result = result.copy()
        return result

    def _get_frame(self, index: int, *, schedule_prefetch: bool) -> np.ndarray:
        with self._lock:
            cached = self._cache.get(index)
            if cached is not None:
                self._cache.move_to_end(index)
                result = cached
            else:
                result = None

        if result is None:
            future = None
            with self._lock:
                future = self._prefetch_futures.pop(index, None)
            if future is not None:
                try:
                    result = future.result()
                except Exception:
                    result = None
            if result is None:
                result = self._decode_and_cache(index)

        if schedule_prefetch:
            self.prefetch_neighbours(index)
        return result

    def _decode_and_cache(self, index: int) -> np.ndarray:
        frame = np.asarray(self._decoder(index))
        if frame.ndim < 2:
            raise ValueError(f"decoded DICOM frame {index} is not an image")
        if hasattr(self, "_frame_shape") and tuple(frame.shape) != self._frame_shape:
            raise ValueError(
                f"inconsistent DICOM frame shape {frame.shape}; expected {self._frame_shape}"
            )

        # Read-only frames prevent accidental edits of cache entries shared by
        # several views.  Annotation data lives separately from source pixels.
        try:
            frame.setflags(write=False)
        except ValueError:
            pass

        with self._lock:
            existing = self._cache.pop(index, None)
            if existing is not None:
                self._cache_bytes -= int(existing.nbytes)
            self._cache[index] = frame
            self._cache_bytes += int(frame.nbytes)
            self._evict_locked(protected=index)
        return frame

    def _evict_locked(self, *, protected: Optional[int] = None) -> None:
        while self._cache_bytes > self._cache_limit_bytes and len(self._cache) > 1:
            candidate, value = next(iter(self._cache.items()))
            if candidate == protected:
                self._cache.move_to_end(candidate)
                continue
            self._cache.pop(candidate)
            self._cache_bytes -= int(value.nbytes)

    def prefetch_neighbours(self, index: int) -> None:
        if self._prefetch_radius <= 0 or self._closed:
            return
        neighbours: list[int] = []
        for distance in range(1, self._prefetch_radius + 1):
            neighbours.extend((index + distance, index - distance))
        self.prefetch(neighbours)

    def prefetch(self, indices: Iterable[int]) -> None:
        if self._closed:
            return
        with self._lock:
            for index in indices:
                index = int(index)
                if not 0 <= index < self._frame_count:
                    continue
                if index in self._cache or index in self._prefetch_futures:
                    continue
                future = self._executor.submit(self._decode_and_cache, index)
                self._prefetch_futures[index] = future

                def _forget(_future: Future, frame_index: int = index) -> None:
                    with self._lock:
                        if self._prefetch_futures.get(frame_index) is _future:
                            self._prefetch_futures.pop(frame_index, None)

                future.add_done_callback(_forget)

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()
            self._cache_bytes = 0

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with self._lock:
            futures = list(self._prefetch_futures.values())
            self._prefetch_futures.clear()
        for future in futures:
            future.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def __del__(
        self,
    ) -> None:  # pragma: no cover - interpreter shutdown is nondeterministic
        try:
            self.close()
        except Exception:
            pass
