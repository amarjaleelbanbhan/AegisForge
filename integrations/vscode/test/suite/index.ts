import Mocha from "mocha";

/**
 * Loaded by `@vscode/test-electron` inside a real VS Code Extension Host.
 * Requires each compiled test file directly (no glob dependency needed --
 * there's exactly one integration suite today; add more `require()` lines
 * here as they're added rather than pulling in a globbing library for a
 * single file).
 */
export function run(): Promise<void> {
  const mocha = new Mocha({ ui: "bdd", color: true, timeout: 30_000 });
  mocha.addFile(require.resolve("./extension.test"));

  return new Promise((resolve, reject) => {
    mocha.run((failures) => {
      if (failures > 0) {
        reject(new Error(`${failures} integration test(s) failed.`));
      } else {
        resolve();
      }
    });
  });
}
