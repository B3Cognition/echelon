import { readFileSync, existsSync } from 'fs'
import { join } from 'path'
import { describe, it, expect, beforeAll } from 'vitest'

const ECHELON = join(process.cwd(), 'extension')
const SCHEMA_DIR = join(process.cwd(), 'templates')

beforeAll(() => {
  if (!existsSync(ECHELON)) {
    throw new Error(`ECHELON dir not found: ${ECHELON}. Run vitest from /Users/michalbachorik/work/evolution/echelon (currently: ${process.cwd()})`)
  }
  if (!existsSync(SCHEMA_DIR)) {
    throw new Error(`SCHEMA_DIR not found: ${SCHEMA_DIR}. Run vitest from /Users/michalbachorik/work/evolution/echelon (currently: ${process.cwd()})`)
  }
})

describe('cross-run spec continuity', () => {
  it('run-history-schema.json exists and has required fields', () => {
    const schema = JSON.parse(readFileSync(join(SCHEMA_DIR, 'run-history-schema.json'), 'utf8'))
    expect(schema.properties.spec_id).toBeDefined()
    expect(schema.properties.runs).toBeDefined()
    expect(schema.properties.authoritative_run).toBeDefined()
    const runItem = schema.properties.runs.items.properties
    expect(runItem.run_id).toBeDefined()
    expect(runItem.phase).toBeDefined()
    expect(runItem.status).toBeDefined()
    expect(runItem.timestamp).toBeDefined()
  })

  it('echelon.run.md reads run-history.json at INIT', () => {
    const content = readFileSync(join(ECHELON, 'commands/echelon.run.md'), 'utf8')
    expect(content).toMatch(/run-history\.json/)
    expect(content).toMatch(/Phase A.*already.*done|phase.*A.*complete|skip.*phase.*A/i)
  })

  it('echelon.run.md writes run-history.json at DONE', () => {
    const content = readFileSync(join(ECHELON, 'commands/echelon.run.md'), 'utf8')
    const matches = content.match(/run-history\.json/g) || []
    expect(matches.length).toBeGreaterThanOrEqual(2)
  })

  it('echelon.build.md appends to run-history.json at BUILD_DONE', () => {
    const content = readFileSync(join(ECHELON, 'commands/echelon.build.md'), 'utf8')
    expect(content).toMatch(/run-history\.json/)
    expect(content).toMatch(/authoritative_run/)
  })
})
