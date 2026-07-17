import * as assert from "node:assert/strict";

import { groupByFile, parseSarif, type ParsedFinding } from "../../src/sarif";

function sarifResult(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    ruleId: "B602",
    level: "error",
    message: { text: "subprocess call with shell=True identified" },
    locations: [
      {
        physicalLocation: {
          artifactLocation: { uri: "vuln.py" },
          region: { startLine: 3, startColumn: 5, endLine: 3, endColumn: 37 },
        },
      },
    ],
    ...overrides,
  };
}

function sarifDocument(results: Record<string, unknown>[]): Record<string, unknown> {
  return { version: "2.1.0", runs: [{ results }] };
}

describe("parseSarif", () => {
  it("returns no findings for an empty document", () => {
    assert.deepEqual(parseSarif({ runs: [] }), []);
  });

  it("returns no findings when the document isn't an object", () => {
    assert.deepEqual(parseSarif(null), []);
    assert.deepEqual(parseSarif("not a document"), []);
    assert.deepEqual(parseSarif(undefined), []);
  });

  it("returns no findings when a run has no results", () => {
    assert.deepEqual(parseSarif({ runs: [{}] }), []);
  });

  it("extracts a well-formed result into a ParsedFinding", () => {
    const findings = parseSarif(sarifDocument([sarifResult()]));
    assert.equal(findings.length, 1);
    const finding = findings[0] as ParsedFinding;
    assert.equal(finding.ruleId, "B602");
    assert.equal(finding.message, "subprocess call with shell=True identified");
    assert.equal(finding.severity, "error");
    assert.equal(finding.filePath, "vuln.py");
  });

  it("converts SARIF's 1-indexed line/column to 0-indexed", () => {
    const findings = parseSarif(sarifDocument([sarifResult()]));
    const finding = findings[0] as ParsedFinding;
    // SARIF region: startLine 3, startColumn 5, endLine 3, endColumn 37
    assert.equal(finding.startLine, 2);
    assert.equal(finding.startColumn, 4);
    assert.equal(finding.endLine, 2);
    assert.equal(finding.endColumn, 36);
  });

  it("maps every known SARIF level to the expected severity", () => {
    const levels: Array<[string, ParsedFinding["severity"]]> = [
      ["error", "error"],
      ["warning", "warning"],
      ["note", "information"],
    ];
    for (const [level, expected] of levels) {
      const findings = parseSarif(sarifDocument([sarifResult({ level })]));
      assert.equal(findings[0]?.severity, expected, `level ${level}`);
    }
  });

  it("defaults an unrecognized or missing level to warning", () => {
    assert.equal(parseSarif(sarifDocument([sarifResult({ level: "bogus" })]))[0]?.severity, "warning");
    assert.equal(parseSarif(sarifDocument([sarifResult({ level: undefined })]))[0]?.severity, "warning");
  });

  it("defaults a missing ruleId to 'unknown' rather than throwing", () => {
    const findings = parseSarif(sarifDocument([sarifResult({ ruleId: undefined })]));
    assert.equal(findings[0]?.ruleId, "unknown");
  });

  it("defaults a missing message to a placeholder rather than throwing", () => {
    const findings = parseSarif(sarifDocument([sarifResult({ message: undefined })]));
    assert.equal(findings[0]?.message, "(no message)");
  });

  it("skips a location with no artifact uri rather than crashing", () => {
    const findings = parseSarif(
      sarifDocument([
        sarifResult({
          locations: [{ physicalLocation: { artifactLocation: {}, region: { startLine: 1 } } }],
        }),
      ]),
    );
    assert.deepEqual(findings, []);
  });

  it("defaults a missing region to line 1, column 1", () => {
    const findings = parseSarif(
      sarifDocument([
        sarifResult({
          locations: [{ physicalLocation: { artifactLocation: { uri: "app.py" } } }],
        }),
      ]),
    );
    assert.equal(findings[0]?.startLine, 0);
    assert.equal(findings[0]?.startColumn, 0);
  });

  it("widens a zero-width range by one column so it renders a visible squiggle", () => {
    const findings = parseSarif(
      sarifDocument([
        sarifResult({
          locations: [
            {
              physicalLocation: {
                artifactLocation: { uri: "app.py" },
                region: { startLine: 1, startColumn: 1, endColumn: 1 },
              },
            },
          ],
        }),
      ]),
    );
    const finding = findings[0] as ParsedFinding;
    assert.equal(finding.endColumn, finding.startColumn + 1);
  });

  it("produces one finding per location when a result has several", () => {
    const findings = parseSarif(
      sarifDocument([
        sarifResult({
          locations: [
            { physicalLocation: { artifactLocation: { uri: "a.py" }, region: { startLine: 1 } } },
            { physicalLocation: { artifactLocation: { uri: "b.py" }, region: { startLine: 2 } } },
          ],
        }),
      ]),
    );
    assert.equal(findings.length, 2);
    assert.deepEqual(
      findings.map((f) => f.filePath),
      ["a.py", "b.py"],
    );
  });

  it("collects findings across multiple results and multiple runs", () => {
    const document = {
      runs: [{ results: [sarifResult({ ruleId: "R1" })] }, { results: [sarifResult({ ruleId: "R2" })] }],
    };
    const findings = parseSarif(document);
    assert.deepEqual(
      findings.map((f) => f.ruleId),
      ["R1", "R2"],
    );
  });

  it("skips a malformed result entry instead of throwing", () => {
    assert.doesNotThrow(() => parseSarif(sarifDocument([null as unknown as Record<string, unknown>])));
    assert.deepEqual(parseSarif(sarifDocument(["not an object" as unknown as Record<string, unknown>])), []);
  });
});

describe("groupByFile", () => {
  it("groups findings under their file path", () => {
    const findings = parseSarif(
      sarifDocument([
        sarifResult({ ruleId: "R1", locations: [{ physicalLocation: { artifactLocation: { uri: "a.py" }, region: { startLine: 1 } } }] }),
        sarifResult({ ruleId: "R2", locations: [{ physicalLocation: { artifactLocation: { uri: "a.py" }, region: { startLine: 2 } } }] }),
        sarifResult({ ruleId: "R3", locations: [{ physicalLocation: { artifactLocation: { uri: "b.py" }, region: { startLine: 1 } } }] }),
      ]),
    );
    const grouped = groupByFile(findings);
    assert.equal(grouped.size, 2);
    assert.equal(grouped.get("a.py")?.length, 2);
    assert.equal(grouped.get("b.py")?.length, 1);
  });

  it("returns an empty map for no findings", () => {
    assert.equal(groupByFile([]).size, 0);
  });
});
