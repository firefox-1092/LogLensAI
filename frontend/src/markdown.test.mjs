import assert from 'node:assert/strict';
import test from 'node:test';

import { parseAssistantMarkdown } from './markdown.mjs';

test('renders escaped asterisk emphasis as formatting tokens', () => {
  const blocks = parseAssistantMarkdown('\\*Source:\\* line 1');

  assert.deepEqual(blocks[0], {
    type: 'paragraph',
    tokens: [
      { type: 'emphasis', value: 'Source:' },
      { type: 'text', value: ' line 1' },
    ],
  });
});

test('renders escaped bold delimiters without changing unrelated backslashes', () => {
  const blocks = parseAssistantMarkdown('\\*\\*Warning\\*\\* at C:\\logs\\service');

  assert.deepEqual(blocks[0].tokens, [
    { type: 'strong', value: 'Warning' },
    { type: 'text', value: ' at C:\\logs\\service' },
  ]);
});

test('preserves backslashes inside inline code', () => {
  const blocks = parseAssistantMarkdown('Check `C:\\logs\\app.log` for details.');

  assert.deepEqual(blocks[0].tokens, [
    { type: 'text', value: 'Check ' },
    { type: 'code', value: 'C:\\logs\\app.log' },
    { type: 'text', value: ' for details.' },
  ]);
});

test('preserves headings, paragraphs, lists, bold text and inline code', () => {
  const blocks = parseAssistantMarkdown(
    '## Observed facts\nThe **service** started.\n\n- Check `line 1`\n- Review source',
  );

  assert.equal(blocks[0].type, 'heading');
  assert.deepEqual(blocks[1].tokens, [
    { type: 'text', value: 'The ' },
    { type: 'strong', value: 'service' },
    { type: 'text', value: ' started.' },
  ]);
  assert.equal(blocks[2].type, 'unordered-list');
  assert.deepEqual(blocks[2].items[0], [
    { type: 'text', value: 'Check ' },
    { type: 'code', value: 'line 1' },
  ]);
});

test('keeps raw HTML as text rather than interpreting it as markup', () => {
  const blocks = parseAssistantMarkdown('<script>alert(1)</script>');

  assert.deepEqual(blocks[0].tokens, [{ type: 'text', value: '<script>alert(1)</script>' }]);
});
