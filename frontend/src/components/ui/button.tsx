import { cn } from "@/lib/cn";

export function Button({
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn(
        "inline-flex h-9 items-center gap-1.5 rounded-md border border-hairline",
        "bg-surface px-3 text-sm text-ink transition-colors hover:bg-grid/40",
        "disabled:cursor-not-allowed disabled:opacity-40",
        className,
      )}
      {...props}
    />
  );
}
