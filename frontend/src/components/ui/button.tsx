"use client";

import { ButtonHTMLAttributes, forwardRef } from "react";
import { clsx } from "clsx";

/**
 * Button — wraps the global `.btn` token classes.
 * The variants map to the CSS classes defined in globals.css so theme
 * changes only need to happen in one place.
 */

const variants = {
  primary: "btn btn-primary",
  accent: "btn btn-accent",
  outline: "btn btn-outline",
  ghost: "btn btn-ghost",
  danger: "btn btn-danger",
  /** Legacy alias — was `bg-white border border-gray-300`. Maps onto the new outline. */
  secondary: "btn btn-outline",
};

const sizes = {
  sm: "btn-sm",
  md: "",
  lg: "btn-lg",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof variants;
  size?: keyof typeof sizes;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "primary", size = "md", className, children, type, ...props }, ref) => (
    <button
      ref={ref}
      type={type ?? "button"}
      className={clsx(variants[variant], sizes[size], className)}
      {...props}
    >
      {children}
    </button>
  )
);
Button.displayName = "Button";
