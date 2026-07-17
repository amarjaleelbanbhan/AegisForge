/**
 * Parses a SARIF 2.1.0 document produced by `ward scan` into plain,
 * VS Code-API-independent data. Kept separate from `extension.ts` so this
 * logic is unit-testable without the full VS Code Extension Host (which
 * `vscode.Diagnostic`/`vscode.Range` require) -- `extension.ts` is the only
 * place that converts a `ParsedFinding` into a real `vscode.Diagnostic`.
 *
 * SARIF is untrusted-shaped input as far as this parser is concerned: it
 * comes from an external process's stdout, and every field is optional per
 * the SARIF spec. Every access is defensive -- a malformed or unexpected
 * document degrades to an empty result, never a thrown exception, matching
 * this project's own scanner adapters' treatment of untrusted tool output
 * (`cortexward.scanners.bandit_scanner._int`, `secrets_scanner._int`).
 */

export type DiagnosticLevel = "error" | "warning" | "information";

export interface ParsedFinding {
  /** The file path exactly as SARIF reported it (relative to the scan root). */
  filePath: string;
  ruleId: string;
  message: string;
  severity: DiagnosticLevel;
  /** 0-indexed, ready for `vscode.Position`/`vscode.Range` (SARIF is 1-indexed). */
  startLine: number;
  startColumn: number;
  endLine: number;
  endColumn: number;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : undefined;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asString(value: unknown, fallback: string): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

/** A positive integer, 1-indexed per SARIF, converted to a 0-indexed line/column -- never negative. */
function asZeroIndexed(value: unknown, fallback: number): number {
  const oneIndexed = typeof value === "number" && Number.isFinite(value) && value >= 1 ? value : fallback + 1;
  return Math.max(0, oneIndexed - 1);
}

const LEVEL_MAP: Record<string, DiagnosticLevel> = {
  error: "error",
  warning: "warning",
  note: "information",
};

function levelFor(rawLevel: unknown): DiagnosticLevel {
  if (typeof rawLevel === "string" && rawLevel in LEVEL_MAP) {
    return LEVEL_MAP[rawLevel];
  }
  return "warning";
}

function findingsFromResult(result: unknown): ParsedFinding[] {
  const record = asRecord(result);
  if (record === undefined) {
    return [];
  }
  const ruleId = asString(record.ruleId, "unknown");
  const message = asString(asRecord(record.message)?.text, "(no message)");
  const severity = levelFor(record.level);

  const findings: ParsedFinding[] = [];
  for (const rawLocation of asArray(record.locations)) {
    const physical = asRecord(asRecord(rawLocation)?.physicalLocation);
    const artifactLocation = asRecord(physical?.artifactLocation);
    const filePath = asString(artifactLocation?.uri, "");
    if (filePath === "") {
      continue;
    }
    const region = asRecord(physical?.region);
    const startLine = asZeroIndexed(region?.startLine, 0);
    const startColumn = asZeroIndexed(region?.startColumn, 0);
    const endLine = region?.endLine !== undefined ? asZeroIndexed(region.endLine, startLine) : startLine;
    const endColumnFallback = startColumn + 1;
    const endColumn =
      region?.endColumn !== undefined ? asZeroIndexed(region.endColumn, endColumnFallback) : endColumnFallback;

    findings.push({
      filePath,
      ruleId,
      message,
      severity,
      startLine,
      startColumn,
      endLine,
      // A zero-width range (endColumn === startColumn) renders no visible
      // squiggle in VS Code; widen by one column when SARIF gave no end.
      endColumn: endColumn > startColumn ? endColumn : startColumn + 1,
    });
  }
  return findings;
}

/** Every finding across every run/result in `document`, defensively parsed. */
export function parseSarif(document: unknown): ParsedFinding[] {
  const root = asRecord(document);
  if (root === undefined) {
    return [];
  }
  const findings: ParsedFinding[] = [];
  for (const run of asArray(root.runs)) {
    for (const result of asArray(asRecord(run)?.results)) {
      findings.push(...findingsFromResult(result));
    }
  }
  return findings;
}

/** Groups findings by file path, the shape `vscode.DiagnosticCollection.set` needs per file. */
export function groupByFile(findings: ParsedFinding[]): Map<string, ParsedFinding[]> {
  const grouped = new Map<string, ParsedFinding[]>();
  for (const finding of findings) {
    const existing = grouped.get(finding.filePath);
    if (existing === undefined) {
      grouped.set(finding.filePath, [finding]);
    } else {
      existing.push(finding);
    }
  }
  return grouped;
}
