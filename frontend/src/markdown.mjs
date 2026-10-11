const INLINE_PATTERN = /(`[^`]*`|\\\*\\\*[\s\S]+?\\\*\\\*|\*\*[\s\S]+?\*\*|\\\*[^*\n]+?\\\*|__[^_\n]+__|\*[^*\n]+?\*)/g;

function parseInline(source) {
  const tokens = [];
  let previousEnd = 0;

  for (const match of source.matchAll(INLINE_PATTERN)) {
    if (match.index > previousEnd) tokens.push({ type: 'text', value: source.slice(previousEnd, match.index) });
    const value = match[0];
    if (value.startsWith('`')) {
      tokens.push({ type: 'code', value: value.slice(1, -1) });
    } else if (value.startsWith('\\*\\*')) {
      tokens.push({ type: 'strong', value: value.slice(4, -4) });
    } else if (value.startsWith('**') || value.startsWith('__')) {
      tokens.push({ type: 'strong', value: value.slice(2, -2) });
    } else if (value.startsWith('\\*')) {
      tokens.push({ type: 'emphasis', value: value.slice(2, -2) });
    } else {
      tokens.push({ type: 'emphasis', value: value.slice(1, -1) });
    }
    previousEnd = match.index + value.length;
  }

  if (previousEnd < source.length) tokens.push({ type: 'text', value: source.slice(previousEnd) });
  return tokens;
}

export function parseAssistantMarkdown(source) {
  const lines = source.split(/\r?\n/);
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      index += 1;
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, tokens: parseInline(heading[2]) });
      index += 1;
      continue;
    }

    const firstItem = line.match(/^(?:[-*]\s+|\d+[.)]\s+)(.+)$/);
    if (firstItem) {
      const ordered = /^\d+[.)]\s+/.test(line);
      const items = [];
      while (index < lines.length) {
        const item = lines[index].trim().match(ordered ? /^\d+[.)]\s+(.+)$/ : /^[-*]\s+(.+)$/);
        if (!item) break;
        items.push(parseInline(item[1]));
        index += 1;
      }
      blocks.push({ type: ordered ? 'ordered-list' : 'unordered-list', items });
      continue;
    }

    const paragraph = [line];
    index += 1;
    while (
      index < lines.length && lines[index].trim() &&
      !/^(?:#{1,3}\s+|[-*]\s+|\d+[.)]\s+)/.test(lines[index].trim())
    ) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push({ type: 'paragraph', tokens: parseInline(paragraph.join(' ')) });
  }

  return blocks;
}
