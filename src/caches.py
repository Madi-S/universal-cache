# mypy: ignore-errors
import datetime
import functools
import os
import typing as t
import uuid
from inspect import isclass, signature

from pottery.cache import CacheInfo
from pydantic import BaseModel
from redis import Redis

from src.repository import PydanticRedisRepository, RedisRepository

# Default Redis connection settings
_default_url: t.Final[str] = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_default_redis: t.Final[Redis] = Redis.from_url(_default_url, socket_timeout=1)

# Type definition for JSON serializable values that can be cached
JSONTypes = t.Union[
    None, BaseModel, bool, int, float, str, t.List[t.Any], t.Dict[str, t.Any]
]
F = t.TypeVar("F", bound=t.Callable[..., JSONTypes])


class ResponseRepository(RedisRepository):
    """Repository for caching HTTP responses"""

    def _serialize(self, obj: t.Any) -> str:
        return obj.json()


def _arg_hash(*args: t.Hashable, **kwargs: t.Hashable) -> int:
    """
    Generate a hash from function arguments for cache key.
    Handles special case of Pydantic models by converting them to JSON first.
    """

    def make_hashable(el):
        if isinstance(el, BaseModel):
            return el.json()
        return el

    # Convert kwargs and args to frozenset for hashing
    kwargs_items = frozenset({(k, make_hashable(v)) for k, v in kwargs.items()})
    args = frozenset([make_hashable(el) for el in args])
    return hash((args, kwargs_items))


def random_key(
    *,
    redis: Redis,
    prefix: str = "investfuture:",
    num_tries: int = 3,
) -> str:
    """
    Generate a random Redis key that doesn't already exist.
    Uses UUID4 for uniqueness and retries if collision occurs.

    Args:
        redis: Redis connection
        prefix: Key prefix to use
        num_tries: Number of attempts to generate unique key
    """
    if not isinstance(num_tries, int):
        raise TypeError("num_tries must be an int >= 0")
    if num_tries < 0:
        raise ValueError("num_tries must be an int >= 0")
    if num_tries == 0:
        raise Exception(redis)

    uuid4 = str(uuid.uuid4())
    key = prefix + uuid4
    if redis.exists(key):  # Available since Redis 1.0.0
        key = random_key(
            redis=redis,
            prefix=prefix,
            num_tries=num_tries - 1,
        )
    return key


def cache(
    *,  # NoQA: C901
    is_class_method: bool = False,
    is_response_method: bool = False,
    redis: t.Optional[Redis] = None,
    prefix: t.Optional[str] = None,
    timeout: t.Optional[int] = 60,
    r_type: t.Optional[t.Any] = None,
) -> t.Callable[[F], F]:
    """Redis-backed caching decorator with an API like functools.lru_cache().

    Arguments to the original underlying function must be hashable, and return
    values from the function must be JSON serializable.

    @param is_class_method: Whether decorated function is a class method
    @param is_response_method: Whether decorated function returns HTTP responses
    @param redis: Redis connection to use, defaults to _default_redis
    @param prefix: Key prefix for Redis cache entries
    @param timeout: Cache TTL in seconds
    @param r_type: Expected return type of decorated function

    Additionally, this decorator provides the following functions:

    f.__wrapped__(*args, **kwargs)
        Access the original underlying function.  This is useful for
        introspection, for bypassing the cache, or for rewrapping the function
        with a different cache.

    f.__bypass__(*args, **kwargs)
        Force a cache reset for your args/kwargs.  Bypass the cache lookup,
        call the original underlying function, then cache the results for
        future calls to f(*args, **kwargs).

    f.cache_info()
        Return a NamedTuple showing hits, misses, maxsize, and currsize.  This
        information is helpful for measuring the effectiveness of the cache.

        Note that maxsize is always None, meaning that this cache is always
        unbounded.  maxsize is only included for compatibility with
        functools.lru_cache().

        While redis_cache() is thread-safe, also note that hits/misses only
        instrument your local process - not other processes, even if connected
        to the same Redis-backed redis_cache() key.  And in some cases,
        hits/misses may be incorrect in multiprocess/distributed applications.

        That said, currsize is always correct, even if other remote processes
        modify the same Redis-backed redis_cache() key.

    f.cache_clear()
        Clear/invalidate the entire cache (for all args/kwargs previously
        cached) for your function.

    In general, you should only use redis_cache() when you want to reuse
    previously computed values.  Accordingly, it doesn't make sense to cache
    functions with side-effects or impure functions such as time() or random().

    However, unlike functools.lru_cache(), redis_cache() reconstructs
    previously cached objects on each cache hit.  Therefore, you can use
    redis_cache() for a function that needs to create a distinct mutable object
    on each call.
    """

    def decorator(func: F) -> F:
        nonlocal prefix, redis, r_type

        # Use default Redis connection if none provided
        if redis is None:
            redis = _default_redis

        # Generate random prefix if none provided
        if prefix is None:
            prefix = random_key(redis=t.cast(Redis, redis))

        # Get return type from function signature if not specified
        if r_type is None:
            r_type = signature(func).return_annotation

        # Select appropriate repository based on return type
        if is_response_method:
            cache = ResponseRepository(redis_client=redis, prefix=prefix)
        elif isclass(r_type) and issubclass(r_type, BaseModel):
            cache = PydanticRedisRepository(
                redis_client=redis, prefix=prefix, obj_type=r_type
            )
        else:
            cache = RedisRepository(redis_client=redis, prefix=prefix)

        hits, misses = 0, 0
        expires_after = datetime.timedelta(seconds=timeout)

        @functools.wraps(func)
        def wrapper(*args: t.Hashable, **kwargs: t.Hashable) -> JSONTypes:
            """Main wrapper that handles cache lookup and storage"""
            nonlocal hits, misses

            # Generate cache key based on function type and arguments
            if is_class_method:
                hash_ = _arg_hash(*args[1:], **kwargs)  # Skip 'self'/'cls' arg
            elif is_response_method:
                request = args[0]
                user_id = str(request.auth.identity.id) if request.auth.identity else ""
                hash_ = _arg_hash(user_id, *args[1:], **kwargs)
            else:
                hash_ = _arg_hash(*args, **kwargs)

            # Try to get value from cache
            return_value = cache[hash_]
            if return_value is None:
                # Cache miss - call function and store result
                return_value = func(*args, **kwargs)
                cache.save(hash_, return_value, ex=expires_after)
                misses += 1
            else:
                hits += 1

            return return_value

        @functools.wraps(func)
        def bypass(*args: t.Hashable, **kwargs: t.Hashable) -> JSONTypes:
            """Force bypass cache and update stored value"""
            if is_class_method or is_response_method:
                hash_ = _arg_hash(*args[1:], **kwargs)
            else:
                hash_ = _arg_hash(*args, **kwargs)

            return_value = func(*args, **kwargs)
            cache.save(hash_, return_value, ex=expires_after)

            return return_value

        def cache_info() -> CacheInfo:
            """Return cache statistics"""
            return CacheInfo(
                hits=hits,
                misses=misses,
                maxsize=None,
                currsize=len(cache),
            )

        def clear_cache() -> None:
            """Clear all cached values"""
            nonlocal hits, misses
            t.cast(Redis, redis).unlink(t.cast(str, prefix))
            hits, misses = 0, 0

        def invalidate_cache(*args: t.Hashable) -> None:
            """Invalidate records by args"""
            nonlocal hits, misses
            hash_ = _arg_hash(*args)
            cache.delete(hash_)

        # Add helper methods to wrapper
        wrapper.__wrapped__ = func  # type: ignore
        wrapper.__bypass__ = bypass  # type: ignore
        wrapper.cache_info = cache_info  # type: ignore
        wrapper.clear_cache = clear_cache  # type: ignore
        wrapper.invalidate_cache = invalidate_cache  # type: ignore

        return t.cast(F, wrapper)

    return decorator


def invalidate_cache(
    *,  # NoQA: C901
    is_class_method: bool = False,
    is_response_method: bool = False,
    redis: t.Optional[Redis] = None,
    prefix: t.Optional[str] = None,
    r_type: t.Optional[t.Any] = None,
    key_args: t.Optional[t.List[str]] = None,
) -> t.Callable[[F], F]:
    """
    Decorator that invalidates cache entries in Redis when the decorated function is called.
    It takes named variables (key_args) of the function that it will use to compute the hash,
    similar to the 'cache' decorator.

    @param is_class_method: Whether decorated function is a class method
    @param is_response_method: Whether decorated function returns HTTP responses
    @param redis: Redis connection to use
    @param prefix: Redis key prefix to use
    @param r_type: Expected return type of the function
    @param key_args: List of argument names to use for computing the hash
    """

    def decorator(func: F) -> F:
        nonlocal prefix, redis, r_type

        # Use default Redis connection if none provided
        if redis is None:
            redis = _default_redis

        # Generate random prefix if none provided
        if prefix is None:
            prefix = random_key(redis=redis)

        # Get return type from function signature if not specified
        if r_type is None:
            r_type = signature(func).return_annotation

        # Select appropriate repository based on return type
        if is_response_method:
            cache = ResponseRepository(redis_client=redis, prefix=prefix)
        elif isclass(r_type) and issubclass(r_type, BaseModel):
            cache = PydanticRedisRepository(
                redis_client=redis, prefix=prefix, obj_type=r_type
            )
        else:
            cache = RedisRepository(redis_client=redis, prefix=prefix)

        @functools.wraps(func)
        def wrapper(*args: t.Any, **kwargs: t.Any) -> t.Any:
            # Bind arguments to function parameters
            bound_args = signature(func).bind(*args, **kwargs)
            bound_args.apply_defaults()

            # Get arguments to use for hash calculation
            if key_args is not None:
                hash_args = {k: bound_args.arguments[k] for k in key_args}
            else:
                # If keys were not provided take all arguments
                hash_args = bound_args.arguments

            args_to_hash = list(hash_args.values())

            # Skip first argument for methods
            if key_args is not None and (is_class_method or is_response_method):
                args_to_hash = args_to_hash[1:]

            # Call original function
            return_value = func(*args, **kwargs)

            # Calculate hash and invalidate cache entry
            hash_ = _arg_hash(*args_to_hash)
            cache.delete(hash_)

            return return_value

        return wrapper

    return decorator
