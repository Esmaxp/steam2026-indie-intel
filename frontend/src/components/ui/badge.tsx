import { cn } from "@/lib/cn";

export function Badge({
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-hairline",
        "px-2 py-0.5 text-xs text-ink2",
        className,
      )}
      {...props}
    />
  );
}
