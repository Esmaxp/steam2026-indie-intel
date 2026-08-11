/** Social account configuration — fill in your usernames and the platforms
 *  appear automatically in the header and the Community page. Leave a field
 *  empty ("") to hide that platform. No usernames are ever invented. */

export interface SocialAccount {
  platform: "youtube" | "twitch" | "tiktok" | "instagram" | "x" | "discord";
  label: string;
  /** Public channel/profile URL. Empty string hides the platform. */
  url: string;
}

export const SOCIAL_ACCOUNTS: SocialAccount[] = [
  { platform: "youtube", label: "YouTube", url: "" },   // e.g. https://www.youtube.com/@yourchannel
  { platform: "twitch", label: "Twitch", url: "" },     // e.g. https://www.twitch.tv/yourname
  { platform: "tiktok", label: "TikTok", url: "" },     // e.g. https://www.tiktok.com/@yourname
  { platform: "instagram", label: "Instagram", url: "" },
  { platform: "x", label: "X (Twitter)", url: "" },
  { platform: "discord", label: "Discord", url: "" },   // invite link
];

export const configuredAccounts = () =>
  SOCIAL_ACCOUNTS.filter((account) => account.url.trim() !== "");
