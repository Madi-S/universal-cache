import typing as t

from pydantic import BaseModel

from src.caches import cache, invalidate_cache


# --- Function example ---
@cache(prefix="some_function", timeout=60)
def func__get_something_useful(*args: tuple, **kwargs: dict) -> t.Any:
    return "something useful"


@cache(prefix="some_function", timeout=60)
def func__update_something_useful(*args: tuple, **kwargs: dict) -> t.Any:
    return "updated"


# --- View example ---
@cache(prefix="some_view", timeout=60 * 15, is_response_method=True)
def view__get_user(*args: tuple, **kwargs: dict) -> BaseModel: ...


@invalidate_cache(prefix="some_view", is_response_method=True)
def view__update_user(*args: tuple, **kwargs: dict) -> None: ...


# --- Class method example ---
class SomeClass:
    _size: int

    def __init__(self):
        self._size: int = 20

    @cache(prefix="some_method", timeout=60 * 25, is_class_method=True)
    def method__get_size(self) -> int:
        return self._size

    @invalidate_cache(prefix="some_method", is_class_method=True)
    def method__update_size(self, size: int) -> None:
        self._size = size
