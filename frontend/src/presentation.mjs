const LINE_CITATION = /\blines?\s+((?:\d+)(?:\s*(?:,\s*(?:(?:and|or|&)\s*)?|(?:and|or|&)\s*|to\s*|[-–]\s*)\d+)*)/gi;

export function getTimelineBarHeight(entries, maximumEntries) {
  if (entries <= 0) return 0;
  const scaleMaximum = Math.max(maximumEntries, 3);
  return Math.max(6, Math.min(100, (entries / scaleMaximum) * 100));
}

export function selectTimelineLabelIndices(bucketCount, maximumLabels = 6) {
  if (bucketCount <= 0 || maximumLabels <= 0) return [];
  if (bucketCount <= maximumLabels) return Array.from({ length: bucketCount }, (_, index) => index);
  if (maximumLabels === 1) return [0];

  return Array.from({ length: maximumLabels }, (_, index) =>
    Math.round((index * (bucketCount - 1)) / (maximumLabels - 1)),
  );
}

export function getCitedLineSegments(text, citedLineNumbers) {
  const allowedLines = citedLineNumbers instanceof Set ? citedLineNumbers : new Set(citedLineNumbers);
  const linkedNumbers = [];

  for (const citation of text.matchAll(LINE_CITATION)) {
    const reference = citation[1];
    const referenceStart = citation.index + citation[0].indexOf(reference);
    for (const number of reference.matchAll(/\d+/g)) {
      const lineNumber = Number(number[0]);
      if (allowedLines.has(lineNumber)) {
        const start = referenceStart + number.index;
        linkedNumbers.push({ start, end: start + number[0].length, lineNumber });
      }
    }
  }

  linkedNumbers.sort((left, right) => left.start - right.start);
  const segments = [];
  let cursor = 0;
  for (const citation of linkedNumbers) {
    if (citation.start < cursor) continue;
    if (citation.start > cursor) segments.push({ type: 'text', value: text.slice(cursor, citation.start) });
    segments.push({ type: 'line', value: text.slice(citation.start, citation.end), lineNumber: citation.lineNumber });
    cursor = citation.end;
  }
  if (cursor < text.length) segments.push({ type: 'text', value: text.slice(cursor) });
  return segments;
}
