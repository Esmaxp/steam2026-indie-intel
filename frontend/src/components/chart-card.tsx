"use client";

import { Card } from "@/components/ui/card";

/** Every card in the analytics grid: same padding, same title style, same
 *  chart height. The genre panel swaps two different components through one
 *  grid slot, so they can only avoid a layout jump by sharing this wrapper
 *  rather than each hand-rolling a Card and a heading.
 *
 *  `action` is for a control that belongs to the card's header (the genre
 *  panel's Close button); `subtitle` for a line of explanation under it. */
export const CHART_BODY_HEIGHT = "h-72";

export function ChartCard({
  title,
  subtitle,
  action,
  footer,
  children,
}: {
  title: string;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
  footer?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card className="flex flex-col p-4">
      <div className="mb-2 flex items-start justify-between gap-2">
        <h3 className="text-sm font-medium text-ink2">{title}</h3>
        {action}
      </div>
      {subtitle ? <div className="mb-2 text-xs text-muted">{subtitle}</div> : null}
      <div className={CHART_BODY_HEIGHT}>{children}</div>
      {footer ? <div className="mt-2">{footer}</div> : null}
    </Card>
  );
}
