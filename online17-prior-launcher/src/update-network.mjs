import { isGitHubUpdateURL, isUpdateMirrorAsset, updateMirrorBase } from './release-updates.mjs';
import { setTimeout as delay } from 'node:timers/promises';

/** An isolated session validates every followed GitHub hop. The mirror serves assets directly. */
export function createUpdateFetch(sessions, mirrorBase) {
  const mirror = updateMirrorBase(mirrorBase);
  let updates;
  let recovery = 0;
  const fetchUpdate = (url, options) => {
    if (!updates) {
      updates = sessions.fromPartition(recovery ? `kaixin-updates-resumed-${recovery}` : 'kaixin-updates');
      updates.webRequest.onBeforeRequest((request, done) => {
        let allowed = false;
        try {
          const url = new URL(request.url);
          allowed = isGitHubUpdateURL(url) || isUpdateMirrorAsset(url, mirror);
        } catch {}
        done({ cancel: !allowed });
      });
    }
    const redirect = isUpdateMirrorAsset(new URL(url), mirror) ? 'error' : 'follow';
    return updates.fetch(String(url), { ...options, redirect });
  };
  fetchUpdate.recoverAfterSuspend = async signal => {
    await delay(1000, undefined, { signal });
    recovery++;
    updates = undefined;
  };
  return fetchUpdate;
}
