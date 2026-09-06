import test from 'node:test';
import assert from 'node:assert/strict';
import { subscribeFeed, FEED_URL } from './feed.js';

const flush = () => new Promise(resolve => setImmediate(resolve));
const sample = generated_at => ({generated_at, matches: Array.from({length: 20}, (_, i) => ({
  id: String(i), home: 'A', away: 'B', league: 'LaLiga', kickoff: '2026-09-05T20:00:00Z',
}))});

test('subscription rejects regressions and cleans up pending requests on remount', async t => {
  const oldWindow = globalThis.window, oldDocument = globalThis.document;
  const timers = new Set(), listeners = new Map(), docListeners = new Map();
  globalThis.window = {setInterval: fn => (timers.add(fn), fn), clearInterval: fn => timers.delete(fn),
    addEventListener: (key, fn) => listeners.set(key, fn), removeEventListener: key => listeners.delete(key)};
  globalThis.document = {visibilityState: 'visible', addEventListener: (key, fn) => docListeners.set(key, fn),
    removeEventListener: key => docListeners.delete(key)};
  t.after(() => {globalThis.window = oldWindow; globalThis.document = oldDocument;});
  let next = sample('2026-09-05T12:00:00Z'), failRemote = false, pending = null;
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(options.cache, 'no-cache');
    assert.ok(options.signal);
    assert.ok(!url.includes('?t='));
    if (pending) return pending;
    if (failRemote && url === FEED_URL) throw new Error('network failure');
    return {ok: true, json: async () => next};
  });
  const received = [];
  const cleanup = subscribeFeed(data => received.push(data));
  await flush();
  assert.equal(received.length, 1);
  next = sample('2026-09-05T10:00:00Z');
  for (const refresh of timers) refresh();
  await flush();
  assert.equal(received.length, 1, 'older remote data is not accepted');
  next = sample('2026-09-05T13:00:00Z'); failRemote = true;
  for (const refresh of timers) refresh();
  await flush();
  assert.equal(received.length, 1, 'bundled fallback cannot replace a live feed');
  failRemote = false;
  for (const refresh of timers) refresh();
  await flush();
  assert.equal(received.length, 2);
  cleanup();
  assert.equal(timers.size + listeners.size + docListeners.size, 0);
  let release;
  pending = new Promise(resolve => {release = resolve;});
  const unmount = subscribeFeed(data => received.push(data));
  unmount();
  release({ok: true, json: async () => sample('2026-09-05T14:00:00Z')});
  await flush();
  assert.equal(received.length, 2, 'a request completing after unmount has no callback');
  assert.equal(timers.size + listeners.size + docListeners.size, 0);
});
