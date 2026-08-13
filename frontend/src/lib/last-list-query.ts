/** Remembers the filters the games list was showing, so leaving a game can
 *  come back to the same list.
 *
 *  Every bit of list state — filters, sort, page — lives in the URL query
 *  string, and the game page is a different route, so following a game and
 *  then "All games" dropped all of it and reset the user to the unfiltered
 *  catalogue. The query is stashed on the way out rather than threaded through
 *  the game URL, which would put a copy of the filters in every shared link.
 *
 *  sessionStorage, not localStorage: this is where you were a moment ago, not
 *  a preference. It should not survive into a new tab or a new day.
 */

const KEY = "steam2026:last-list-query";

export function rememberListQuery(query: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(KEY, query);
  } catch {
    // Private browsing and storage quotas both throw here. Losing the
    // filters on the way back is a far smaller problem than a crash.
  }
}

/** Where "All games" should point: the list as it was last seen. */
export function listHref(): string {
  if (typeof window === "undefined") return "/";
  try {
    const query = window.sessionStorage.getItem(KEY);
    return query ? `/?${query}` : "/";
  } catch {
    return "/";
  }
}
