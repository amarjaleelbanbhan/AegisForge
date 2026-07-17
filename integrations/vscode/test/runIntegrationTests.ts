import * as path from "node:path";

import { runTests } from "@vscode/test-electron";

async function main(): Promise<void> {
  // Compiled output lives at out/test/runIntegrationTests.js; the
  // extension root (where package.json lives) is two levels up from there.
  const extensionDevelopmentPath = path.resolve(__dirname, "../../");
  const extensionTestsPath = path.resolve(__dirname, "./suite/index");
  await runTests({ extensionDevelopmentPath, extensionTestsPath });
}

main().catch((error: unknown) => {
  console.error("Failed to run integration tests:", error);
  process.exitCode = 1;
});
