/**
 * mommy-chaogu-preset-installer —— 投研 preset 幂等自安装（嫁接面 2）。
 *
 * patch 行 `mommy-chaogu-preset-installer`（host 面常驻）。boot 时把
 * assets/preset/mommy-investor 安装到产品 preset root（默认
 * ~/.local/share/mommy-chaogu/dsh-presets；agent-presets 覆盖行已把该 root
 * 配进 roots）。托管算法与 dsh-trading base/presets 同款：首行
 * `# mommy-chaogu-managed: <sha256[0:8]>`，升级只覆写「未被用户修改」的
 * 文件；用户改过的文件整体保留并打警告。插件卸载不删除已安装目录。
 */
import { createHash } from 'node:crypto'
import { lstat, mkdir, readFile, writeFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { join } from 'node:path'
import Schema from '@deepseek-ai/schemastery'
import type { HostContext } from './types.ts'

/** Cordis 插件名 = patch 行 id。 */
export const name = 'mommy-chaogu-preset-installer'

export interface Config {
  presetRoot?: string
}

export const Config: Schema<Config> = Schema.object({ presetRoot: Schema.string() })

/** 产品 preset root：mommy 数据目录下的自有区（与用户创作区分开）。 */
export function defaultPresetRoot(): string {
  return process.env.MOMMY_DATA_DIR !== undefined && process.env.MOMMY_DATA_DIR !== ''
    ? join(process.env.MOMMY_DATA_DIR, 'dsh-presets')
    : join(homedir(), '.local', 'share', 'mommy-chaogu', 'dsh-presets')
}

export const PRESET_ID = 'mommy-investor'
const FILES = ['agent.cordis.yml', 'preset.yml'] as const
const PREFIX = '# mommy-chaogu-managed: '
const hash = (body: string) => createHash('sha256').update(body, 'utf8').digest('hex').slice(0, 8)
export const stamp = (body: string) => `${PREFIX}${hash(body)}\n${body}`
export function isUnmodifiedManaged(text: string): boolean {
  const end = text.indexOf('\n')
  return end >= 0 && text.slice(0, end) === `${PREFIX}${hash(text.slice(end + 1))}`
}

export interface InstallResult {
  dir: string
  wrote: string[]
  skipped: string[]
}

async function readOwnedFile(path: string): Promise<string | null> {
  try {
    const stat = await lstat(path)
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`Refusing non-regular preset file: ${path}`)
    return await readFile(path, 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null
    throw error
  }
}

/** 读包内 preset 资产（CRLF 归一：Windows checkout 会把 LF 资产变 CRLF）。 */
export async function readPresetAssets(): Promise<Record<(typeof FILES)[number], string>> {
  const base = new URL('../assets/preset/mommy-investor/', import.meta.url)
  const entries = await Promise.all(FILES.map(async file =>
    [(await readFile(new URL(file, base), 'utf8')).replace(/\r\n/g, '\n'), file] as const))
  return Object.fromEntries(entries.map(([body, file]) => [file, body])) as Record<(typeof FILES)[number], string>
}

/**
 * 幂等安装：先整体校验（两个文件都读完、被修改的先记 skip），再落盘——
 * 不留半迁移状态。内容与现状一致时零写入。
 */
export async function installPreset(presetRoot: string = defaultPresetRoot()): Promise<InstallResult> {
  const assets = await readPresetAssets()
  const dir = join(presetRoot, PRESET_ID)
  const result: InstallResult = { dir, wrote: [], skipped: [] }
  try {
    if ((await lstat(dir)).isSymbolicLink()) throw new Error(`Refusing symlink preset directory: ${dir}`)
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
  }
  const current = await Promise.all(FILES.map(file => readOwnedFile(join(dir, file))))
  for (const [i, file] of FILES.entries()) {
    if (current[i] !== null && !isUnmodifiedManaged(current[i]!)) {
      result.skipped.push(`${file}: custom or modified management stamp; entire preset preserved`)
    }
  }
  if (result.skipped.length === 0) {
    await mkdir(dir, { recursive: true })
    for (const [i, file] of FILES.entries()) {
      const next = stamp(assets[file])
      if (next !== current[i]) {
        await writeFile(join(dir, file), next)
        result.wrote.push(file)
      }
    }
  }
  return result
}

/** 插件入口：boot 时幂等自安装。 */
export function apply(ctx: HostContext, config: Config = {}): void {
  void installPreset(config.presetRoot ?? defaultPresetRoot()).then(
    result => {
      if (result.skipped.length > 0) {
        console.warn('[mommy-chaogu/presets]', result.dir, result.skipped.join('; '))
      }
    },
    error => {
      console.warn('[mommy-chaogu/presets] preset self-install failed (host keeps running):', error)
    },
  )
}
