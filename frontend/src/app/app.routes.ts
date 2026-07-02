import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'library' },
  {
    path: 'library',
    loadComponent: () => import('./features/library/library-page').then((m) => m.LibraryPage),
  },
  {
    path: 'books/:id/job',
    loadComponent: () =>
      import('./features/job-progress/job-progress-page').then((m) => m.JobProgressPage),
  },
  {
    path: 'books/:id/read',
    loadComponent: () => import('./features/reader/reader-page').then((m) => m.ReaderPage),
  },
  {
    path: 'books/:id/summary',
    loadComponent: () => import('./features/summary/summary-page').then((m) => m.SummaryPage),
  },
  {
    path: 'books/:id/chat',
    loadComponent: () => import('./features/chat/chat-page').then((m) => m.ChatPage),
  },
  { path: '**', redirectTo: 'library' },
];
