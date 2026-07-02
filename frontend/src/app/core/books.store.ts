import { Injectable, computed, inject, signal } from '@angular/core';

import { BooksApiService } from './books-api.service';
import { Book, Job, SourceLang } from './models/book.model';

@Injectable({ providedIn: 'root' })
export class BooksStore {
  private readonly api = inject(BooksApiService);

  private readonly booksSignal = signal<Book[]>([]);
  readonly books = this.booksSignal.asReadonly();

  private readonly loadingSignal = signal(false);
  readonly loading = this.loadingSignal.asReadonly();

  private readonly uploadingSignal = signal(false);
  readonly uploading = this.uploadingSignal.asReadonly();

  private readonly activeJobSignal = signal<Job | null>(null);
  readonly activeJob = this.activeJobSignal.asReadonly();

  readonly isJobActive = computed(() => {
    const status = this.activeJobSignal()?.status;
    return status === 'queued' || status === 'running';
  });

  async loadBooks(): Promise<void> {
    this.loadingSignal.set(true);
    try {
      this.booksSignal.set(await this.api.listBooks());
    } finally {
      this.loadingSignal.set(false);
    }
  }

  async upload(file: File, sourceLang: SourceLang): Promise<Book> {
    this.uploadingSignal.set(true);
    try {
      const book = await this.api.uploadBook(file, sourceLang);
      this.booksSignal.update((books) => [book, ...books]);
      return book;
    } finally {
      this.uploadingSignal.set(false);
    }
  }

  async deleteBook(bookId: string): Promise<void> {
    await this.api.deleteBook(bookId);
    this.booksSignal.update((books) => books.filter((b) => b.id !== bookId));
  }

  async startTranslation(bookId: string): Promise<Job> {
    const job = await this.api.startTranslation(bookId);
    this.activeJobSignal.set(job);
    this.patchBook(bookId, { status: 'translating' });
    return job;
  }

  async retryFailed(jobId: string): Promise<Job> {
    const job = await this.api.retryFailed(jobId);
    this.activeJobSignal.set(job);
    this.patchBook(job.book_id, { status: 'translating' });
    return job;
  }

  /** One-shot fetch of a book's latest job; page components schedule the polling. */
  async pollLatestJob(bookId: string): Promise<Job | null> {
    try {
      const job = await this.api.getLatestJobForBook(bookId);
      this.activeJobSignal.set(job);
      return job;
    } catch {
      this.activeJobSignal.set(null);
      return null;
    }
  }

  async refreshBook(bookId: string): Promise<void> {
    const book = await this.api.getBook(bookId);
    this.patchBook(bookId, book);
  }

  private patchBook(bookId: string, patch: Partial<Book>): void {
    this.booksSignal.update((books) =>
      books.map((b) => (b.id === bookId ? { ...b, ...patch } : b))
    );
  }
}
