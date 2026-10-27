import { useTheme, type Theme } from "../hooks/use-theme";

const options: { value: Theme; label: string; icon: string }[] = [
  { value: "system", label: "System", icon: "◐" },
  { value: "light", label: "Light", icon: "☀" },
  { value: "dark", label: "Dark", icon: "☾" },
];

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <div className="theme-toggle" role="group" aria-label="Theme">
      {options.map((option) => (
        <button
          key={option.value}
          className={theme === option.value ? "active" : undefined}
          onClick={() => setTheme(option.value)}
          title={option.label}
          aria-pressed={theme === option.value}
        >
          <span className="theme-icon">{option.icon}</span>
          <span className="theme-label">{option.label}</span>
        </button>
      ))}
    </div>
  );
}
