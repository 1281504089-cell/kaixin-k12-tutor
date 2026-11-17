import { isGitHubUpdateURL } from './release-updates.mjs';

/** Electron cancels manual fetch redirects; an isolated session validates every followed hop. */
export function createUpdateFetch(sessions) {
  let updates;
  return (url, options) => {
    if (!updates) {
      updates = sessions.fromPartition('kaixin-updates');
      updates.webRequest.onBeforeRequest((request, done) => {
        let allowed = false;
        try { allowed = isGitHubUpdateURL(new URL(request.url)); } catch {}
        done({ cancel: !allowed });
      });
    }
    return updates.fetch(String(url), { ...options, redirect: 'follow' });
  };
}
