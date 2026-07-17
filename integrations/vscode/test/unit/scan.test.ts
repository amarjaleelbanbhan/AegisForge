import * as assert from "node:assert/strict";
import * as os from "node:os";
import * as path from "node:path";

import { runScan } from "../../src/scan";

/**
 * `runScan` shells out via `execFile` with a fixed argv and no shell
 * (deliberately, per its own module docstring) -- faking a stand-in "ward"
 * executable that `execFile` can invoke directly, cross-platform, without
 * a shell is its own rabbit hole (a `.cmd`/`.sh` wrapper needs `shell:
 * true` to run via `execFile` on Windows, which would test a code path
 * `runScan` doesn't use). The genuinely testable-without-a-shell surface
 * is the error handling when the executable itself can't be found; the
 * SARIF-parsing logic `runScan` shares with a real invocation is covered
 * exhaustively by `sarif.test.ts`, and the full happy path (a real `ward`
 * producing real SARIF over a real subprocess) is covered by the
 * integration test suite instead.
 */
describe("runScan", () => {
  it("rejects with a clear error when the executable can't be found", async () => {
    const missingPath = path.join(os.tmpdir(), "definitely-not-a-real-cortexward-executable");
    await assert.rejects(
      runScan({ wardPath: missingPath, workspaceRoot: "." }),
      /ward scan failed to run/,
    );
  });
});
