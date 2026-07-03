export type BookStatus = 'uploaded' | 'extracted' | 'translating' | 'done' | 'error';
export type JobStatus = 'queued' | 'running' | 'done' | 'error' | 'cancelled';

/** Free text (e.g. "Tiếng Anh", "Japanese", "Tiếng Đức") — any language the model supports,
 * not a fixed enum. */
export type Lang = string;

export interface Book {
  id: string;
  title: string;
  original_filename: string;
  source_lang: Lang;
  target_lang: Lang;
  page_count: number | null;
  created_at: string;
  status: BookStatus;
}

export type JobType = 'translate' | 'summarize' | 'index';

export interface Job {
  id: string;
  book_id: string;
  job_type: JobType;
  status: JobStatus;
  current_stage: string | null;
  total_chunks: number | null;
  completed_chunks: number;
  failed_chunks: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChapterSummary {
  heading_block_id: number;
  title: string;
  summary: string | null;
}

export interface Chapter {
  heading_block_id: number;
  title: string;
}

export interface IndexStatus {
  indexed: boolean;
  chunk_count: number;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

export interface RetranslatedBlock {
  id: number;
  translated_text: string | null;
  translation_error: boolean;
}
