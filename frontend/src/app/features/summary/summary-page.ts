import { Component, OnInit, computed, effect, inject, input, signal } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { catchError, exhaustMap, of, switchMap, takeWhile, timer } from 'rxjs';

import { BooksApiService } from '../../core/books-api.service';
import { ChapterSummary, Job } from '../../core/models/book.model';

const POLL_INTERVAL_MS = 2000;

const isActive = (job: Job): boolean => job.status === 'queued' || job.status === 'running';

@Component({
  selector: 'app-summary-page',
  imports: [RouterLink],
  templateUrl: './summary-page.html',
  styleUrl: './summary-page.scss',
})
export class SummaryPage implements OnInit {
  readonly id = input.required<string>();

  private readonly api = inject(BooksApiService);

  /** Bumped after clicking "Tạo tóm tắt" to (re)start the job-polling stream. */
  private readonly runToken = signal(0);
  private readonly runKey = computed(() => ({ bookId: this.id(), token: this.runToken() }));

  private readonly summariesSignal = signal<ChapterSummary[] | null>(null);
  readonly loadingSummaries = computed(() => this.summariesSignal() === null);
  readonly summaries = computed(() => this.summariesSignal() ?? []);
  readonly error = signal<string | null>(null);

  /** null = no job started this session (or none active). */
  private readonly job = toSignal<Job | null>(
    toObservable(this.runKey).pipe(
      switchMap(({ token }) => {
        if (token === 0) return of(null); // don't poll until the user starts a run
        return timer(0, POLL_INTERVAL_MS).pipe(
          exhaustMap(() => this.api.getLatestJobForBook(this.id()).then(
            (j) => j, () => null
          )),
          takeWhile((j): j is Job => j !== null && isActive(j), true)
        );
      })
    ),
    { initialValue: null }
  );

  readonly isRunning = computed(() => {
    const j = this.job();
    return j !== null && isActive(j) && j.job_type === 'summarize';
  });

  readonly progressText = computed(() => {
    const j = this.job();
    if (!j?.total_chunks) return 'Đang chuẩn bị…';
    return `${j.completed_chunks}/${j.total_chunks} chương`;
  });

  constructor() {
    // Refresh the summary list whenever the polled job transitions to a terminal state.
    effect(() => {
      const j = this.job();
      if (j !== null && !isActive(j)) {
        void this.load();
      }
    });
  }

  ngOnInit(): void {
    void this.load();
  }

  async load(): Promise<void> {
    this.summariesSignal.set(await this.api.getSummaries(this.id()));
  }

  async start(force = false): Promise<void> {
    this.error.set(null);
    try {
      await this.api.startSummarize(this.id(), force);
      this.runToken.update((n) => n + 1);
    } catch {
      this.error.set('Không thể tạo tóm tắt — sách có thể chưa dịch xong hoặc đang có job khác chạy.');
    }
  }
}
