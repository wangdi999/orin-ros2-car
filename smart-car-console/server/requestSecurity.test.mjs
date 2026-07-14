import test from 'node:test';
import assert from 'node:assert/strict';
import { requireJsonContentType, validateLocalRequest } from './requestSecurity.mjs';

test('local API accepts loopback hosts and local browser origins', () => {
  assert.equal(validateLocalRequest({ host: '127.0.0.1:8787', origin: 'http://127.0.0.1:5173' }).ok, true);
  assert.equal(validateLocalRequest({ host: 'localhost:8787', origin: 'http://localhost:5173' }).ok, true);
  assert.equal(validateLocalRequest({ host: '[::1]:8787' }).ok, true);
});

test('local API rejects DNS rebinding and cross-site browser requests', () => {
  assert.equal(validateLocalRequest({ host: 'attacker.example:8787' }).ok, false);
  assert.equal(validateLocalRequest({ host: '127.0.0.1:8787', origin: 'https://attacker.example' }).ok, false);
  assert.equal(validateLocalRequest({ host: '127.0.0.1:8787', 'sec-fetch-site': 'cross-site' }).ok, false);
  assert.equal(validateLocalRequest({ host: '127.0.0.1:8787', origin: 'null' }).ok, false);
});

test('JSON request bodies require the JSON media type', () => {
  assert.doesNotThrow(() => requireJsonContentType({ 'content-type': 'application/json; charset=utf-8' }));
  assert.throws(() => requireJsonContentType({ 'content-type': 'text/plain' }), /application\/json/);
  assert.throws(() => requireJsonContentType({}), /application\/json/);
});
