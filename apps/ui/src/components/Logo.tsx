export function LogoHorizontal({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 220 60" fill="none" xmlns="http://www.w3.org/2000/svg" className={className}>
      <polyline points="27,12 15,12 3,30 15,48 27,48" stroke="#2563eb" strokeWidth="7" strokeLinejoin="miter" strokeLinecap="butt" />
      <polyline points="33,48 45,48 57,30 45,12 33,12" stroke="#2563eb" strokeWidth="7" strokeLinejoin="miter" strokeLinecap="butt" />
      <circle cx="21" cy="30" r="3.5" fill="#2563eb" />
      <circle cx="30" cy="30" r="3.5" fill="#2563eb" />
      <circle cx="39" cy="30" r="3.5" fill="#2563eb" />
      <text
        x="70"
        y="42"
        fontFamily="system-ui, -apple-system, sans-serif"
        fontSize="34"
        fontWeight="800"
        fill="currentColor"
        letterSpacing="-1"
      >
        Encodr
      </text>
    </svg>
  );
}

export function LogoStacked({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 200 160" fill="none" xmlns="http://www.w3.org/2000/svg" className={className}>
      <polyline points="95,33 77,33 59,60 77,87 95,87" stroke="#2563eb" strokeWidth="10" strokeLinejoin="miter" strokeLinecap="butt" />
      <polyline points="105,87 123,87 141,60 123,33 105,33" stroke="#2563eb" strokeWidth="10" strokeLinejoin="miter" strokeLinecap="butt" />
      <circle cx="86" cy="60" r="5" fill="#2563eb" />
      <circle cx="100" cy="60" r="5" fill="#2563eb" />
      <circle cx="114" cy="60" r="5" fill="#2563eb" />
      <text
        x="100"
        y="140"
        fontFamily="system-ui, -apple-system, sans-serif"
        fontSize="48"
        fontWeight="800"
        fill="currentColor"
        textAnchor="middle"
        letterSpacing="-1.5"
      >
        Encodr
      </text>
    </svg>
  );
}
