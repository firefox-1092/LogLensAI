import assert from 'node:assert/strict';
import test from 'node:test';

import { getCitedLineSegments, getTimelineBarHeight, selectTimelineLabelIndices } from './presentation.mjs';

test('timeline bars scale by count without making a lone event full height', () => {
  assert.equal(getTimelineBarHeight(0, 8), 0);
  assert.ok(Math.abs(getTimelineBarHeight(1, 1) - (100 / 3)) < 1e-9);
  assert.equal(getTimelineBarHeight(4, 8), 50);
  assert.equal(getTimelineBarHeight(20, 8), 100);
});

test('timeline labels stay bounded and cover the first and last buckets', () => {
  assert.deepEqual(selectTimelineLabelIndices(0), []);
  assert.deepEqual(selectTimelineLabelIndices(3), [0, 1, 2]);
  const indices = selectTimelineLabelIndices(100);
  assert.equal(indices.length, 6);
  assert.equal(indices[0], 0);
  assert.equal(indices.at(-1), 99);
  assert.deepEqual([...indices].sort((a, b) => a - b), indices);
});

test('only explicit line citations present in validated evidence are linkable', () => {
  const segments = getCitedLineSegments(
    'Observed on **Lines 1, 3 and 8**. Status 500 at 10:00, and line 9 was not cited.',
    [1, 3, 8],
  );

  assert.deepEqual(segments.filter((part) => part.type === 'line'), [
    { type: 'line', value: '1', lineNumber: 1 },
    { type: 'line', value: '3', lineNumber: 3 },
    { type: 'line', value: '8', lineNumber: 8 },
  ]);
  assert.ok(segments.some((part) => part.type === 'text' && part.value.includes('line 9')));
  assert.ok(segments.some((part) => part.type === 'text' && part.value.includes('Status 500 at 10:00')));
});

test('uncited numeric text remains ordinary text', () => {
  assert.deepEqual(getCitedLineSegments('HTTP 500 happened at 10:00 in 2026.', [500, 10, 2026]), [
    { type: 'text', value: 'HTTP 500 happened at 10:00 in 2026.' },
  ]);
});
