"""Unit tests for the Event Function routing, with an in-memory repository."""

import base64
import json
from datetime import UTC, datetime

import items_api
import pytest
from items_api import ConflictError, NotFoundError, route

FIXED_NOW = lambda: datetime(2026, 1, 1, tzinfo=UTC)  # noqa: E731


class MemoryRepo:
    def __init__(self):
        self.items = {}

    def create(self, item):
        if item["id"] in self.items:
            raise ConflictError(item["id"])
        self.items[item["id"]] = item

    def get(self, item_id):
        return self.items.get(item_id)

    def list(self):
        return list(self.items.values())

    def remove(self, item_id):
        if self.items.pop(item_id, None) is None:
            raise NotFoundError(item_id)


@pytest.fixture
def repo():
    return MemoryRepo()


def test_health(repo):
    assert route("GET", "/health", None, repo) == (200, {"status": "ok", "impl": "event-function"})


def test_create_generates_id_and_timestamp(repo):
    status, item = route("POST", "/items", json.dumps({"name": " first "}), repo, now=FIXED_NOW)
    assert status == 201
    assert item["name"] == "first"
    assert item["createdAt"] == "2026-01-01T00:00:00.000Z"
    assert len(item["id"]) == 36


def test_create_duplicate_id_is_409(repo):
    body = json.dumps({"id": "dup", "name": "a"})
    assert route("POST", "/items", body, repo)[0] == 201
    assert route("POST", "/items", body, repo)[0] == 409


@pytest.mark.parametrize(
    "body",
    ["{not json", json.dumps({"name": ""}), json.dumps({"id": "bad id!", "name": "x"}), json.dumps([1]), None],
)
def test_create_rejects_bad_input(repo, body):
    assert route("POST", "/items", body, repo)[0] == 400


def test_get_list_delete(repo):
    route("POST", "/items", json.dumps({"id": "abc", "name": "x"}), repo)
    assert route("GET", "/items/abc", None, repo)[0] == 200
    assert len(route("GET", "/items", None, repo)[1]["items"]) == 1
    assert route("DELETE", "/items/abc", None, repo) == (204, None)
    assert route("GET", "/items/abc", None, repo)[0] == 404
    assert route("DELETE", "/items/abc", None, repo)[0] == 404


def test_unknown_route_and_method(repo):
    assert route("GET", "/nope", None, repo)[0] == 404
    assert route("PUT", "/items", None, repo)[0] == 405


def test_handler_decodes_function_url_event(repo, monkeypatch):
    monkeypatch.setattr(items_api, "_repo", repo)
    event = {
        "version": "2.0",
        "rawPath": "/items",
        "requestContext": {"http": {"method": "POST"}},
        "isBase64Encoded": True,
        "body": base64.b64encode(json.dumps({"id": "b64", "name": "n"}).encode()).decode(),
    }
    resp = items_api.handler(event, None)
    assert resp["statusCode"] == 201
    assert resp["headers"]["content-type"] == "application/json"
    assert json.loads(resp["body"])["id"] == "b64"


@pytest.mark.parametrize(
    "raw_path", ["/health", "/_aws/lambda-url/0123abcd/health", "/_aws/lambda-url/0123abcd/health/"]
)
def test_handler_ignores_emulator_url_prefix(repo, monkeypatch, raw_path):
    monkeypatch.setattr(items_api, "_repo", repo)
    resp = items_api.handler({"rawPath": raw_path, "requestContext": {"http": {"method": "GET"}}}, None)
    assert resp["statusCode"] == 200


def test_handler_204_has_no_body(repo, monkeypatch):
    monkeypatch.setattr(items_api, "_repo", repo)
    repo.create({"id": "x", "name": "n", "createdAt": "t"})
    resp = items_api.handler({"rawPath": "/items/x", "requestContext": {"http": {"method": "DELETE"}}}, None)
    assert resp == {"statusCode": 204}
