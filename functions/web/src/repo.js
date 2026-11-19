// DynamoDB-backed repository. The SDK picks the endpoint from the environment:
// on Lambda it is the real service; in CI, AWS_ENDPOINT_URL points it at AWS Emulator.
import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import {
  DeleteCommand,
  DynamoDBDocumentClient,
  GetCommand,
  PutCommand,
  ScanCommand,
} from "@aws-sdk/lib-dynamodb";
import { ConflictError, NotFoundError } from "./app.js";

export function createDynamoRepo({ tableName, client = DynamoDBDocumentClient.from(new DynamoDBClient({})) }) {
  if (!tableName) throw new Error("TABLE_NAME is required");
  return {
    async create(item) {
      try {
        await client.send(
          new PutCommand({ TableName: tableName, Item: item, ConditionExpression: "attribute_not_exists(id)" }),
        );
      } catch (err) {
        if (err.name === "ConditionalCheckFailedException") throw new ConflictError(item.id);
        throw err;
      }
    },
    async get(id) {
      const out = await client.send(new GetCommand({ TableName: tableName, Key: { id } }));
      return out.Item ?? null;
    },
    async list() {
      const out = await client.send(new ScanCommand({ TableName: tableName, Limit: 100 }));
      return (out.Items ?? []).sort((a, b) => a.createdAt.localeCompare(b.createdAt));
    },
    async remove(id) {
      try {
        await client.send(
          new DeleteCommand({ TableName: tableName, Key: { id }, ConditionExpression: "attribute_exists(id)" }),
        );
      } catch (err) {
        if (err.name === "ConditionalCheckFailedException") throw new NotFoundError(id);
        throw err;
      }
    },
  };
}
