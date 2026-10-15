import "./Segmented.css";

interface Props<T extends string> {
  /** Shared radio name; must be unique on the page */
  name: string;
  /** Accessible group name (visually hidden) */
  legend: string;
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}

/** A segmented control built from real radio inputs, so arrow keys and screen readers work natively. */
export default function Segmented<T extends string>({ name, legend, options, value, onChange, className }: Props<T>) {
  return (
    <fieldset className={`segmented${className ? ` ${className}` : ""}`}>
      <legend className="visually-hidden">{legend}</legend>
      {options.map((option) => (
        <label key={option.value} className="segmented-option">
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={value === option.value}
            onChange={() => onChange(option.value)}
          />
          <span>{option.label}</span>
        </label>
      ))}
    </fieldset>
  );
}
