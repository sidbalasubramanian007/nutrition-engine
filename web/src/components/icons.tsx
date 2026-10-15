// 16px inline icons; they inherit color via currentColor. Always used inside labelled buttons.

export function LockIcon({ filled }: { filled: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      {filled ? (
        <>
          <path d="M5 7V5a3 3 0 0 1 6 0v2" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          <rect x="3" y="7" width="10" height="7" rx="1.5" fill="currentColor" />
        </>
      ) : (
        <>
          <path d="M5 7V5a3 3 0 0 1 5.8-1.1" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          <rect x="3.75" y="7.75" width="8.5" height="5.5" rx="1.25" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </>
      )}
    </svg>
  );
}

export function RemoveIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
