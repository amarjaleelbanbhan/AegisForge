import * as path from "node:path";
import * as vscode from "vscode";

import { runScan } from "./scan";
import { groupByFile, parseSarif, type DiagnosticLevel } from "./sarif";

const DIAGNOSTIC_COLLECTION_NAME = "cortexward";

const SEVERITY_MAP: Record<DiagnosticLevel, vscode.DiagnosticSeverity> = {
  error: vscode.DiagnosticSeverity.Error,
  warning: vscode.DiagnosticSeverity.Warning,
  information: vscode.DiagnosticSeverity.Information,
};

export function activate(context: vscode.ExtensionContext): void {
  const diagnostics = vscode.languages.createDiagnosticCollection(DIAGNOSTIC_COLLECTION_NAME);
  context.subscriptions.push(diagnostics);

  context.subscriptions.push(
    vscode.commands.registerCommand("cortexward.scanWorkspace", () => scanWorkspace(diagnostics)),
    vscode.commands.registerCommand("cortexward.clearDiagnostics", () => diagnostics.clear()),
  );
}

export function deactivate(): void {
  // Nothing to tear down: the DiagnosticCollection and command
  // registrations are disposed automatically via context.subscriptions.
}

async function scanWorkspace(diagnostics: vscode.DiagnosticCollection): Promise<void> {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (folder === undefined) {
    void vscode.window.showErrorMessage("CortexWard: open a folder or workspace to scan.");
    return;
  }

  const wardPath = vscode.workspace.getConfiguration("cortexward").get<string>("wardPath", "ward");
  const workspaceRoot = folder.uri.fsPath;

  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "CortexWard: scanning workspace…" },
    async () => {
      try {
        const sarifDocument = await runScan({ wardPath, workspaceRoot });
        const findings = parseSarif(sarifDocument);
        publishDiagnostics(diagnostics, workspaceRoot, findings);
        void vscode.window.showInformationMessage(
          findings.length === 0
            ? "CortexWard: no findings."
            : `CortexWard: ${findings.length} finding(s) reported.`,
        );
      } catch (error) {
        void vscode.window.showErrorMessage(`CortexWard scan failed: ${(error as Error).message}`);
      }
    },
  );
}

function publishDiagnostics(
  collection: vscode.DiagnosticCollection,
  workspaceRoot: string,
  findings: ReturnType<typeof parseSarif>,
): void {
  collection.clear();
  for (const [relativePath, fileFindings] of groupByFile(findings)) {
    const uri = vscode.Uri.file(path.join(workspaceRoot, relativePath));
    const fileDiagnostics = fileFindings.map((finding) => {
      const range = new vscode.Range(
        finding.startLine,
        finding.startColumn,
        finding.endLine,
        finding.endColumn,
      );
      const diagnostic = new vscode.Diagnostic(range, finding.message, SEVERITY_MAP[finding.severity]);
      diagnostic.source = "CortexWard";
      diagnostic.code = finding.ruleId;
      return diagnostic;
    });
    collection.set(uri, fileDiagnostics);
  }
}
