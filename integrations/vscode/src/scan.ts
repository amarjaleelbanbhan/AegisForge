/**
 * Shells out to `ward scan` and returns its parsed SARIF output. Uses
 * `execFile` (never `exec`) with a fixed argv, never a shell -- the same
 * "no shell, no string-built command line" discipline every subprocess
 * call in the Python codebase already follows (`BanditScanner`,
 * `apply_and_rescan`'s `git apply`).
 */

import { execFile } from "node:child_process";

export interface ScanOptions {
  wardPath: string;
  workspaceRoot: string;
  timeoutMs?: number;
}

const DEFAULT_TIMEOUT_MS = 5 * 60 * 1000;
// Generous but bounded, matching BanditScanner's own 300s subprocess
// timeout -- a hung `ward scan` must not hang the extension indefinitely.

const MAX_BUFFER_BYTES = 10 * 1024 * 1024;

interface ExecFileError extends Error {
  code?: number;
  stdout?: string;
}

/**
 * Runs `ward scan <workspaceRoot> --fail-on none --format sarif` and parses
 * the resulting document. `--fail-on none` is deliberate and not
 * user-configurable: this extension shows every finding as a diagnostic
 * regardless of severity, so there is no meaningful "fail" outcome for it
 * to react to -- unlike CI, where `--fail-on` gates a pipeline.
 */
export function runScan(options: ScanOptions): Promise<unknown> {
  const args = ["scan", options.workspaceRoot, "--fail-on", "none", "--format", "sarif"];
  return new Promise((resolve, reject) => {
    execFile(
      options.wardPath,
      args,
      { timeout: options.timeoutMs ?? DEFAULT_TIMEOUT_MS, maxBuffer: MAX_BUFFER_BYTES },
      (error, stdout) => {
        let output = stdout;
        if (error !== null) {
          // `--fail-on none` means ward scan always exits 0 on a genuine
          // scan, but defend against a future default change or a caller
          // passing a stricter threshold some other way: a non-zero exit
          // with valid SARIF on stdout is still a completed scan, not a
          // failure to run at all.
          const execError = error as ExecFileError;
          if (typeof execError.stdout !== "string" || execError.stdout.trim().length === 0) {
            reject(new Error(`ward scan failed to run: ${execError.message}`));
            return;
          }
          output = execError.stdout;
        }
        try {
          resolve(JSON.parse(output));
        } catch (parseError) {
          reject(new Error(`ward scan produced output that isn't valid JSON: ${String(parseError)}`));
        }
      },
    );
  });
}
