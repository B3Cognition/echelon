import { readFileSync, existsSync } from 'fs'
import { join } from 'path'
import { describe, it, expect, beforeAll } from 'vitest'

const ECHELON = join(process.cwd(), 'extension')

beforeAll(() => {
  if (!existsSync(ECHELON)) {
    throw new Error(`ECHELON dir not found: ${ECHELON}. Run vitest from /Users/michalbachorik/work/evolution/echelon (currently: ${process.cwd()})`)
  }
})

describe('constitution amendment flow', () => {
  it('mirror.md produces amendment candidates in its output', () => {
    const content = readFileSync(join(ECHELON, 'agents/learning/mirror.md'), 'utf8')
    expect(content).toMatch(/amendment.*candidate|constitution.*amendment/i)
    expect(content).toMatch(/PROPOSED/)
  })

  it('veteran.md produces amendment candidates from cross-run comparison', () => {
    const content = readFileSync(join(ECHELON, 'agents/learning/veteran.md'), 'utf8')
    expect(content).toMatch(/amendment.*candidate|constitution.*amendment/i)
    expect(content).toMatch(/PROPOSED/)
    expect(content).toMatch(/run-history\.json|cross-run/i)
  })

  it('echelon.build.md has a consolidation phase after AUDITOR', () => {
    const content = readFileSync(join(ECHELON, 'commands/echelon.build.md'), 'utf8')
    expect(content).toMatch(/consolidation|Consolidation/i)
    expect(content).toMatch(/constitution-amendment-candidates\.md/)
  })

  it('echelon.build.md appends PROPOSED blocks to constitution.md', () => {
    const content = readFileSync(join(ECHELON, 'commands/echelon.build.md'), 'utf8')
    expect(content).toMatch(/\[PROPOSED/)
    expect(content).toMatch(/constitution_amendments_pending/)
  })

  it('echelon.build.md requires human approval — no auto-amendment', () => {
    const content = readFileSync(join(ECHELON, 'commands/echelon.build.md'), 'utf8')
    expect(content).toMatch(/human.*review|human.*approve|speckit\.constitution/i)
  })
})
