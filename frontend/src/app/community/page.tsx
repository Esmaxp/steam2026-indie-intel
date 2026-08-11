import { CommunityClips } from "@/components/community-clips";

export const metadata = { title: "Community Clips — Steam 2026 Indie Intelligence" };

export default function CommunityPage() {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Community Clips</h1>
        <p className="mt-1 text-sm text-ink2">
          Videos and clips from across platforms — YouTube and Twitch update
          automatically; TikTok, Instagram and X entries are hand-curated.
        </p>
      </div>
      <CommunityClips />
    </div>
  );
}
