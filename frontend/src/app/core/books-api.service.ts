import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, firstValueFrom } from 'rxjs';

import { Book, Job, SourceLang } from './models/book.model';

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

  uploadBook(file: File, sourceLang: SourceLang): Promise<Book> {
    const form = new FormData();
    form.append('file', file);
    form.append('source_lang', sourceLang);
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

  getBookHtml(bookId: string): Promise<string> {
    return firstValueFrom(
      this.http.get(`${this.base}/books/${bookId}/html`, { responseType: 'text' })
    );
  }

  /** Observable variant used by the reader page's reactive fetch. */
  bookHtml$(bookId: string): Observable<string> {
    return this.http.get(`${this.base}/books/${bookId}/html`, { responseType: 'text' });
  }
}
