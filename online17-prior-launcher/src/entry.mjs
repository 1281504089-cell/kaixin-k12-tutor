// A packaged Electron executable otherwise ignores an external probe script.
if (process.argv.includes('--student-lesson-probe')) {
  await import('./lesson-browser.cjs');
} else {
  await import('./main.mjs');
}
