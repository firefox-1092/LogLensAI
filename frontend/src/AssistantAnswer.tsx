import type { ReactNode } from 'react';
import type { EvidenceReference } from './api';
import { parseAssistantMarkdown } from './markdown.mjs';
import type { InlineToken } from './markdown.mjs';
import { getCitedLineSegments } from './presentation.mjs';

function renderInline(tokens: InlineToken[], citedLines: Set<number>, onCitation: (line: number) => void): ReactNode[] {
  return tokens.flatMap((token, tokenIndex) => {
    const segments = token.type === 'code' ? [{ type: 'text' as const, value: token.value }] : getCitedLineSegments(token.value, citedLines);
    const content = segments.map((segment, segmentIndex) => segment.type === 'line'
      ? <button className="citation-link" type="button" key={`${tokenIndex}-${segmentIndex}`} aria-label={`Open cited log line ${segment.lineNumber}`} onClick={() => onCitation(segment.lineNumber)}>{segment.value}</button>
      : <span key={`${tokenIndex}-${segmentIndex}`}>{segment.value}</span>);
    if (token.type === 'strong') return [<strong key={tokenIndex}>{content}</strong>];
    if (token.type === 'emphasis') return [<em key={tokenIndex}>{content}</em>];
    if (token.type === 'code') return [<code key={tokenIndex}>{content}</code>];
    return content;
  });
}

export function AssistantAnswer({ answer, citedEvidence, onCitation }: {
  answer: string;
  citedEvidence: EvidenceReference[];
  onCitation: (line: number) => void;
}) {
  const citedLines = new Set(citedEvidence.map((item) => item.line_number));
  const blocks = parseAssistantMarkdown(answer).map((block, index) => {
    if (block.type === 'heading') {
      const heading = renderInline(block.tokens, citedLines, onCitation);
      const headingText = block.tokens.map((token) => token.value).join('').toLowerCase();
      const headingClass = headingText.includes('hypothes') || headingText.includes('explanation')
        ? 'answer-heading hypothesis-heading'
        : headingText.includes('observ') || headingText.includes('fact')
          ? 'answer-heading fact-heading'
          : 'answer-heading';
      if (block.level === 1) return <h1 className={headingClass} key={index}>{heading}</h1>;
      if (block.level === 2) return <h2 className={headingClass} key={index}>{heading}</h2>;
      return <h3 className={headingClass} key={index}>{heading}</h3>;
    }
    if (block.type === 'paragraph') return <p key={index}>{renderInline(block.tokens, citedLines, onCitation)}</p>;
    const items = block.items.map((tokens, itemIndex) => <li key={itemIndex}>{renderInline(tokens, citedLines, onCitation)}</li>);
    return block.type === 'ordered-list' ? <ol key={index}>{items}</ol> : <ul key={index}>{items}</ul>;
  });
  return <div className="assistant-answer">{blocks}</div>;
}
