# universal-cache

Lightweight and yet powerful way to cache and invalidate caches for anything in Python.

Works perfectly fine with any web frameworks (django, fastapi, blacksheep, flask ...), regular functions and class methods.

"HOWTO" is pretty self-explanatory, but for any struggles or misunderstandings free to open issues or discussions.

<b>TODO</b>:

    - `async` support

    - create `requirements.txt` :D

Example usage located in `__init__.py`:

```python
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

```

If you are unsure that the object your function returns is cacheable, have a look at `src.utils.Serializer` and add a method to your object that is called `to_json` that should probably return a dict xD, which makes your object "json dumpable".

Generally, there is no need to define `from_json` method for that class, because usually if it is json convertible, then it can be converted back to python object a.k.a "json loadable"
