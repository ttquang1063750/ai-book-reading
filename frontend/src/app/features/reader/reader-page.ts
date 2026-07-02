import { Component, SecurityContext, ViewEncapsulation, computed, inject, input, signal } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { DomSanitizer } from '@angular/platform-browser';
import { RouterLink } from '@angular/router';
import { catchError, of, switchMap } from 'rxjs';

import { BooksApiService } from '../../core/books-api.service';

export type ViewMode = 'mode-both' | 'mode-original' | 'mode-translated';

const MODES: { value: ViewMode; label: string }[] = [
  { value: 'mode-both', label: 'Song ngữ' },
  { value: 'mode-original', label: 'Bản gốc' },
  { value: 'mode-translated', label: 'Bản dịch' },
];

@Component({
  selector: 'app-reader-page',
  imports: [RouterLink],
  templateUrl: './reader-page.html',
  styleUrl: './reader-page.css',
  // The book HTML arrives via [innerHTML]; styles must reach it, so no emulated scoping.
  encapsulation: ViewEncapsulation.None,
})
export class ReaderPage {
  /** Route param `:id`, bound via withComponentInputBinding. */
  readonly id = input.required<string>();

  private readonly api = inject(BooksApiService);
  private readonly sanitizer = inject(DomSanitizer);

  readonly modes = MODES;
  readonly mode = signal<ViewMode>('mode-both');

  /** Bumped by the reload button to re-fetch partially translated content. */
  private readonly refresh = signal(0);
  private readonly fetchKey = computed(() => ({ bookId: this.id(), refresh: this.refresh() }));

  /** undefined = loading, null = failed, string = fragment HTML. */
  private readonly rawHtml = toSignal<string | null | undefined>(
    toObservable(this.fetchKey).pipe(
      switchMap(({ bookId }) => this.api.bookHtml$(bookId).pipe(catchError(() => of(null))))
    ),
    { initialValue: undefined }
  );

  readonly loading = computed(() => this.rawHtml() === undefined);
  readonly failed = computed(() => this.rawHtml() === null);

  /** Translation still in progress — some blocks arrived without a translation. */
  readonly hasPending = computed(() => this.rawHtml()?.includes('class="pending"') ?? false);

  readonly safeHtml = computed(() => {
    const raw = this.rawHtml();
    return raw ? this.sanitizer.sanitize(SecurityContext.HTML, raw) : null;
  });

  reload(): void {
    this.refresh.update((n) => n + 1);
  }
}
