import test from 'node:test';
import assert from 'node:assert/strict';
import { decide } from '../src/index.js';

const now = Date.parse('2026-10-15T12:00:00Z');
const run = (status, minAgo) => ({ status, created_at: new Date(now - minAgo * 60000).toISOString() });

test('starts when nothing has run for a while', () => assert.equal(decide({ runs: [run('completed', 20)], nowMs: now, minGapMin: 4.5 }).start, true));
test('starts when no run ever happened', () => assert.equal(decide({ runs: [], nowMs: now, minGapMin: 4.5 }).start, true));
test('does not pile up while a run is working', () => assert.equal(decide({ runs: [run('in_progress', 2), run('completed', 9)], nowMs: now, minGapMin: 4.5 }).start, false));
test('does not start while one is waiting in line', () => assert.equal(decide({ runs: [run('queued', 1)], nowMs: now, minGapMin: 4.5 }).start, false));
test('does not start twice inside the minimum gap', () => assert.equal(decide({ runs: [run('completed', 3)], nowMs: now, minGapMin: 4.5 }).start, false));
test('bad input never throws', () => assert.equal(decide({ runs: null, nowMs: now, minGapMin: 4.5 }).start, true));
