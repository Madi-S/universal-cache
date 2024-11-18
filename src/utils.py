import json
import typing as t


class JsonEncoder(json.JSONEncoder):
    # This `t.Any` is a kostyl', in reality it should return json serializable object
    def default(self, obj: t.Any) -> t.Any:
        return obj.to_json()


class Serializer:
    def _serialize(self, obj: t.Any) -> str:
        try:
            encoder = JsonEncoder if hasattr(obj, "to_json") else None
            return json.dumps(obj, sort_keys=True, cls=encoder)
        except TypeError:
            raise NotImplementedError(
                "Serialization for this object is not implemented, define `to_json` method for the object you want to cache (i.e. function result) or make sure it is JSON serializable"
            )
