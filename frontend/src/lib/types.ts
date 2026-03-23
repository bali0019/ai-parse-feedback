export interface Document {
  document_id: string
  filename: string
  volume_path: string | null
  image_output_path: string | null
  page_count: number | null
  element_count: number | null
  status: string
  error_message: string | null
  uploaded_by: string | null
  use_case_name: string | null
  uploaded_at: string
  parsed_at: string | null
  updated_at: string
  parsed_result?: ParsedResult
  parsed_summary?: { page_count: number; element_count: number; has_parsed_result: boolean }
  feedback_stats?: { total_feedback: number; correct_count: number; issue_count: number }
}

export interface UseCaseSummary {
  use_case_name: string
  doc_count: number
  total_elements: number
  total_feedback: number
  total_issues: number
}

export interface QualityFlag {
  element_id: number
  check: string
  severity: string
  message: string
}

export interface ParsedResult {
  document: {
    pages: Page[]
    elements: Element[]
  }
  metadata?: Record<string, unknown>
}

export interface Page {
  id: number
  page_number?: number
  image_uri?: string
  header?: string
  footer?: string
}

export interface Element {
  id: number
  type: string
  content?: string
  description?: string
  bbox?: BBox[]
}

export interface BBox {
  page_id: number
  coord: number[] // [x1, y1, x2, y2]
}

export interface Feedback {
  feedback_id: string
  document_id: string
  element_id: number
  page_id: number
  element_type: string | null
  bbox_coords: number[] | null
  is_correct: boolean | null
  issue_category: string | null
  comment: string | null
  suggested_content: string | null
  suggested_type: string | null
  reviewer: string | null
  created_at: string
  updated_at: string
}

export interface PageData {
  page_id: number
  page_number: number
  total_pages: number
  image: { data_uri: string; width: number; height: number } | null
  image_uri: string | null
  elements: Element[]
  feedback: Record<number, Feedback>
  quality_flags: Record<number, QualityFlag[]>
}

export interface IssueCategory {
  value: string
  label: string
  description: string
}

export interface AppConfig {
  issue_categories: IssueCategory[]
  element_colors: Record<string, string>
}
