import { Component, OnInit, ViewEncapsulation, computed, inject, input, signal } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { RouterLink } from '@angular/router';
import { catchError, of, switchMap } from 'rxjs';

import { BooksApiService } from '../../core/books-api.service';
import { Chapter } from '../../core/models/book.model';

export type ViewMode = 'mode-both' | 'mode-original' | 'mode-translated';

const MODES: { value: ViewMode; label: string }[] = [
  { value: 'mode-both', label: 'Song ngữ' },
  { value: 'mode-original', label: 'Bản gốc' },
  { value: 'mode-translated', label: 'Bản dịch' },
];

const FONT_SCALE_STORAGE_KEY = 'reader-font-scale';
const FONT_SCALE_MIN = 0.85;
const FONT_SCALE_MAX = 1.55;
const FONT_SCALE_STEP = 0.15;

@Component({
  selector: 'app-reader-page',
  imports: [RouterLink],
  templateUrl: './reader-page.html',
  styleUrl: './reader-page.scss',
  // The book HTML arrives via [innerHTML]; styles must reach it, so no emulated scoping.
  encapsulation: ViewEncapsulation.None,
})
export class ReaderPage implements OnInit {
  /** Route param `:id`, bound via withComponentInputBinding. */
  readonly id = input.required<string>();

  private readonly api = inject(BooksApiService);
  private readonly sanitizer = inject(DomSanitizer);

  readonly modes = MODES;
  readonly mode = signal<ViewMode>('mode-both');

  readonly chapters = signal<Chapter[]>([]);
  readonly showToc = signal(false);

  readonly fontScale = signal(this.readStoredFontScale());
  readonly canDecreaseFont = computed(() => this.fontScale() > FONT_SCALE_MIN + 0.001);
  readonly canIncreaseFont = computed(() => this.fontScale() < FONT_SCALE_MAX - 0.001);

  decreaseFont(): void {
    this.setFontScale(this.fontScale() - FONT_SCALE_STEP);
  }

  increaseFont(): void {
    this.setFontScale(this.fontScale() + FONT_SCALE_STEP);
  }

  private setFontScale(value: number): void {
    const clamped = Math.min(FONT_SCALE_MAX, Math.max(FONT_SCALE_MIN, value));
    this.fontScale.set(clamped);
    localStorage.setItem(FONT_SCALE_STORAGE_KEY, String(clamped));
  }

  private readStoredFontScale(): number {
    const stored = Number(localStorage.getItem(FONT_SCALE_STORAGE_KEY));
    return stored >= FONT_SCALE_MIN && stored <= FONT_SCALE_MAX ? stored : 1;
  }

  async ngOnInit(): Promise<void> {
    try {
      this.chapters.set(await this.api.getChapters(this.id()));
    } catch {
      this.chapters.set([]);
    }
  }

  toggleToc(): void {
    this.showToc.update((v) => !v);
  }

  goToChapter(headingBlockId: number): void {
    this.showToc.set(false);
    // Wait a frame so the TOC panel's removal (and the resulting layout shift)
    // is applied before measuring where to scroll to — otherwise the target
    // lands short by roughly the panel's height.
    requestAnimationFrame(() => {
      document.getElementById(`block-${headingBlockId}`)?.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      });
    });
  }

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

  readonly safeHtml = computed<SafeHtml | null>(() => {
    const raw = this.rawHtml();
    if (!raw) return null;
    // Angular's sanitize() strips id/data-* attributes we rely on (chapter anchors,
    // page markers). Safe to bypass: this HTML is generated entirely by our own
    // backend, which escapes all extracted text — no untrusted third-party content.
    return this.sanitizer.bypassSecurityTrustHtml(raw);
  });

  reload(): void {
    this.refresh.update((n) => n + 1);
  }
}
