// Unit tests: the real HTTP handler on an ephemeral port with an in-memory repository.
import { after, before, beforeEach, describe, test } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { ConflictError, NotFoundError, createRequestHandler, validateNewItem } from "../src/app.js";

function memoryRepo() {
  const items = new Map();
  return {
    items,
    async create(item) {
      if (items.has(item.id)) throw new ConflictError(item.id);
      items.set(item.id, item);
    },
    async get(id) {
      return items.get(id) ?? null;
    },
    async list() {
      return [...items.values()];
    },
    async remove(id) {
      if (!items.delete(id)) throw new NotFoundError(id);
    },
  };
}

describe("items API (web function)", () => {
  let server;
  let base;
  let repo;

  before(async () => {
    repo = memoryRepo();
    const handler = createRequestHandler({ repo, now: () => new Date("2026-01-01T00:00:00Z") });
    server = http.createServer(handler);
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    base = `http://127.0.0.1:${server.address().port}`;
  });
  after(() => server.close());
  beforeEach(() => repo.items.clear());

  const post = (body) =>
    fetch(`${base}/items`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: typeof body === "string" ? body : JSON.stringify(body),
    });

  test("GET /health reports the implementation", async () => {
    const r = await fetch(`${base}/health`);
    assert.equal(r.status, 200);
    assert.deepEqual(await r.json(), { status: "ok", impl: "web-function" });
  });

  test("POST /items creates an item with a generated id", async () => {
    const r = await post({ name: "  first  " });
    assert.equal(r.status, 201);
    const item = await r.json();
    assert.equal(item.name, "first");
    assert.equal(item.createdAt, "2026-01-01T00:00:00.000Z");
    assert.match(item.id, /^[0-9a-f-]{36}$/);
  });

  test("POST /items with an existing id returns 409", async () => {
    assert.equal((await post({ id: "dup", name: "a" })).status, 201);
    assert.equal((await post({ id: "dup", name: "b" })).status, 409);
  });

  test("POST /items rejects invalid JSON and invalid fields", async () => {
    assert.equal((await post("{not json")).status, 400);
    assert.equal((await post({ name: "" })).status, 400);
    assert.equal((await post({ id: "bad id!", name: "x" })).status, 400);
    assert.equal((await post([1, 2])).status, 400);
  });

  test("GET, list and DELETE an item", async () => {
    await post({ id: "abc", name: "x" });
    assert.equal((await fetch(`${base}/items/abc`)).status, 200);
    assert.equal((await (await fetch(`${base}/items`)).json()).items.length, 1);
    assert.equal((await fetch(`${base}/items/abc`, { method: "DELETE" })).status, 204);
    assert.equal((await fetch(`${base}/items/abc`)).status, 404);
    assert.equal((await fetch(`${base}/items/abc`, { method: "DELETE" })).status, 404);
  });

  test("unknown routes and methods", async () => {
    assert.equal((await fetch(`${base}/nope`)).status, 404);
    assert.equal((await fetch(`${base}/items`, { method: "PUT" })).status, 405);
  });
});

test("validateNewItem keeps a valid client id", () => {
  assert.deepEqual(validateNewItem({ id: "a_b-1", name: "n" }), { id: "a_b-1", name: "n" });
});
