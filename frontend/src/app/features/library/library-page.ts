import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { BooksStore } from '../../core/books.store';

/** Curated list of common target languages — the user picks a destination to
 * read in, so a short trusted list beats free text (no guessing how the model
 * expects a language name spelled). "other" reveals a free-text fallback for
 * anything not listed. */
export const TARGET_LANG_PRESETS = [
  'Tiếng Việt',
  'Tiếng Anh',
  'Tiếng Pháp',
  'Tiếng Nhật',
  'Tiếng Hàn',
  'Tiếng Trung',
  'Tiếng Đức',
  'Tiếng Tây Ban Nha',
  'Tiếng Ý',
  'Tiếng Nga',
  'Tiếng Thái',
] as const;

@Component({
  selector: 'app-library-page',
  imports: [RouterLink],
  templateUrl: './library-page.html',
  styleUrl: './library-page.scss',
})
export class LibraryPage implements OnInit {
  private readonly router = inject(Router);
  readonly store = inject(BooksStore);

  readonly targetLangPresets = TARGET_LANG_PRESETS;

  readonly targetLangChoice = signal<string>('Tiếng Việt');
  readonly targetLangCustom = signal('');
  readonly targetLang = computed(() =>
    this.targetLangChoice() === 'other' ? this.targetLangCustom().trim() : this.targetLangChoice()
  );
  readonly error = signal<string | null>(null);

  ngOnInit(): void {
    void this.store.loadBooks();
  }

  async onFileSelected(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;

    if (!this.targetLang()) {
      this.error.set('Vui lòng nhập ngôn ngữ đích (chọn "Khác…" cần gõ tên ngôn ngữ).');
      return;
    }

    this.error.set(null);
    try {
      await this.store.upload(file, this.targetLang());
    } catch (err) {
      const detail = err instanceof HttpErrorResponse ? err.error?.detail : null;
      this.error.set(detail ? `Upload thất bại: ${detail}` : 'Upload thất bại — kiểm tra file và thử lại.');
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
