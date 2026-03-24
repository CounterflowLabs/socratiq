import { clsx } from "clsx";

export function Card({
  children,
  className,
  onClick,
  hover,
}: {
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
  hover?: boolean;
}) {
  return (
    <div
      onClick={onClick}
      className={clsx(
        "bg-white rounded-xl border border-gray-200",
        hover && "cursor-pointer hover:border-blue-300 hover:shadow-md transition-all duration-150",
        className
      )}
    >
      {children}
    </div>
  );
}
