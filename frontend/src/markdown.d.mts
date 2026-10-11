export type InlineToken = { type: 'text' | 'strong' | 'emphasis' | 'code'; value: string };

export type MarkdownBlock =
  | { type: 'heading'; level: number; tokens: InlineToken[] }
  | { type: 'paragraph'; tokens: InlineToken[] }
  | { type: 'ordered-list' | 'unordered-list'; items: InlineToken[][] };

export function parseAssistantMarkdown(source: string): MarkdownBlock[];
