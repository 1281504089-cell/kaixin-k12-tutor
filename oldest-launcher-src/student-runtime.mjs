import path from 'node:path';
import { existsSync } from 'node:fs';

/** Optional components stay outside the chat process until a tool needs them. */
export function studentEnvironment(config, cachePath) {
  const root = path.resolve(process.env.DEEPTUTOR_STUDENT_RESOURCES || path.join(config.basePath ?? path.dirname(config.sourcePath), 'support'));
  if (!existsSync(root)) return {};
  const tex = path.join(root, 'tex', 'bin', process.platform === 'win32' ? 'windows' : 'universal-darwin');
  return {
    PATH: [path.join(root, 'bin'), tex, path.dirname(config.nodePath), path.dirname(config.pythonPath), process.env.PATH].filter(Boolean).join(path.delimiter),
    DEEPTUTOR_FONT_DIR: path.join(root, 'fonts'),
    DEEPTUTOR_REMOTION_RUNTIME: path.join(root, 'remotion'),
    DEEPTUTOR_LOCAL_AI: path.join(root, 'local-ai'),
    TESSDATA_PREFIX: path.join(root, 'tessdata'),
    DEEPTUTOR_OCR_LANGUAGE: 'chi_sim+eng',
    DEEPTUTOR_OCR_BACKEND: 'rapidocr_onnxruntime',
    TEXMFVAR: path.join(cachePath, 'tex-var'),
    TEXMFCONFIG: path.join(cachePath, 'tex-config'),
    MPLCONFIGDIR: path.join(cachePath, 'matplotlib'),
    MPLBACKEND: 'Agg',
    OMP_NUM_THREADS: '2',
    OPENBLAS_NUM_THREADS: '2',
  };
}
