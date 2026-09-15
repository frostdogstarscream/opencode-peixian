// Invoked only for a versioned, administrator-published plugin entry.
import { pathToFileURL } from "node:url";

const write = process.stdout.write.bind(process.stdout);
process.stdout.write = () => true;
process.stderr.write = () => true;
for (const method of ["log", "info", "warn", "error", "debug", "trace", "dir", "table"])
  console[method] = () => {};

let result = { supported: true, ok: false, message: "Connection test failed" };
try {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const { entry, options, platform_connections, platform_client } = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  const plugin = await import(pathToFileURL(entry).href);
  if (typeof plugin.test !== "function") {
    result = { supported: false, ok: false, message: "Plugin does not export a connection test" };
  } else {
    const platform = platform_client ? (await import(pathToFileURL(platform_client).href)).createPlatform(platform_connections) : undefined;
    const value = await plugin.test(options, platform);
    if (!value || typeof value.ok !== "boolean" || typeof value.message !== "string")
      throw new Error("Invalid test result");
    // Free-form plugin output may include addresses or credentials. Return a
    // fixed message derived only from the boolean result.
    result = { supported: true, ok: value.ok,
      message: value.ok ? "Connection test passed" : "Connection test failed" };
  }
} catch {}
write(JSON.stringify(result));
process.exit(0);
