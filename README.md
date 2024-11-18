# universal-cache
Lightweight and yet powerful way to cache and invalidate caches for anything in Python

Requirements: redis, pottery

Example usage located in `__init__.py`:

```python
import typing as t

from src.caches import cache


@cache(prefix="some_prefix.some_func", timeout=60 * 60 * 24)
def some_func(*args, **kwargs) -> t.Any:
    return "something"


@cache(prefix="some_prefix.some_view", timeout=60 * 60 * 2, is_response_method=True)
def some_view(*args, **kwargs) -> t.Any:
    return "response"


@cache(prefix="some_prefix.some_method", timeout=60 * 60 * 2, is_class_method=True)
def some_method(*args, **kwargs) -> t.Any:
    return "something from class"
```
