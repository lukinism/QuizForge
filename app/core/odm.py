from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any, TypeVar

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pydantic import BaseModel, ConfigDict, Field
from pymongo.errors import OperationFailure


PydanticObjectId = str
DocumentT = TypeVar("DocumentT", bound="Document")
_database: AsyncIOMotorDatabase | None = None


@dataclass(frozen=True)
class IndexMetadata:
    unique: bool = False


def Indexed(annotation: Any, unique: bool = False) -> Any:
    return Annotated[annotation, IndexMetadata(unique=unique)]


def generate_object_id() -> str:
    return str(ObjectId())


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return {key: _normalize_value(item) for key, item in value.model_dump(mode="python").items()}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_value(item) for key, item in value.items()}
    return value


class QueryExpression:
    def __init__(self, field_name: str, operator: str, value: Any):
        self.field_name = field_name
        self.operator = operator
        self.value = value


class QueryField:
    def __init__(self, field_name: str):
        self.field_name = field_name

    def __eq__(self, other: Any) -> QueryExpression:  # type: ignore[override]
        return QueryExpression(self.field_name, "$eq", other)


class DocumentMeta(type(BaseModel)):
    def __getattr__(cls, item: str) -> QueryField:
        pydantic_fields = cls.__dict__.get("__pydantic_fields__", {})
        if item in pydantic_fields:
            return QueryField(item)
        raise AttributeError(item)


class QuerySet:
    def __init__(self, model_cls: type[Document], conditions: tuple[Any, ...]):
        self.model_cls = model_cls
        self.query = self._compile_query(conditions)
        self.sort_spec: list[tuple[str, int]] = []

    @staticmethod
    def _mongo_key(key: str) -> str:
        return "_id" if key == "id" else key

    def _compile_query(self, conditions: tuple[Any, ...]) -> dict[str, Any]:
        query: dict[str, Any] = {}
        for condition in conditions:
            if isinstance(condition, QueryExpression):
                mongo_key = self._mongo_key(condition.field_name)
                if condition.operator != "$eq":
                    raise NotImplementedError(f"Unsupported operator: {condition.operator}")
                query[mongo_key] = _normalize_value(condition.value)
                continue

            if isinstance(condition, dict):
                for key, value in condition.items():
                    mongo_key = self._mongo_key(key)
                    normalized_value = _normalize_value(value)
                    if (
                        mongo_key in query
                        and isinstance(query[mongo_key], dict)
                        and isinstance(normalized_value, dict)
                    ):
                        query[mongo_key].update(normalized_value)
                    else:
                        query[mongo_key] = normalized_value
                continue

            raise TypeError(f"Unsupported query condition: {condition!r}")
        return query

    def sort(self, *fields: str) -> "QuerySet":
        self.sort_spec = []
        for field in fields:
            direction = -1 if field.startswith("-") else 1
            field_name = field[1:] if field.startswith("-") else field
            self.sort_spec.append((self._mongo_key(field_name), direction))
        return self

    def _cursor(self):
        cursor = self.model_cls.get_collection().find(self.query)
        if self.sort_spec:
            cursor = cursor.sort(self.sort_spec)
        return cursor

    async def to_list(self) -> list[Document]:
        documents = await self._cursor().to_list(length=None)
        return [self.model_cls.from_mongo(document) for document in documents]

    async def count(self) -> int:
        return await self.model_cls.get_collection().count_documents(self.query)

    async def delete(self) -> int:
        result = await self.model_cls.get_collection().delete_many(self.query)
        return result.deleted_count


class Document(BaseModel, metaclass=DocumentMeta):
    id: PydanticObjectId = Field(default_factory=generate_object_id)

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="ignore",
        populate_by_name=True,
        validate_assignment=True,
    )

    @classmethod
    def collection_name(cls) -> str:
        settings = getattr(cls, "Settings", None)
        explicit_name = getattr(settings, "name", None)
        if explicit_name:
            return explicit_name
        return f"{cls.__name__.lower()}s"

    @classmethod
    def get_collection(cls) -> AsyncIOMotorCollection:
        if _database is None:
            raise RuntimeError("MongoDB database is not initialized")
        return _database[cls.collection_name()]

    @classmethod
    def from_mongo(cls: type[DocumentT], document: dict[str, Any]) -> DocumentT:
        payload = dict(document)
        payload["id"] = str(payload.pop("_id"))
        return cls.model_validate(payload)

    def to_mongo(self) -> dict[str, Any]:
        payload = _normalize_value(self.model_dump(mode="python"))
        payload["_id"] = payload.pop("id")
        return payload

    @classmethod
    async def get(cls: type[DocumentT], document_id: PydanticObjectId) -> DocumentT | None:
        document = await cls.get_collection().find_one({"_id": str(document_id)})
        return cls.from_mongo(document) if document else None

    @classmethod
    def find(cls, *conditions: Any) -> QuerySet:
        return QuerySet(cls, conditions)

    @classmethod
    async def find_one(cls: type[DocumentT], *conditions: Any) -> DocumentT | None:
        query = QuerySet(cls, conditions).query
        document = await cls.get_collection().find_one(query)
        return cls.from_mongo(document) if document else None

    @classmethod
    def find_all(cls) -> QuerySet:
        return QuerySet(cls, ())

    async def insert(self: DocumentT) -> DocumentT:
        await self.get_collection().insert_one(self.to_mongo())
        return self

    async def save(self: DocumentT) -> DocumentT:
        await self.get_collection().replace_one({"_id": self.id}, self.to_mongo(), upsert=True)
        return self

    async def delete(self) -> None:
        await self.get_collection().delete_one({"_id": self.id})


def _index_name_for_field(field_name: str) -> str:
    return f"{field_name}_1"


async def _ensure_single_field_index(
    collection: AsyncIOMotorCollection,
    field_name: str,
    *,
    unique: bool = False,
) -> None:
    desired_name = _index_name_for_field(field_name)
    desired_key = [(field_name, 1)]
    existing_indexes = await collection.index_information()

    for existing_name, existing_spec in existing_indexes.items():
        if existing_name == "_id_":
            continue

        existing_key = list(existing_spec.get("key", []))
        existing_unique = existing_spec.get("unique", False)

        if existing_key == desired_key and existing_unique == unique:
            return

        if existing_name == desired_name or existing_key == desired_key:
            await collection.drop_index(existing_name)

    try:
        await collection.create_index(field_name, unique=unique, name=desired_name)
    except OperationFailure as exc:
        if unique and exc.code == 11000:
            raise RuntimeError(
                f"Cannot create unique index for '{collection.name}.{field_name}'. "
                "Duplicate values already exist in this collection."
            ) from exc
        raise


async def init_odm(
    database: AsyncIOMotorDatabase,
    document_models: list[type[Document]] | tuple[type[Document], ...],
) -> None:
    global _database
    _database = database

    for model in document_models:
        collection = model.get_collection()

        settings = getattr(model, "Settings", None)
        for index_name in getattr(settings, "indexes", []):
            if isinstance(index_name, str):
                await _ensure_single_field_index(collection, index_name, unique=False)

        for field_name, field_info in model.model_fields.items():
            for metadata in field_info.metadata:
                if isinstance(metadata, IndexMetadata):
                    await _ensure_single_field_index(
                        collection,
                        field_name,
                        unique=metadata.unique,
                    )


def reset_odm() -> None:
    global _database
    _database = None
