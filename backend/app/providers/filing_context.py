"""Conservative heading context for filing excerpts; unknown context stays unknown."""
import re
from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass
class Block:
    text: str
    heading: bool
    table: bool


@dataclass
class Passage:
    text: str
    offset: int
    section: str | None
    headings: list[str]
    scope: str
    segment: str | None
    fiscal_years: list[int]


class ContextualFiling(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.parts = []
        self.bold = []
        self.table = False
        self.blocks = []

    def flush(self):
        text = re.sub(r'\s+', ' ', ''.join(self.parts)).strip()
        if text:
            letters = re.sub(r'[^A-Za-z]', '', text)
            styled = bool(self.bold) and all(self.bold)
            heading = not self.table and len(text) < 180 and (styled or (len(letters) > 6 and letters.isupper()))
            self.blocks.append(Block(text, heading, self.table))
        self.parts, self.bold, self.table = [], [], False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('p', 'div', 'tr', 'h1', 'h2', 'h3', 'h4', 'br'):
            self.flush()
        parent = self.stack[-1] if self.stack else ('', False, False, False)
        style = attrs.get('style', '').lower().replace(' ', '')
        hidden = parent[1] or tag in ('script', 'style', 'ix:header') or 'display:none' in style
        bold = parent[2] or tag in ('b', 'strong', 'i', 'em', 'h1', 'h2', 'h3', 'h4') or 'font-weight:bold' in style or 'font-weight:700' in style or 'font-style:italic' in style
        table = parent[3] or tag == 'table'
        if tag not in ('br', 'hr', 'img', 'meta', 'link', 'input', 'wbr'):
            self.stack.append((tag, hidden, bold, table))

    def handle_endtag(self, tag):
        if tag in ('p', 'div', 'tr', 'h1', 'h2', 'h3', 'h4', 'table'):
            self.flush()
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, text):
        _, hidden, bold, table = self.stack[-1] if self.stack else ('', False, False, False)
        if not hidden:
            self.parts.append(text)
            if re.search(r'[A-Za-z]', text):
                self.bold.append(bold)
            self.table |= table

    def passages(self):
        self.flush()
        result = []
        section, area, segment = None, None, None
        years, headings = [], []
        for offset, block in enumerate(self.blocks):
            text = block.text
            if block.table:
                continue  # Table row labels must not become narrative headings.
            item = re.fullmatch(r'(?:PART\s+[IVX]+\s+)?ITEM\s+(\d+[A-Z]?)\.?\s*(.*)', text, re.I)
            if item:
                new_section = {'1': 'business', '1A': 'risks', '7': 'md&a'}.get(item[1].upper())
                if new_section != section:
                    section, area, segment, years, headings = new_section, None, None, [], []
                continue  # Repeated page headers do not reset the current subsection.
            if re.fullmatch(r'(?:PART\s+[IVX]+|\d+|[•·])', text, re.I):
                continue
            comparison = re.fullmatch(r'(?:Fiscal\s+)?Years?\s+(20\d{2})\s+(?:Compared\s+(?:with|to)|versus|vs\.?)\s+(?:Fiscal\s+Years?\s+)?(20\d{2})', text, re.I)
            if comparison:
                years = [int(comparison[1]), int(comparison[2])]
                continue
            if block.heading:
                upper = text.upper()
                if 'SUMMARY RESULTS OF OPERATIONS' in upper or 'CONSOLIDATED RESULTS OF OPERATIONS' in upper:
                    area, segment, years, headings = 'company', None, [], [text]
                elif 'SEGMENT RESULTS OF OPERATIONS' in upper:
                    area, segment, years, headings = 'segment', None, [], [text]
                elif upper in ('REPORTABLE SEGMENTS',):
                    continue
                elif upper == text and len(re.sub(r'[^A-Z]', '', text)) > 6:
                    # A new major heading ends a segment/summary scope. Do not infer
                    # consolidated attribution merely from a generic expenses heading.
                    area, segment, years, headings = None, None, [], [text]
                elif area == 'segment':
                    segment = text
                    headings = headings[:1] + [text]
                else:
                    headings = headings[:1] + [text]
                continue
            if len(text) < 80:
                continue
            scope = 'company' if area == 'company' else 'segment' if area == 'segment' and segment else 'unknown'
            passage_segment = segment
            # A consolidated discussion may include a narrower business metric.
            subject = re.match(r'^(.{2,70}?)\s+(?:gross margin|operating margin|revenue|operating income|operating expenses)\b', text, re.I)
            if subject and scope == 'company' and not re.match(r'^(?:revenue|cost of revenue|gross margin|operating income|operating expenses)\b', text, re.I):
                name = subject[1].strip()
                if name.lower() not in ('our', 'total', 'consolidated', 'the company', "the company's"):
                    scope, passage_segment = 'segment', name
            result.append(Passage(text, offset, section, list(headings), scope, passage_segment, list(years)))
        return result
