import { Injectable, effect, signal } from '@angular/core';

const STORAGE_KEY = 'theme-dark';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly isDark = signal(this.readInitial());

  constructor() {
    // Applies to <html> (document.documentElement === :root), so every page's
    // `:root.dark { --color-*: ... }` override in styles.scss takes effect app-wide.
    effect(() => {
      document.documentElement.classList.toggle('dark', this.isDark());
      localStorage.setItem(STORAGE_KEY, this.isDark() ? '1' : '0');
    });
  }

  toggle(): void {
    this.isDark.update((v) => !v);
  }

  private readInitial(): boolean {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored !== null) return stored === '1';
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
  }
}
