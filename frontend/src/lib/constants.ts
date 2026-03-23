/**
 * Shared design constants — single source of truth for the frontend.
 * Backend canonical values are in backend/config.py.
 */

export const ELEMENT_COLORS: Record<string, string> = {
  section_header: '#FF6B6B',
  text: '#4ECDC4',
  figure: '#45B7D1',
  caption: '#96CEB4',
  page_footer: '#FFEAA7',
  page_header: '#DDA0DD',
  table: '#98D8C8',
  list: '#F7DC6F',
  default: '#BDC3C7',
}

export function getElementColor(type: string): string {
  return ELEMENT_COLORS[type.toLowerCase()] || ELEMENT_COLORS.default
}

export const ELEMENT_TYPES = [
  'section_header', 'text', 'table', 'figure',
  'caption', 'list', 'page_header', 'page_footer',
] as const
