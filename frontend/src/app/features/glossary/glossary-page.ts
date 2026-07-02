import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { BooksApiService } from '../../core/books-api.service';

interface Term {
  source: string;
  translated: string;
}

@Component({
  selector: 'app-glossary-page',
  imports: [RouterLink],
  templateUrl: './glossary-page.html',
  styleUrl: './glossary-page.css',
})
export class GlossaryPage implements OnInit {
  readonly id = input.required<string>();

  private readonly api = inject(BooksApiService);

  private readonly termsSignal = signal<Term[] | null>(null);
  readonly loading = computed(() => this.termsSignal() === null);
  readonly terms = computed(() => this.termsSignal() ?? []);

  async ngOnInit(): Promise<void> {
    const glossary = await this.api.getGlossary(this.id());
    const terms = Object.entries(glossary.terms)
      .map(([source, translated]) => ({ source, translated }))
      .sort((a, b) => a.source.localeCompare(b.source));
    this.termsSignal.set(terms);
  }
}
