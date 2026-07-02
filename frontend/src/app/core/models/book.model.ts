export type BookStatus = 'uploaded' | 'extracted' | 'translating' | 'done' | 'error';
export type JobStatus = 'queued' | 'running' | 'done' | 'error' | 'cancelled';
export type SourceLang = 'en' | 'fr';

export interface Book {
  id: string;
  title: string;
  original_filename: string;
  source_lang: SourceLang;
  page_count: number | null;
  created_at: string;
  status: BookStatus;
}

export interface Job {
  id: string;
  book_id: string;
  status: JobStatus;
  current_stage: string | null;
  total_chunks: number | null;
  completed_chunks: number;
  failed_chunks: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}
