'use client';

import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';

export function SellerNavigation({ ariaLabel, children }: { ariaLabel: string; children: ReactNode }) {
  const [expanded, setExpanded] = useState(false);
  const navigationId = useId();
  const trigger = useRef<HTMLButtonElement>(null);

  function closeOnEscape(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== 'Escape' || !expanded) return;
    event.preventDefault();
    setExpanded(false);
    trigger.current?.focus();
  }

  return <>
    <button
      ref={trigger}
      className="seller-mobile-nav-toggle"
      type="button"
      aria-expanded={expanded}
      aria-controls={navigationId}
      onClick={() => setExpanded((value) => !value)}
    >
      Разделы
    </button>
    <nav
      id={navigationId}
      aria-label={ariaLabel}
      data-mobile-nav={expanded ? 'open' : 'closed'}
      onKeyDown={closeOnEscape}
      onClick={(event) => {
        if ((event.target as HTMLElement).closest('a')) setExpanded(false);
      }}
    >
      {children}
    </nav>
  </>;
}
