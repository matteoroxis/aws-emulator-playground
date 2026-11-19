// Entry point of the Lambda Web Function. Lambda passes the address to listen on in
// AWS_LAMBDA_HTTP_ENDPOINT ("host:port"); outside Lambda we fall back to PORT (default 3000).
import http from "node:http";
import { createRequestHandler } from "./app.js";
import { createDynamoRepo } from "./repo.js";

const endpoint = process.env.AWS_LAMBDA_HTTP_ENDPOINT ?? `127.0.0.1:${process.env.PORT ?? 3000}`;
const sep = endpoint.lastIndexOf(":");
const host = endpoint.slice(0, sep);
const port = Number(endpoint.slice(sep + 1));

const handler = createRequestHandler({ repo: createDynamoRepo({ tableName: process.env.TABLE_NAME }) });
const server = http.createServer(handler);

server.listen(port, host, () => console.log(JSON.stringify({ msg: "listening", host, port })));

process.on("SIGTERM", () => server.close(() => process.exit(0)));
