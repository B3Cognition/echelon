import { Client } from "pg";

const client = new Client({ connectionString: process.env.DATABASE_URL });
await client.connect();
await client.query("create table if not exists markers (marker text primary key)");
await client.end();
