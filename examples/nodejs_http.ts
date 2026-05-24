/**
 * Intégration audit-bim-i3f en Node.js via HTTP (transport streamable-http).
 *
 * Côté serveur, dans un terminal séparé :
 *   python -m audit_bim.mcp --transport streamable-http --host 0.0.0.0 --port 8765
 *
 * Prérequis client :
 *   npm install @modelcontextprotocol/sdk
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

async function main() {
  const transport = new StreamableHTTPClientTransport(
    new URL("http://localhost:8765/mcp"),
  );
  const client = new Client(
    { name: "metier-bim-app", version: "1.0.0" },
    { capabilities: {} },
  );
  await client.connect(transport);

  const sugs = await client.callTool({
    name: "suggest_classifications",
    arguments: { min_confidence: 0.6, top_n: 1, limit: 50 },
  });
  console.log("Suggestions :", JSON.stringify(sugs, null, 2));

  await client.close();
}

main();
