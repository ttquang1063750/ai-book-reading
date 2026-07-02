import { Component, computed, inject, input, signal } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { catchError, exhaustMap, of, switchMap, takeWhile, timer } from 'rxjs';

import { BooksApiService } from '../../core/books-api.service';
import { BooksStore } from '../../core/books.store';
import { Job } from '../../core/models/book.model';

const POLL_INTERVAL_MS = 2000;

const isActive = (job: Job): boolean => job.status === 'queued' || job.status === 'running';

@Component({
  selector: 'app-job-progress-page',
  imports: [RouterLink],
  templateUrl: './job-progress-page.html',
  styleUrl: './job-progress-page.css',
})
export class JobProgressPage {
  /** Route param `:id`, bound via withComponentInputBinding. */
  readonly id = input.required<string>();

  private readonly api = inject(BooksApiService);
  private readonly store = inject(BooksStore);

  /** Bumped to restart the polling stream after a retry. */
  private readonly restart = signal(0);
  private readonly pollKey = computed(() => ({ bookId: this.id(), restart: this.restart() }));

  readonly job = toSignal<Job | null>(
    toObservable(this.pollKey).pipe(
      switchMap(({ bookId }) =>
        timer(0, POLL_INTERVAL_MS).pipe(
          exhaustMap(() => this.api.latestJobForBook$(bookId).pipe(catchError(() => of(null)))),
          takeWhile((job): job is Job => job !== null && isActive(job), true)
        )
      )
    ),
    { initialValue: null }
  );

  readonly isDone = computed(() => this.job()?.status === 'done');
  readonly isFailed = computed(
    () => this.job()?.status === 'error' || (this.job()?.failed_chunks ?? 0) > 0
  );
  readonly isRunning = computed(() => {
    const job = this.job();
    return job !== null && isActive(job);
  });

  readonly progressPercent = computed(() => {
    const job = this.job();
    if (!job?.total_chunks) return 0;
    return Math.round((job.completed_chunks / job.total_chunks) * 100);
  });

  readonly stageLabel = computed(() => {
    const labels: Record<string, string> = {
      extracting: 'Đang trích xuất nội dung PDF…',
      rough_translating: 'Đang dịch thô (dịch cả sách trước, chưa biên tập)…',
      polishing: 'Đang biên tập văn phong (dịch nháp đã xong, giờ viết lại tự nhiên hơn)…',
      assembling_html: 'Đang tạo HTML…',
      done: 'Hoàn thành',
    };
    const stage = this.job()?.current_stage;
    return stage ? (labels[stage] ?? stage) : 'Đang chuẩn bị…';
  });

  downloadUrl(): string {
    return `/api/books/${this.id()}/download`;
  }

  async retryFailed(): Promise<void> {
    const job = this.job();
    if (!job) return;
    await this.store.retryFailed(job.id);
    this.restart.update((n) => n + 1);
  }
}
