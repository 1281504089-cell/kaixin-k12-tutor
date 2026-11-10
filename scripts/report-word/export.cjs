const fs = require('node:fs');
const {word} = require('./review-document.cjs');

async function main() {
  const data = JSON.parse(fs.readFileSync(0, 'utf8'));
  const ids = new Map(data.evidence.map((entry, index) => [entry.id, 'm' + (index + 1)]));
  const evidence = data.evidence.map(entry => ({
    ...entry, id: ids.get(entry.id), hasUnseenImage: entry.has_images,
  }));
  const review = data.subject_review;
  const sections = review.sections.map(section => ({
    text: section.text, refs: section.refs.map(id => ids.get(id)).filter(Boolean),
  }));
  const {from,to} = data.range;
  const document = await word({
    subject: data.subject,
    evidence,
    textbookScope: data.textbook_scope || [],
    range: {label: from === to ? from : from + ' 至 ' + to},
    report: {...review, recordSummary: data.result_level === 'records', sections, sectionTitles: review.sections.map(section => section.title)},
  });
  process.stdout.write(document);
}

main().catch(error => {
  process.stderr.write(String(error));
  process.exitCode = 1;
});
