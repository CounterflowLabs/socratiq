import { clsx } from "clsx";

const colorMap: Record<string, string> = {
  blue: "bg-blue-50 text-blue-700",
  green: "bg-emerald-50 text-emerald-700",
  orange: "bg-amber-50 text-amber-700",
  red: "bg-red-50 text-red-700",
  violet: "bg-violet-50 text-violet-700",
  gray: "bg-gray-100 text-gray-600",
};

export function Badge({
  children,
  color = "blue",
}: {
  children: React.ReactNode;
  color?: string;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium",
        colorMap[color] || colorMap.blue
      )}
    >
      {children}
    </span>
  );
}
