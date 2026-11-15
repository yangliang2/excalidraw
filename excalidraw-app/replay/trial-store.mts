import { randomUUID } from "node:crypto";
import type { Plugin } from "vite";

// Only the development server stores trial clips here. Restarting clears them.
export function localReplayStore(): Plugin {
  const clips = new Map<string, Buffer>();
  const maxBytes = 8 * 1024 * 1024;
  return {
    name: "local-replay-trial",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use("/__replay", async (req, res) => {
        res.setHeader("Cache-Control", "no-store");
        if (req.method === "POST" && req.url === "/") {
          const origin = req.headers.origin;
          if (!origin || new URL(origin).host !== req.headers.host) {
            res.writeHead(403).end();
            return;
          }
          if (clips.size >= 16) {
            res.writeHead(507).end();
            return;
          }
          const chunks: Buffer[] = [];
          let size = 0;
          try {
            for await (const chunk of req) {
              size += chunk.length;
              if (size > maxBytes) {
                res.writeHead(413).end();
                return;
              }
              chunks.push(chunk);
            }
            const id = randomUUID();
            clips.set(id, Buffer.concat(chunks));
            res.setHeader("Content-Type", "application/json");
            res.end(JSON.stringify({ id }));
          } catch {
            res.writeHead(400).end();
          }
          return;
        }
        const clip =
          req.method === "GET" && clips.get((req.url || "").slice(1));
        if (!clip) {
          res.writeHead(404).end();
          return;
        }
        res.setHeader("Content-Type", "application/octet-stream");
        res.end(clip);
      });
    },
  };
}
