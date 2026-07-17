import * as assert from "node:assert/strict";

import * as vscode from "vscode";

describe("CortexWard extension", () => {
  it("is discoverable and activates without error", async () => {
    const extension = vscode.extensions.getExtension("amarjaleelbanbhan.cortexward-vscode");
    assert.ok(extension, "extension should be discoverable by its id");
    await extension?.activate();
    assert.equal(extension?.isActive, true);
  });

  it("registers both of its commands", async () => {
    const extension = vscode.extensions.getExtension("amarjaleelbanbhan.cortexward-vscode");
    await extension?.activate();
    const commands = await vscode.commands.getCommands(true);
    assert.ok(commands.includes("cortexward.scanWorkspace"));
    assert.ok(commands.includes("cortexward.clearDiagnostics"));
  });

  it("clearDiagnostics runs without throwing even with nothing to clear", async () => {
    const extension = vscode.extensions.getExtension("amarjaleelbanbhan.cortexward-vscode");
    await extension?.activate();
    await vscode.commands.executeCommand("cortexward.clearDiagnostics");
  });

  it("contributes the cortexward.wardPath configuration setting", () => {
    const config = vscode.workspace.getConfiguration("cortexward");
    assert.equal(config.get<string>("wardPath"), "ward");
  });
});
