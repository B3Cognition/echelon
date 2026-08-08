#!/usr/bin/env node
import { Command } from 'commander';
import { analyzeRepository } from '../analysis/analyze.js';
import { renderSummary, writeJsonAtomic } from '../output/writer.js';
import { packageVersion } from '../version.js';

const program = new Command();

program
  .name('perlgraph')
  .description('Static structural graph extraction for Perl repositories')
  .version(packageVersion());

program
  .command('analyze')
  .requiredOption('--repo-path <path>', 'repository path to analyze')
  .option('--output-path <path>', 'analysis JSON output path')
  .option('--summary-path <path>', 'summary JSON output path')
  .option('--include <glob...>', 'include glob patterns')
  .option('--exclude <glob...>', 'exclude glob patterns')
  .option('--json', 'print analysis JSON to stdout')
  .action(async (options) => {
    const analysis = await analyzeRepository(options.repoPath, {
      include: options.include,
      exclude: options.exclude
    });

    if (options.outputPath) {
      await writeJsonAtomic(options.outputPath, analysis);
    }

    if (options.summaryPath) {
      await writeJsonAtomic(options.summaryPath, renderSummary(analysis));
    }

    if (options.json || !options.outputPath) {
      process.stdout.write(`${JSON.stringify(analysis, null, 2)}\n`);
    }
  });

program.parseAsync(process.argv).catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`[perlgraph] ERROR: ${message}\n`);
  process.exitCode = 1;
});
