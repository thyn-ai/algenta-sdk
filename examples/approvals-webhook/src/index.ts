import { loadConfig } from "./config.js";
import { createServer, startServer } from "./server.js";

async function main(): Promise<void> {
  const config = loadConfig();
  const { server, url } = createServer(config);

  await startServer({ server, port: config.port, url });

  console.log(`Algenta approvals webhook receiver listening at ${url}/webhooks/approval`);
  console.log(`Targeting Algenta engine: ${config.baseUrl}`);
  if (config.webhookSecret !== undefined) {
    console.log("Webhook callback-token verification is enabled.");
  }
}

void main();
