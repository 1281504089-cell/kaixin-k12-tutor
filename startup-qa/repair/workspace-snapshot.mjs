import { cp, link, lstat, mkdir, rm } from 'node:fs/promises';
import { constants } from 'node:fs';
import path from 'node:path';
import { sha256 } from './bundles.mjs';

/** ReadingStore's content-addressed PDFs are immutable; notes/settings get independent copies. */
export async function snapshotWorkspace(source, destination) {
  await mkdir(destination, { mode: 0o700 });
  try {
    await cp(source, destination, {
      recursive: true, verbatimSymlinks: true, mode: constants.COPYFILE_FICLONE,
      filter: async (file, target) => {
        const parts = path.relative(source, file).split(path.sep);
        const raw = parts.at(-2) === 'raw' && parts.at(-4) === 'reading';
        const digest = parts.at(-3) ?? '';
        if (raw && /^[a-f0-9]{64}$/.test(digest) && /\.pdf$/i.test(file) && (await lstat(file)).isFile() && await sha256(file) === digest) {
          await mkdir(path.dirname(target), { recursive: true });
          try { await link(file, target); return false; }
          catch (error) { if (!['EXDEV', 'EPERM', 'ENOTSUP'].includes(error.code)) throw error; }
        }
        return true;
      },
    });
  } catch (error) {
    await rm(destination, { recursive: true, force: true });
    throw error;
  }
}
