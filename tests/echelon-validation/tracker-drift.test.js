import { readFileSync, existsSync } from 'fs'
import { join } from 'path'
import { describe, it, expect, beforeAll } from 'vitest'

const ECHELON = join(process.cwd(), 'extension')

beforeAll(() => {
  if (!existsSync(ECHELON)) {
    throw new Error(`ECHELON dir not found: ${ECHELON}. Run vitest from /Users/michalbachorik/work/evolution/echelon (currently: ${process.cwd()})`)
  }
})

describe('TRACKER drift correction', () => {
  it('tracker.md output format defines drift_severity field', () => {
    const content = readFileSync(join(ECHELON, 'agents/control/tracker.md'), 'utf8')
    expect(content).toMatch(/drift_severity/)
    expect(content).toMatch(/ALIGNED/)
    expect(content).toMatch(/MINOR_DRIFT/)
    expect(content).toMatch(/MAJOR_DRIFT/)
  })

  it('tracker.md defines severity thresholds with 20% boundary', () => {
    const content = readFileSync(join(ECHELON, 'agents/control/tracker.md'), 'utf8')
    expect(content).toMatch(/20%|0\.20/)
  })

  it('echelon.build.md has a severity-tiered drift gate', () => {
    const content = readFileSync(join(ECHELON, 'commands/echelon.build.md'), 'utf8')
    expect(content).toMatch(/MAJOR_DRIFT/)
    expect(content).toMatch(/MINOR_DRIFT/)
  })

  it('echelon.build.md dispatches CHANGE CONTROLLER on MAJOR_DRIFT (non-banzai)', () => {
    const content = readFileSync(join(ECHELON, 'commands/echelon.build.md'), 'utf8')
    // CHANGE CONTROLLER must appear near MAJOR_DRIFT
    expect(content).toMatch(/MAJOR_DRIFT[\s\S]{0,500}CHANGE CONTROLLER|CHANGE CONTROLLER[\s\S]{0,200}MAJOR_DRIFT/i)
  })

  it('echelon.build.md sets requires_human_review on MAJOR_DRIFT in banzai mode', () => {
    const content = readFileSync(join(ECHELON, 'commands/echelon.build.md'), 'utf8')
    expect(content).toMatch(/requires_human_review/)
    expect(content).toMatch(/drift-escalation\.md/)
  })
})
