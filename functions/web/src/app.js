// HTTP routing and validation for the Items API. No AWS code here: the repository is injected,
// so the same handler runs in unit tests (in-memory repo) and in the Web Function (DynamoDB repo).
import { randomUUID } from "node:crypto";

export class ConflictError extends Error {}
export class NotFoundError extends Error {}

const MAX_BODY_BYTES = 64 * 1024;
const ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;
const ITEM_PATH = /^\/items\/([^/]+)$/;

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export function validateNewItem(body) {
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    throw new HttpError(400, "body must be a JSON object");
  }
  const { id, name } = body;
  if (typeof name !== "string" || name.trim() === "" || name.length > 100) {
    throw new HttpError(400, "name must be a non-empty string of at most 100 characters");
  }
  if (id !== undefined && (typeof id !== "string" || !ID_PATTERN.test(id))) {
    throw new HttpError(400, "id must match [A-Za-z0-9_-]{1,64}");
  }
  return { id: id ?? randomUUID(), name: name.trim() };
}

async function readJson(req) {
  let size = 0;
  const chunks = [];
  for await (const chunk of req) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) throw new HttpError(413, "body too large");
    chunks.push(chunk);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new HttpError(400, "body must be valid JSON");
  }
}

function send(res, status, payload) {
  if (payload === undefined) {
    res.writeHead(status);
    res.end();
    return;
  }
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(payload));
}

export function createRequestHandler({ repo, impl = "web-function", now = () => new Date() }) {
  return async function handle(req, res) {
    try {
      const path = new URL(req.url, "http://localhost").pathname.replace(/\/+$/, "") || "/";
      const method = req.method;

      if (path === "/health") {
        if (method !== "GET") throw new HttpError(405, "method not allowed");
        return send(res, 200, { status: "ok", impl });
      }

      if (path === "/items") {
        if (method === "GET") return send(res, 200, { items: await repo.list() });
        if (method === "POST") {
          const fields = validateNewItem(await readJson(req));
          const item = { ...fields, createdAt: now().toISOString() };
          try {
            await repo.create(item);
          } catch (err) {
            if (err instanceof ConflictError) throw new HttpError(409, `item ${item.id} already exists`);
            throw err;
          }
          return send(res, 201, item);
        }
        throw new HttpError(405, "method not allowed");
      }

      const match = ITEM_PATH.exec(path);
      if (match) {
        const id = decodeURIComponent(match[1]);
        if (!ID_PATTERN.test(id)) throw new HttpError(400, "invalid id");
        if (method === "GET") {
          const item = await repo.get(id);
          if (!item) throw new HttpError(404, `item ${id} not found`);
          return send(res, 200, item);
        }
        if (method === "DELETE") {
          try {
            await repo.remove(id);
          } catch (err) {
            if (err instanceof NotFoundError) throw new HttpError(404, `item ${id} not found`);
            throw err;
          }
          return send(res, 204);
        }
        throw new HttpError(405, "method not allowed");
      }

      throw new HttpError(404, "route not found");
    } catch (err) {
      if (err instanceof HttpError) return send(res, err.status, { error: err.message });
      console.error(err);
      return send(res, 500, { error: "internal error" });
    }
  };
}
