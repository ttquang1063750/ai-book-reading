import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, firstValueFrom } from 'rxjs';

import {
  Book,
  Chapter,
  ChapterSummary,
  ChatMessage,
  IndexStatus,
  Job,
  Lang,
  RetranslatedBlock,
} from './models/book.model';

@Injectable({ providedIn: 'root' })
export class BooksApiService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api';

  listBooks(): Promise<Book[]> {
    return firstValueFrom(this.http.get<Book[]>(`${this.base}/books`));
  }

  getBook(bookId: string): Promise<Book> {
    return firstValueFrom(this.http.get<Book>(`${this.base}/books/${bookId}`));
  }

  deleteBook(bookId: string): Promise<void> {
    return firstValueFrom(this.http.delete<void>(`${this.base}/books/${bookId}`));
  }

  uploadBook(file: File, targetLang: Lang): Promise<Book> {
    const form = new FormData();
    form.append('file', file);
    form.append('target_lang', targetLang);
    return firstValueFrom(this.http.post<Book>(`${this.base}/books`, form));
  }

  startTranslation(bookId: string): Promise<Job> {
    return firstValueFrom(this.http.post<Job>(`${this.base}/books/${bookId}/translate`, null));
  }

  getJob(jobId: string): Promise<Job> {
    return firstValueFrom(this.http.get<Job>(`${this.base}/jobs/${jobId}`));
  }

  getLatestJobForBook(bookId: string): Promise<Job> {
    return firstValueFrom(this.http.get<Job>(`${this.base}/books/${bookId}/job`));
  }

  /** Observable variant used by the polling stream on the job progress page. */
  latestJobForBook$(bookId: string): Observable<Job> {
    return this.http.get<Job>(`${this.base}/books/${bookId}/job`);
  }

  retryFailed(jobId: string): Promise<Job> {
    return firstValueFrom(this.http.post<Job>(`${this.base}/jobs/${jobId}/retry-failed`, null));
  }

  cancelJob(jobId: string): Promise<Job> {
    return firstValueFrom(this.http.post<Job>(`${this.base}/jobs/${jobId}/cancel`, null));
  }

  getBookHtml(bookId: string): Promise<string> {
    return firstValueFrom(
      this.http.get(`${this.base}/books/${bookId}/html`, { responseType: 'text' })
    );
  }

  /** Observable variant used by the reader page's reactive fetch. */
  bookHtml$(bookId: string): Observable<string> {
    return this.http.get(`${this.base}/books/${bookId}/html`, { responseType: 'text' });
  }

  getChapters(bookId: string): Promise<Chapter[]> {
    return firstValueFrom(this.http.get<Chapter[]>(`${this.base}/books/${bookId}/chapters`));
  }

  retranslateBlock(bookId: string, blockId: number): Promise<RetranslatedBlock> {
    return firstValueFrom(
      this.http.post<RetranslatedBlock>(
        `${this.base}/books/${bookId}/blocks/${blockId}/retranslate`,
        null
      )
    );
  }

  getSummaries(bookId: string): Promise<ChapterSummary[]> {
    return firstValueFrom(
      this.http.get<ChapterSummary[]>(`${this.base}/books/${bookId}/summaries`)
    );
  }

  startSummarize(bookId: string, force = false): Promise<Job> {
    const suffix = force ? '?force=true' : '';
    return firstValueFrom(
      this.http.post<Job>(`${this.base}/books/${bookId}/summarize${suffix}`, null)
    );
  }

  getIndexStatus(bookId: string): Promise<IndexStatus> {
    return firstValueFrom(this.http.get<IndexStatus>(`${this.base}/books/${bookId}/index-status`));
  }

  startIndexing(bookId: string): Promise<Job> {
    return firstValueFrom(this.http.post<Job>(`${this.base}/books/${bookId}/index`, null));
  }

  getChatHistory(bookId: string): Promise<ChatMessage[]> {
    return firstValueFrom(
      this.http.get<ChatMessage[]>(`${this.base}/books/${bookId}/chat/history`)
    );
  }

  clearChatHistory(bookId: string): Promise<void> {
    return firstValueFrom(this.http.delete<void>(`${this.base}/books/${bookId}/chat/history`));
  }

  /**
   * Streams the assistant's reply via fetch()+ReadableStream — HttpClient has
   * no incremental-body API, so this bypasses it (unlike every other method
   * in this service) purely for that reason.
   */
  async streamChatMessage(
    bookId: string,
    message: string,
    onToken: (token: string) => void
  ): Promise<void> {
    const response = await fetch(`${this.base}/books/${bookId}/chat/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    });
    if (!response.ok || !response.body) {
      const detail = await response.text().catch(() => '');
      throw new Error(detail || `Chat request failed: ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      onToken(decoder.decode(value, { stream: true }));
    }
  }
}
