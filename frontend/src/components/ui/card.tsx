import { clsx } from "clsx";

/**
 * Card — wraps the global `.card` token class.
 * Tone: surface-on-paper with a 1px border and the restrained `--shadow-sm`.
 */
export function Card({
  children,
  className,
  onClick,
  hover,
  variant = "default",
}: {
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
  hover?: boolean;
  variant?: "default" | "quiet" | "soft";
}) {
  const variantClass =
    variant === "quiet" ? "card-quiet" : variant === "soft" ? "card-soft" : "card";

  return (
    <div
      onClick={onClick}
      className={clsx(
        variantClass,
        hover && "cursor-pointer transition-colors",
        className
      )}
      style={
        hover
          ? {
              transition: "border-color var(--duration-fast) ease, background var(--duration-fast) ease",
            }
          : undefined
      }
    >
      {children}
    </div>
  );
}
