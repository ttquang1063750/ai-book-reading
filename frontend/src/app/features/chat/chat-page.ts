import {
  Component,
  ElementRef,
  OnInit,
  computed,
  effect,
  inject,
  input,
  signal,
  viewChild,
} from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { exhaustMap, of, switchMap, takeWhile, timer } from 'rxjs';

import { BooksApiService } from '../../core/books-api.service';
import { ChatMessage, IndexStatus, Job } from '../../core/models/book.model';
import { ChatMarkdownPipe } from './chat-markdown';

const POLL_INTERVAL_MS = 2000;

const isActive = (job: Job): boolean => job.status === 'queued' || job.status === 'running';

@Component({
  selector: 'app-chat-page',
  imports: [RouterLink, ChatMarkdownPipe],
  templateUrl: './chat-page.html',
  styleUrl: './chat-page.scss',
})
export class ChatPage implements OnInit {
  readonly id = input.required<string>();

  private readonly api = inject(BooksApiService);

  private readonly indexStatusSignal = signal<IndexStatus | null>(null);
  readonly loadingIndexStatus = computed(() => this.indexStatusSignal() === null);
  readonly indexStatus = computed(() => this.indexStatusSignal());

  readonly messages = signal<ChatMessage[]>([]);
  readonly draft = signal('');
  readonly streamingReply = signal<string | null>(null);
  readonly sending = computed(() => this.streamingReply() !== null);
  readonly error = signal<string | null>(null);
  readonly indexingError = signal<string | null>(null);

  private readonly messageListEl = viewChild<ElementRef<HTMLDivElement>>('messageList');

  /** Guards ensureIndexing() so it only fires the auto-trigger once per page visit. */
  private autoIndexTriggered = false;

  /** Bumped to (re)start the job-polling stream — on auto-trigger or "Đánh lại index". */
  private readonly runToken = signal(0);
  private readonly runKey = computed(() => ({ bookId: this.id(), token: this.runToken() }));

  private readonly job = toSignal<Job | null>(
    toObservable(this.runKey).pipe(
      switchMap(({ token }) => {
        if (token === 0) return of(null);
        return timer(0, POLL_INTERVAL_MS).pipe(
          exhaustMap(() => this.api.getLatestJobForBook(this.id()).then((j) => j, () => null)),
          takeWhile((j): j is Job => j !== null && isActive(j), true)
        );
      })
    ),
    { initialValue: null }
  );

  readonly isIndexing = computed(() => {
    const j = this.job();
    return j !== null && isActive(j) && j.job_type === 'index';
  });

  readonly indexProgressText = computed(() => {
    const j = this.job();
    if (!j?.total_chunks) return 'Đang chuẩn bị…';
    return `${j.completed_chunks}/${j.total_chunks} đoạn`;
  });

  constructor() {
    // Refresh index status once the polled indexing job reaches a terminal state.
    effect(() => {
      const j = this.job();
      if (j !== null && !isActive(j)) {
        void this.loadIndexStatus();
      }
    });

    // Keep the message list pinned to the latest content — new messages and
    // incoming stream tokens both need this, now that the list scrolls in its
    // own fixed-height region instead of the whole page. requestAnimationFrame
    // defers past Angular's DOM update for the new content (same fix as the
    // reader page's TOC-scroll timing issue).
    effect(() => {
      this.messages();
      this.streamingReply();
      const el = this.messageListEl()?.nativeElement;
      if (el) {
        requestAnimationFrame(() => {
          el.scrollTop = el.scrollHeight;
        });
      }
    });
  }

  ngOnInit(): void {
    void this.loadIndexStatus();
    void this.loadHistory();
  }

  async loadIndexStatus(): Promise<void> {
    const status = await this.api.getIndexStatus(this.id());
    this.indexStatusSignal.set(status);
    if (!status.indexed) {
      void this.ensureIndexing();
    }
  }

  async loadHistory(): Promise<void> {
    this.messages.set(await this.api.getChatHistory(this.id()));
  }

  /** Auto-triggers indexing the first time this page sees an un-indexed book —
   * translation already chains this automatically, so this is mostly a fallback
   * for books translated before that existed. A 409 here just means a job
   * (most likely that same auto-chained one) is already running, which is fine. */
  private async ensureIndexing(): Promise<void> {
    if (this.autoIndexTriggered) return;
    this.autoIndexTriggered = true;
    try {
      await this.api.startIndexing(this.id());
    } catch {
      // already indexing (409) or book not ready yet — polling below will reflect reality.
    }
    this.runToken.update((n) => n + 1);
  }

  /** Manual "Đánh lại index" — surfaces errors since this is a deliberate user action. */
  async startIndexing(): Promise<void> {
    this.indexingError.set(null);
    try {
      await this.api.startIndexing(this.id());
      this.runToken.update((n) => n + 1);
    } catch {
      this.indexingError.set(
        'Không thể bắt đầu đánh index — sách có thể đang có job khác chạy.'
      );
    }
  }

  async send(): Promise<void> {
    const text = this.draft().trim();
    if (!text || this.sending()) return;

    this.error.set(null);
    this.draft.set('');
    this.messages.update((msgs) => [
      ...msgs,
      { role: 'user', content: text, timestamp: new Date().toISOString() },
    ]);
    this.streamingReply.set('');

    try {
      await this.api.streamChatMessage(this.id(), text, (token) =>
        this.streamingReply.update((s) => (s ?? '') + token)
      );
      const finalReply = this.streamingReply() ?? '';
      this.messages.update((msgs) => [
        ...msgs,
        { role: 'assistant', content: finalReply, timestamp: new Date().toISOString() },
      ]);
    } catch {
      this.error.set('Không thể lấy câu trả lời — kiểm tra Ollama có đang chạy không.');
    } finally {
      this.streamingReply.set(null);
    }
  }

  async clearHistory(): Promise<void> {
    await this.api.clearChatHistory(this.id());
    this.messages.set([]);
  }
}
