// The API must be a separately deployed HTTPS service; never deploy a broken
// frontend or route private submissions to an accidentally selected origin.
const apiOrigin = process.env.ARENA_API_ORIGIN;
if (!apiOrigin) {
  throw new Error('Set ARENA_API_ORIGIN to the HTTPS origin of the Stack Theory API before deploying.');
}
const api = new URL(apiOrigin);
if (api.protocol !== 'https:' || api.username || api.password || api.pathname !== '/' || api.search || api.hash) {
  throw new Error('ARENA_API_ORIGIN must be a bare HTTPS origin without credentials or a path.');
}

export const config = {
  framework: 'vite',
  buildCommand: 'pnpm build',
  outputDirectory: 'dist',
  rewrites: [
    { source: '/api/:path*', destination: `${api.origin}/api/:path*` },
    { source: '/(.*)', destination: '/index.html' },
  ],
};
