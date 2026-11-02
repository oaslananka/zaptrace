// Bind Chrome DevTools to the verified local debugger launched for this test.
export function localChromeSocketUrl(candidate, expectedPort) {
  const port = Number(expectedPort);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw Error('Invalid local Chrome debugger port');
  }
  const parsed = new URL(candidate);
  const valid = parsed.protocol === 'ws:' &&
    (parsed.hostname === '127.0.0.1' || parsed.hostname === 'localhost') &&
    Number(parsed.port) === port &&
    !parsed.username && !parsed.password && !parsed.search && !parsed.hash &&
    /^\/devtools\/page\/[A-Za-z0-9_-]{1,128}$/.test(parsed.pathname);
  if (!valid) throw Error('Chrome debugger endpoint is not the expected local page');
  return `ws://127.0.0.1:${port}${parsed.pathname}`;
}
