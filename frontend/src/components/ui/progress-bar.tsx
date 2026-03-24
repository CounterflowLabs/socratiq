import { clsx } from "clsx";

export function ProgressBar({
  value,
  max = 100,
  className,
}: {
  value: number;
  max?: number;
  className?: string;
}) {
  return (
    <div className={clsx("h-1.5 bg-gray-100 rounded-full overflow-hidden", className)}>
      <div
        className="h-full bg-blue-600 rounded-full transition-all duration-500"
        style={{ width: `${(value / max) * 100}%` }}
      />
    </div>
  );
}
