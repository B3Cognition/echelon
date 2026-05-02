import { readFileSync, existsSync } from 'fs'
import { join } from 'path'
import { describe, it, expect, beforeAll } from 'vitest'

const ECHELON = join(process.cwd(), 'extension')

beforeAll(() => {
  if (!existsSync(ECHELON)) {
    throw new Error(`ECHELON dir not found: ${ECHELON}. Run vitest from /Users/michalbachorik/work/evolution/echelon (currently: ${process.cwd()})`)
  }
})

describe('visual validation config', () => {
  it('echelon-config.yml has visual_validation.enabled set to true', () => {
    const raw = readFileSync(join(ECHELON, 'echelon-config.yml'), 'utf8')
    // Parse just the visual_validation block — avoid a full YAML dependency
    expect(raw).toMatch(/visual_validation:\s*\n\s*enabled:\s*true/)
  })

  it('visual-validator.md has a capability check before any work', () => {
    const content = readFileSync(join(ECHELON, 'agents/build/visual-validator.md'), 'utf8')
    expect(content).toMatch(/Capability Check/i)
    expect(content).toMatch(/playwright.*version|npx playwright/i)
    expect(content).toMatch(/skipped_no_playwright/)
  })

  it('visual-validator.md degrades gracefully when no UI framework detected', () => {
    const content = readFileSync(join(ECHELON, 'agents/build/visual-validator.md'), 'utf8')
    expect(content).toMatch(/no.*browser|no.*ui.*framework|not.*browser/i)
    expect(content).toMatch(/skip.*silently/i)
    expect(content).toMatch(/return\s+`?COMPLETE`?/i)
  })
})
