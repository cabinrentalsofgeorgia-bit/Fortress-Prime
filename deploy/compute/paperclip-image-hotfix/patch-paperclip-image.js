const fs = require("node:fs");
const path = require("node:path");

function patchJsonFile(filePath, mutate) {
  const original = fs.readFileSync(filePath, "utf8");
  const parsed = JSON.parse(original);
  const next = JSON.stringify(mutate(parsed, filePath), null, 2) + "\n";
  fs.writeFileSync(filePath, next);
}

function patchTextFile(filePath, searchPattern, replaceValue, appliedMarker) {
  const original = fs.readFileSync(filePath, "utf8");
  if (!searchPattern.test(original)) {
    if (appliedMarker && original.includes(appliedMarker)) {
      return;
    }

    throw new Error(`expected snippet not found in ${filePath}`);
  }

  fs.writeFileSync(filePath, original.replace(searchPattern, replaceValue));
}

const mergePattern =
  /const mergedConfig = issueAssigneeOverrides\?\.adapterConfig\s*\n\s*\? \{ \.\.\.workspaceManagedConfig, \.\.\.issueAssigneeOverrides\.adapterConfig \}\s*\n\s*: workspaceManagedConfig;/;

const mergeReplace = `const mergedConfig = issueAssigneeOverrides?.adapterConfig
                ? {
                    ...workspaceManagedConfig,
                    ...issueAssigneeOverrides.adapterConfig,
                    env: {
                        ...parseObject(workspaceManagedConfig.env),
                        ...parseObject(issueAssigneeOverrides.adapterConfig.env),
                    },
                }
                : workspaceManagedConfig;`;

for (const filePath of [
  "/app/packages/adapter-utils/package.json",
  "/app/server/node_modules/@paperclipai/adapter-utils/package.json",
  "/app/node_modules/.pnpm/@paperclipai+adapter-utils@0.3.1/node_modules/@paperclipai/adapter-utils/package.json",
]) {
  patchJsonFile(filePath, (pkg, currentPath) => {
    const next = { ...pkg, exports: { ...(pkg.exports || {}) } };
    next.exports["./server-utils"] = currentPath.includes(`${path.sep}.pnpm${path.sep}`)
      ? "./dist/server-utils.js"
      : "./src/server-utils.ts";

    if (next.publishConfig?.exports) {
      next.publishConfig = {
        ...next.publishConfig,
        exports: {
          ...next.publishConfig.exports,
          "./server-utils": {
            types: "./dist/server-utils.d.ts",
            import: "./dist/server-utils.js",
            default: "./dist/server-utils.js",
          },
        },
      };
    }

    return next;
  });
}

patchTextFile(
  "/app/server/src/services/heartbeat.ts",
  mergePattern,
  mergeReplace,
  "parseObject(workspaceManagedConfig.env)",
);
patchTextFile(
  "/app/server/dist/services/heartbeat.js",
  mergePattern,
  mergeReplace,
  "parseObject(workspaceManagedConfig.env)",
);
