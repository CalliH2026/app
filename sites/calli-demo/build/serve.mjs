// Local Node server for the built preview: node build/serve.mjs [port] [server|assets]
import {createServer} from 'node:http';
import {fileURLToPath} from 'node:url';
import {fileAssets} from './assets.mjs';
const port = Number(process.argv[2] || 8787);
const mode = process.argv[3] || 'server';
let fetchHandler;
if (mode === 'assets') {
  const {handle} = await import('../dist/worker.js');
  const env = {ASSETS: fileAssets(fileURLToPath(new URL('../dist/public', import.meta.url)))};
  fetchHandler = (request) => handle(request, env);
} else {
  const server = (await import('../dist/server/index.js')).default;
  fetchHandler = (request) => server.fetch(request, {});
}
createServer(async (req, res) => {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const init = {method: req.method, headers: req.headers};
  if (chunks.length && !['GET', 'HEAD'].includes(req.method)) init.body = Buffer.concat(chunks);
  const response = await fetchHandler(new Request(`http://127.0.0.1:${port}${req.url}`, init));
  res.writeHead(response.status, Object.fromEntries(response.headers));
  res.end(response.body ? Buffer.from(await response.arrayBuffer()) : undefined);
}).listen(port, '127.0.0.1', () => console.log(`Calli preview (${mode}) on http://127.0.0.1:${port}/`));
