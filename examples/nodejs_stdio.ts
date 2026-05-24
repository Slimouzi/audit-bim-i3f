/**
 * Intégration audit-bim-i3f en Node.js / TypeScript via stdio.
 *
 * Prérequis :
 *   npm install @modelcontextprotocol/sdk
 *
 * Lancer :
 *   npx tsx examples/nodejs_stdio.ts
 *
 * Le serveur Python est spawné en sous-processus.
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

async function main() {
  const transport = new StdioClientTransport({
    command: "python",
    args: ["-m", "audit_bim.mcp"],
    cwd: "/Users/stani/code/MCP/audit-bim-i3f",
  });

  const client = new Client(
    { name: "my-bim-app", version: "1.0.0" },
    { capabilities: {} },
  );
  await client.connect(transport);

  // 1. Lister les tools dispo
  const { tools } = await client.listTools();
  console.log(`${tools.length} tools disponibles :`);
  for (const t of tools) console.log(`  • ${t.name}`);

  // 2. Cadrer l'audit
  await client.callTool({
    name: "set_active_model",
    arguments: { phase: "AVP" },
  });

  // 3. Pipeline complet
  const result = await client.callTool({
    name: "full_audit",
    arguments: { phase: "AVP", push_mode: "smartview" },
  });
  console.log("\nRésultat :", JSON.stringify(result, null, 2));

  await client.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
