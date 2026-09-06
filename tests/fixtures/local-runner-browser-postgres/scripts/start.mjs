import http from "node:http";
import { Client } from "pg";

const databaseUrl = process.env.DATABASE_URL;
const expectedToken = process.env.ECHELON_SESSION_TOKEN;
const marker = process.env.ECHELON_MARKER;
const port = Number(process.env.ECHELON_PORT);

if (!databaseUrl || !expectedToken || !marker || !Number.isInteger(port)) {
  throw new Error("runner-owned environment is incomplete");
}

function authorized(request) {
  return request.headers.authorization === `Bearer ${expectedToken}`;
}

async function readMarker() {
  const client = new Client({ connectionString: databaseUrl });
  await client.connect();
  const result = await client.query("select marker from markers order by marker limit 1");
  await client.end();
  return result.rows[0]?.marker ?? null;
}

async function storeMarker() {
  const client = new Client({ connectionString: databaseUrl });
  await client.connect();
  await client.query("insert into markers (marker) values ($1) on conflict (marker) do nothing", [marker]);
  await client.end();
}

const server = http.createServer(async (request, response) => {
  try {
    if (request.url === "/health/ready") {
      await readMarker();
      response.writeHead(200).end("ready");
      return;
    }
    if (request.url === "/marker" && !authorized(request)) {
      response.writeHead(401).end("unauthorized");
      return;
    }
    if (request.url === "/marker" && request.method === "GET") {
      const saved = await readMarker();
      if (!saved) response.writeHead(404).end("missing");
      else response.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({ marker: saved }));
      return;
    }
    if (request.url === "/marker" && request.method === "POST") {
      await storeMarker();
      response.writeHead(201).end("stored");
      return;
    }
    if (request.url === "/") {
      response.writeHead(200, { "content-type": "text/html" }).end(`<!doctype html>
        <main id="scene">Loading saved world…</main>
        <script type="module">
          const token = sessionStorage.getItem("echelonSessionToken");
          const headers = { authorization: "Bearer " + token };
          const first = await fetch("/marker", { headers });
          if (first.status === 404) await fetch("/marker", { method: "POST", headers });
          const saved = await fetch("/marker", { headers }).then(response => response.json());
          document.querySelector("#scene").dataset.marker = saved.marker;
          document.querySelector("#scene").textContent = "Saved marker: " + saved.marker;
        </script>`);
      return;
    }
    response.writeHead(404).end("not found");
  } catch (error) {
    response.writeHead(503).end(String(error));
  }
});

server.listen(port, "127.0.0.1");
