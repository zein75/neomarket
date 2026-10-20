import type { ButtonHTMLAttributes, ChangeEvent, InputHTMLAttributes, ReactNode } from 'react';

type ButtonTone = 'primary' | 'secondary' | 'danger';

export function Button({ tone = 'secondary', children, className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: ButtonTone; children: ReactNode }) {
  return <button {...props} className={`nm-button nm-button-${tone} ${className}`.trim()}>{children}</button>;
}

export function StatusBadge({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'success' | 'warning' | 'danger' }) {
  return <span className={`nm-status nm-status-${tone}`} role="status">{children}</span>;
}

export function Price({ minor, currency = 'RUB' }: { minor: number; currency?: string }) {
  return <span className="nm-price">{new Intl.NumberFormat('ru-RU', { style: 'currency', currency, maximumFractionDigits: 0 }).format(minor / 100)}</span>;
}

export function QuantityStepper({ value, min = 1, max = 99, disabled = false, onChange, label = 'Количество', className = '' }: { value: number; min?: number; max?: number; disabled?: boolean; onChange: (value: number) => void; label?: string; className?: string }) {
  const setValue = (next: number) => onChange(Math.min(max, Math.max(min, Number.isFinite(next) ? Math.trunc(next) : min)));
  const handleInput = (event: ChangeEvent<HTMLInputElement>) => setValue(Number(event.target.value));
  return <div className={`nm-quantity-stepper ${className}`.trim()} role="group" aria-label={label}>
    <button type="button" onClick={() => setValue(value - 1)} disabled={disabled || value <= min} aria-label={`${label}: уменьшить`}>−</button>
    <input type="number" min={min} max={max} value={value} onChange={handleInput} disabled={disabled} aria-label={label} {...({ inputMode: 'numeric' } satisfies InputHTMLAttributes<HTMLInputElement>)} />
    <button type="button" onClick={() => setValue(value + 1)} disabled={disabled || value >= max} aria-label={`${label}: увеличить`}>+</button>
  </div>;
}
