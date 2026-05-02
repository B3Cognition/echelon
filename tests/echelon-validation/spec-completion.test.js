import { readFileSync, existsSync } from 'fs'
import { join } from 'path'
import { describe, it, expect } from 'vitest'

const ECHELON = join(process.cwd(), 'extension')
const SCHEMA_DIR = join(process.cwd(), 'templates')

if (!existsSync(SCHEMA_DIR)) {
  throw new Error(`SCHEMA_DIR not found: ${SCHEMA_DIR}. Run vitest from /Users/michalbachorik/work/evolution/echelon (currently: ${process.cwd()})`)
}

describe('spec completion tracking', () => {
  it('state-schema.json has spec_status with full lifecycle enum', () => {
    const schema = JSON.parse(readFileSync(join(SCHEMA_DIR, 'state-schema.json'), 'utf8'))
    const prop = schema.properties.spec_status
    expect(prop).toBeDefined()
    expect(prop.enum).toContain('draft')
    expect(prop.enum).toContain('planned')
    expect(prop.enum).toContain('in-progress')
    expect(prop.enum).toContain('implemented')
    expect(prop.default).toBe('draft')
  })

  it('state-schema.json has build object with tasks_completed_pct', () => {
    const schema = JSON.parse(readFileSync(join(SCHEMA_DIR, 'state-schema.json'), 'utf8'))
    const build = schema.properties.build
    expect(build).toBeDefined()
    expect(build.properties.tasks_completed_pct).toBeDefined()
    expect(build.properties.tasks_completed_pct.type).toBe('number')
    expect(build.properties.total_tasks).toBeDefined()
    expect(build.properties.completed_tasks).toBeDefined()
  })

  it('echelon.run.md sets spec_status to planned after CARTOGRAPHER', () => {
    const content = readFileSync(join(ECHELON, 'commands/echelon.run.md'), 'utf8')
    expect(content).toMatch(/spec_status.*planned/)
    expect(content).toMatch(/Status.*Planned/)
  })

  it('echelon.build.md sets spec_status to in-progress at build start', () => {
    const content = readFileSync(join(ECHELON, 'commands/echelon.build.md'), 'utf8')
    expect(content).toMatch(/spec_status.*in-progress/)
    expect(content).toMatch(/Status.*In Progress/)
  })

  it('echelon.build.md sets spec_status to implemented on VERIFICATION PASS', () => {
    const content = readFileSync(join(ECHELON, 'commands/echelon.build.md'), 'utf8')
    expect(content).toMatch(/spec_status.*implemented/)
    expect(content).toMatch(/Status.*Implemented/)
    expect(content).toMatch(/tasks_completed_pct/)
  })
})
