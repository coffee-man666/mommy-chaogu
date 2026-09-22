import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterAll, describe, expect, it } from 'vitest'
import { PRESET_ID, installPreset, isUnmodifiedManaged, readPresetAssets, stamp } from '../src/presets.ts'

const root = await mkdtemp(join(tmpdir(), 'mommy-preset-'))
afterAll(async () => {
  await rm(root, { recursive: true, force: true })
})

describe('托管 stamp', () => {
  it('stamp → isUnmodifiedManaged 往返成立', () => {
    const body = 'line1\nline2\n'
    expect(isUnmodifiedManaged(stamp(body))).toBe(true)
  })
  it('用户改过托管文件后视为 modified', () => {
    const modified = `${stamp('body\n')}\n# user note`
    expect(isUnmodifiedManaged(modified)).toBe(false)
  })
  it('无 stamp 的用户自建文件视为 modified（整体保留）', () => {
    expect(isUnmodifiedManaged('# user file\n')).toBe(false)
  })
})

describe('installPreset（幂等 + 用户修改保护）', () => {
  it('首次安装写出两个文件，重复安装零写入', async () => {
    const first = await installPreset(root)
    expect([...first.wrote].sort()).toEqual(['agent.cordis.yml', 'preset.yml'])
    expect(first.skipped).toEqual([])
    const again = await installPreset(root)
    expect(again.wrote).toEqual([])
    expect(again.skipped).toEqual([])
  })
  it('内容与包内资产一致（CRLF 归一 + stamp 首行）', async () => {
    const assets = await readPresetAssets()
    const installed = await readFile(join(root, PRESET_ID, 'agent.cordis.yml'), 'utf8')
    expect(installed).toBe(stamp(assets['agent.cordis.yml']))
  })
  it('用户修改过的文件整体保留（skip 且不写）', async () => {
    const dir = join(root, PRESET_ID)
    const current = await readFile(join(dir, 'preset.yml'), 'utf8')
    await writeFile(join(dir, 'preset.yml'), `${current}\n# user customized`)
    const result = await installPreset(root)
    expect(result.wrote).toEqual([])
    expect(result.skipped.length).toBe(1)
    expect(result.skipped[0]).toContain('preset.yml')
  })
})
