export type CitationSegment =
  | { type: 'text'; value: string }
  | { type: 'line'; value: string; lineNumber: number };

export function getTimelineBarHeight(entries: number, maximumEntries: number): number;
export function selectTimelineLabelIndices(bucketCount: number, maximumLabels?: number): number[];
export function getCitedLineSegments(text: string, citedLineNumbers: Iterable<number>): CitationSegment[];
