import { readFileSync, existsSync } from 'fs'
import { join } from 'path'
import { describe, it, expect, beforeAll } from 'vitest'

const ECHELON = join(process.cwd(), 'extension')

beforeAll(() => {
  if (!existsSync(ECHELON)) {
    throw new Error(`ECHELON dir not found: ${ECHELON}. Run vitest from /Users/michalbachorik/work/evolution/echelon (currently: ${process.cwd()})`)
  }
})

describe('MODELER dispatch points', () => {
  it('echelon.run.md dispatches MODELER after SYNTHESIZER', () => {
    const content = readFileSync(join(ECHELON, 'commands/echelon.run.md'), 'utf8')
    const synthIdx = content.indexOf('SYNTHESIZER')
    const modelerIdx = content.indexOf('MODELER', synthIdx)
    expect(synthIdx).toBeGreaterThan(-1)
    expect(modelerIdx).toBeGreaterThan(synthIdx)
  })

  it('echelon.run.md MODELER dispatch references mental-model-code.md', () => {
    const content = readFileSync(join(ECHELON, 'commands/echelon.run.md'), 'utf8')
    expect(content).toMatch(/Dispatch MODELER/)
    expect(content).toMatch(/mental-model-code\.md/)
  })

  it('echelon.build.md dispatches MODELER after IMPLEMENTER task completion', () => {
    const content = readFileSync(join(ECHELON, 'commands/echelon.build.md'), 'utf8')
    // Verify MODELER appears in the task-completion section context,
    // not just anywhere after the first IMPLEMENTER mention
    expect(content).toMatch(/MODELER Update.*mandatory after every task|mandatory after every task.*MODELER/is)
    // Also verify ordering: IMPLEMENTER appears before MODELER Update section
    const implIdx = content.indexOf('IMPLEMENTER')
    const modelerUpdateIdx = content.indexOf('MODELER Update')
    expect(implIdx).toBeGreaterThan(-1)
    expect(modelerUpdateIdx).toBeGreaterThan(implIdx)
  })

  it('echelon.build.md MODELER checks for invariant violations', () => {
    const content = readFileSync(join(ECHELON, 'commands/echelon.build.md'), 'utf8')
    expect(content).toMatch(/invariant.*violation|MODELER.*alert|MODELER.*ALERT/i)
  })
})
