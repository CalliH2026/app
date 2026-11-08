// File-backed stand-in for the Cloudflare ASSETS binding (tests and local serve only).
import {readFile} from 'node:fs/promises';
import {join, normalize, sep} from 'node:path';

export function fileAssets(root) {
  return {
    async fetch(request) {
      const name = new URL(request.url).pathname;
      if (!/^\/_p\/[a-f0-9]{24}$/.test(name)) return new Response('not found', {status: 404});
      const file = normalize(join(root, name));
      if (!file.startsWith(normalize(root) + sep)) return new Response('not found', {status: 404});
      try { return new Response(await readFile(file)); } catch { return new Response('not found', {status: 404}); }
    },
  };
}
