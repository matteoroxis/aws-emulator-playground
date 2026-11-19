"""Items API as a classic (Event) Lambda behind a Function URL (payload format 2.0).

Same HTTP contract as functions/web. Routing is a pure function over (method, path, body, repo),
so unit tests run it with an in-memory repository.
"""

from __future__ import annotations

import base64
import json
import os
import re
import uuid
from datetime import UTC, datetime

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ITEM_PATH = re.compile(r"^/items/([^/]+)$")
# AWS Emulator serves Function URLs under /_aws/lambda-url/<id>/ and leaves that prefix in rawPath.
# On AWS the URL has its own domain and rawPath never contains it, so stripping it is a no-op there.
# Tracked as a known gap in tools/capability_gate.py: remove this when the gate reports it closed.
EMULATOR_URL_PREFIX = re.compile(r"^/_aws/lambda-url/[^/]+")
MAX_BODY_BYTES = 64 * 1024
IMPL = "event-function"


class ConflictError(Exception):
    pass


class NotFoundError(Exception):
    pass


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def validate_new_item(body) -> dict:
    if not isinstance(body, dict):
        raise HttpError(400, "body must be a JSON object")
    name = body.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise HttpError(400, "name must be a non-empty string of at most 100 characters")
    item_id = body.get("id")
    if item_id is not None and (not isinstance(item_id, str) or not ID_PATTERN.match(item_id)):
        raise HttpError(400, "id must match [A-Za-z0-9_-]{1,64}")
    return {"id": item_id or str(uuid.uuid4()), "name": name.strip()}


def _parse_json(raw: str | None):
    if raw is not None and len(raw.encode()) > MAX_BODY_BYTES:
        raise HttpError(413, "body too large")
    try:
        return json.loads(raw or "")
    except json.JSONDecodeError as exc:
        raise HttpError(400, "body must be valid JSON") from exc


def route(method: str, path: str, raw_body: str | None, repo, now=lambda: datetime.now(UTC)):
    """Returns (status, payload_or_None)."""
    path = path.rstrip("/") or "/"
    try:
        if path == "/health":
            if method != "GET":
                raise HttpError(405, "method not allowed")
            return 200, {"status": "ok", "impl": IMPL}

        if path == "/items":
            if method == "GET":
                return 200, {"items": repo.list()}
            if method == "POST":
                fields = validate_new_item(_parse_json(raw_body))
                item = {**fields, "createdAt": now().isoformat(timespec="milliseconds").replace("+00:00", "Z")}
                try:
                    repo.create(item)
                except ConflictError as exc:
                    raise HttpError(409, f"item {item['id']} already exists") from exc
                return 201, item
            raise HttpError(405, "method not allowed")

        match = ITEM_PATH.match(path)
        if match:
            item_id = match.group(1)
            if not ID_PATTERN.match(item_id):
                raise HttpError(400, "invalid id")
            if method == "GET":
                item = repo.get(item_id)
                if item is None:
                    raise HttpError(404, f"item {item_id} not found")
                return 200, item
            if method == "DELETE":
                try:
                    repo.remove(item_id)
                except NotFoundError as exc:
                    raise HttpError(404, f"item {item_id} not found") from exc
                return 204, None
            raise HttpError(405, "method not allowed")

        raise HttpError(404, "route not found")
    except HttpError as exc:
        return exc.status, {"error": str(exc)}


class DynamoRepo:
    def __init__(self, table_name: str, client=None):
        import boto3  # available in the Lambda Python runtime

        self._table = table_name
        self._ddb = client or boto3.client("dynamodb")

    @staticmethod
    def _to_item(raw: dict) -> dict:
        return {k: v["S"] for k, v in raw.items()}

    def create(self, item: dict) -> None:
        try:
            self._ddb.put_item(
                TableName=self._table,
                Item={k: {"S": v} for k, v in item.items()},
                ConditionExpression="attribute_not_exists(id)",
            )
        except self._ddb.exceptions.ConditionalCheckFailedException as exc:
            raise ConflictError(item["id"]) from exc

    def get(self, item_id: str):
        raw = self._ddb.get_item(TableName=self._table, Key={"id": {"S": item_id}}).get("Item")
        return self._to_item(raw) if raw else None

    def list(self) -> list:
        raw = self._ddb.scan(TableName=self._table, Limit=100).get("Items", [])
        return sorted((self._to_item(i) for i in raw), key=lambda i: i["createdAt"])

    def remove(self, item_id: str) -> None:
        try:
            self._ddb.delete_item(
                TableName=self._table,
                Key={"id": {"S": item_id}},
                ConditionExpression="attribute_exists(id)",
            )
        except self._ddb.exceptions.ConditionalCheckFailedException as exc:
            raise NotFoundError(item_id) from exc


_repo = None


def handler(event, context):
    global _repo
    if _repo is None:
        _repo = DynamoRepo(os.environ["TABLE_NAME"])
    body = event.get("body")
    if body is not None and event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = EMULATOR_URL_PREFIX.sub("", event.get("rawPath", "/")) or "/"
    status, payload = route(method, path, body, _repo)
    response = {"statusCode": status}
    if payload is not None:
        response["headers"] = {"content-type": "application/json"}
        response["body"] = json.dumps(payload)
    return response
