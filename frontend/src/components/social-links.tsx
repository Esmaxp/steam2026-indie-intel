import {
  Instagram,
  MessageCircle,
  Music2,
  Twitch,
  Twitter,
  Youtube,
} from "lucide-react";
import { configuredAccounts, type SocialAccount } from "@/config/social";

const ICONS: Record<SocialAccount["platform"], React.ComponentType<{ size?: number }>> = {
  youtube: Youtube,
  twitch: Twitch,
  tiktok: Music2,
  instagram: Instagram,
  x: Twitter,
  discord: MessageCircle,
};

/** Account icon links (header). Hidden entirely until src/config/social.ts
 *  has at least one URL filled in — nothing is invented. */
export function SocialLinks() {
  const accounts = configuredAccounts();
  if (accounts.length === 0) return null;
  return (
    <nav aria-label="Social media accounts" className="flex items-center gap-1">
      {accounts.map((account) => {
        const Icon = ICONS[account.platform];
        return (
          <a
            key={account.platform}
            href={account.url}
            target="_blank"
            rel="noopener noreferrer"
            title={account.label}
            aria-label={account.label}
            className="rounded-md p-1.5 text-ink2 transition-colors hover:bg-grid/40 hover:text-ink"
          >
            <Icon size={16} />
          </a>
        );
      })}
    </nav>
  );
}
