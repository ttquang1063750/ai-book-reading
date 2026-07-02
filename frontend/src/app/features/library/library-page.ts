import { Component, OnInit, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { BooksStore } from '../../core/books.store';
import { SourceLang } from '../../core/models/book.model';

@Component({
  selector: 'app-library-page',
  imports: [RouterLink],
  templateUrl: './library-page.html',
  styleUrl: './library-page.css',
})
export class LibraryPage implements OnInit {
  private readonly router = inject(Router);
  readonly store = inject(BooksStore);

  readonly sourceLang = signal<SourceLang>('en');
  readonly error = signal<string | null>(null);

  ngOnInit(): void {
    void this.store.loadBooks();
  }

  async onFileSelected(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;

    this.error.set(null);
    try {
      await this.store.upload(file, this.sourceLang());
    } catch {
      this.error.set('Upload thất bại — kiểm tra file PDF và thử lại.');
    }
  }

  async translate(bookId: string): Promise<void> {
    this.error.set(null);
    try {
      await this.store.startTranslation(bookId);
      await this.router.navigate(['/books', bookId, 'job']);
    } catch {
      this.error.set('Không thể bắt đầu dịch — có thể đang có job chạy cho sách này.');
    }
  }

  async remove(bookId: string, title: string): Promise<void> {
    if (!confirm(`Xoá sách "${title}"? Bản dịch và file gốc sẽ bị xoá vĩnh viễn.`)) return;
    this.error.set(null);
    try {
      await this.store.deleteBook(bookId);
    } catch {
      this.error.set('Không xoá được — sách có thể đang được dịch.');
    }
  }

  downloadUrl(bookId: string): string {
    return `/api/books/${bookId}/download`;
  }

  statusLabel(status: string): string {
    const labels: Record<string, string> = {
      uploaded: 'Đã tải lên',
      extracted: 'Đã trích xuất',
      translating: 'Đang dịch',
      done: 'Hoàn thành',
      error: 'Lỗi',
    };
    return labels[status] ?? status;
  }
}
