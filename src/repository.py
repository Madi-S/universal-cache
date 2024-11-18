import datetime
import json
import typing as t
import uuid

from pydantic import BaseModel
from redis import Redis

from src.utils import Serializer

_T = t.TypeVar("_T", bound=BaseModel)
_TWO_WEEKS = datetime.timedelta(weeks=2)


class RedisRepository(Serializer):
    """
    Base class for redis object repository.

    :param redis_client: Redis client
    :param prefix: Redis key prefix for every key. If None then name of object (_T)
                   treated as prefix.
    """

    _redis_client: "Redis[str]"
    _prefix: str

    def __init__(
        self,
        redis_client: "Redis[str]",
        prefix: str = "",
    ) -> None:
        """
        Init method sets redis client and extracts object type from
        typing annotation.
        """
        self._redis_client = redis_client
        self._prefix = prefix

    def _deserialize(self, encoded_value: t.Union[str, bytes]) -> t.Any:
        if isinstance(encoded_value, bytes):
            string = encoded_value.decode()
        else:
            string = encoded_value

        decoded_value = json.loads(string)
        return decoded_value

    def save(
        self,
        key: t.Union[str, uuid.UUID],
        obj: t.Any,
        ex: t.Optional[datetime.timedelta] = _TWO_WEEKS,
    ) -> None:
        """
        Saves object in redis with passed key

        :param key: Object key
        :param obj: Object to be saved
        :param ex: Expiration timedelta
        """
        r_key = self._prefix + str(key)
        r_value = self._serialize(obj)

        self._redis_client.set(r_key, r_value, ex=ex)

    def save_with_intermediate(
        self,
        keys: t.List[t.Union[str, uuid.UUID]],
        obj: _T,
        ex: t.Optional[datetime.timedelta] = _TWO_WEEKS,
    ) -> None:
        """
        Saves object in redis with passed key with assumption of
        intermediate relation e.g.: key[i] -> intermediate -> object

        :param keys: List of keys for object
        :param obj: Object to be saved
        :param ex: Expiration timedelta
        """
        r_keys = [self._prefix + str(key) for key in keys]
        intermediate = str(uuid.uuid4())
        r_value = self._serialize(obj)

        pipe = self._redis_client.pipeline()
        for r_key in r_keys:
            pipe.set(r_key, intermediate, ex=ex)

        pipe.set(intermediate, r_value, ex=ex)
        pipe.execute()

    def get(self, key: t.Union[str, uuid.UUID]) -> t.Optional[t.Any]:
        """
        Extracting object from redis db

        :param key: Object key
        :return: Object instance or None if object with such key does not exists
        """

        r_key = self._prefix + str(key)
        json_obj = self._redis_client.get(r_key)
        if json_obj is None:
            return None

        r_value = self._deserialize(json_obj)
        return r_value

    def get_with_intermediate(self, key: t.Union[str, uuid.UUID]) -> t.Optional[t.Any]:
        """
        Extracting object from redis db with assumption of
        intermediate relation e.g.: key[i] -> intermediate -> object

        :param key: Object key
        :return: Object instance or None if object with such key does not exists
        """

        r_key = self._prefix + str(key)
        # receive intermediate key
        intermediate = self._redis_client.get(r_key)
        if intermediate is None:
            return None
        # receive object
        json_obj = self._redis_client.get(intermediate)
        if json_obj is None:
            return None

        return self._deserialize(json_obj)

    def delete(self, key: t.Union[str, uuid.UUID]) -> None:
        """
        Delete object from redis db

        :param key: Object key
        """

        r_key = self._prefix + str(key)
        self._redis_client.delete(r_key)

    def delete_with_intermediate(self, *keys: t.Union[str, uuid.UUID]) -> None:
        """
        Delete object from redis db with assumption of
        intermediate relation e.g.: key[i] -> intermediate -> object

        :param keys: Object keys
        """
        r_keys = [self._prefix + str(key) for key in keys]

        intermediate = self._redis_client.get(r_keys[0])

        pipe = self._redis_client.pipeline()
        for r_key in r_keys:
            pipe.delete(r_key)
        if intermediate:
            pipe.delete(intermediate)

        pipe.execute()

    def exists(self, key: t.Union[str, uuid.UUID]) -> bool:
        """
        Check whether particular key exists or not

        :param key: Object key
        :return: True if occupied else False
        """
        r_key = self._prefix + str(key)
        return bool(self._redis_client.exists(r_key))

    def expire(self, key: t.Union[str, uuid.UUID], ex: datetime.timedelta) -> None:
        r_key = self._prefix + str(key)
        self._redis_client.expire(r_key, time=ex)

    def __getitem__(self, key: t.Union[str, uuid.UUID]) -> t.Optional[t.Any]:
        return self.get(key)

    def __setitem__(self, key: t.Union[str, uuid.UUID], value: t.Any) -> None:
        self.save(key, value)


class PydanticRedisRepository(RedisRepository, t.Generic[_T]):
    def __init__(
        self,
        redis_client: "Redis[str]",
        prefix: t.Optional[str] = None,
        obj_type: t.Optional[_T] = None,
    ) -> None:
        """
        Init method sets redis client and extracts object type from
        typing annotation.
        """
        if obj_type is None:
            self.obj_type = t.get_args(self.__orig_bases__[0])[0]  # type: ignore
        else:
            self.obj_type = obj_type

        super(PydanticRedisRepository, self).__init__(
            redis_client=redis_client,
            prefix=prefix or self.obj_type.__name__ + "_",
        )

    def _serialize(self, obj: _T) -> str:
        return obj.json()

    def _deserialize(self, encoded_value: t.Union[str, bytes]) -> _T:
        if self.obj_type is None:
            raise Exception("Object type cannot be None for PydanticRedisRepository")

        return t.cast(_T, self.obj_type.parse_raw(encoded_value))

    def get(self, key: t.Union[str, uuid.UUID]) -> t.Optional[_T]:
        return t.cast(_T, super().get(key))

    def get_with_intermediate(self, key: t.Union[str, uuid.UUID]) -> t.Optional[_T]:
        return t.cast(_T, super().get_with_intermediate(key))

    def __getitem__(self, key: t.Union[str, uuid.UUID]) -> t.Optional[_T]:
        return t.cast(_T, self.get(key))
