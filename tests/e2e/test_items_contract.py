"""HTTP contract of the Items API, end to end: HTTP -> function code -> DynamoDB on the emulator."""

import os

import boto3
import pytest

pytestmark = pytest.mark.emulator


def test_health_reports_implementation(api, impl):
    r = api.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "impl": impl}


def test_create_read_delete_roundtrip(api, new_id):
    created = api.post("/items", json={"id": new_id, "name": "roundtrip"})
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "roundtrip"

    got = api.get(f"/items/{new_id}")
    assert got.status_code == 200
    assert got.json() == created.json()

    assert new_id in {i["id"] for i in api.get("/items").json()["items"]}

    assert api.delete(f"/items/{new_id}").status_code == 204
    assert api.get(f"/items/{new_id}").status_code == 404


def test_item_is_really_in_dynamodb(api, new_id):
    """The write must land in the emulator's DynamoDB, not in some in-process cache."""
    assert api.post("/items", json={"id": new_id, "name": "persisted"}).status_code == 201
    item = boto3.client("dynamodb").get_item(TableName=os.environ["TABLE_NAME"], Key={"id": {"S": new_id}})
    assert item["Item"]["name"] == {"S": "persisted"}


def test_duplicate_id_conflicts(api, new_id):
    assert api.post("/items", json={"id": new_id, "name": "a"}).status_code == 201
    r = api.post("/items", json={"id": new_id, "name": "b"})
    assert r.status_code == 409
    assert api.get(f"/items/{new_id}").json()["name"] == "a"


@pytest.mark.parametrize(
    "payload",
    [{"name": ""}, {"id": "not valid!", "name": "x"}, {"name": "x" * 101}, ["not", "an", "object"]],
    ids=["empty-name", "invalid-id", "name-too-long", "not-an-object"],
)
def test_validation_errors(api, payload):
    r = api.post("/items", json=payload)
    assert r.status_code == 400
    assert "error" in r.json()


def test_invalid_json(api):
    r = api.post("/items", content=b"{broken", headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_missing_item_and_unknown_route(api):
    assert api.get("/items/does-not-exist").status_code == 404
    assert api.delete("/items/does-not-exist").status_code == 404
    assert api.get("/nope").status_code == 404
    assert api.put("/items").status_code == 405
