import { mkdir, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const fontDir = path.join(root, 'public', 'fonts')
const files = [
  {
    name: 'TsangerJinKai02-W04.ttf',
    url: 'https://cdn.jsdelivr.net/gh/tw93/Kami@main/assets/fonts/TsangerJinKai02-W04.ttf',
  },
  {
    name: 'TsangerJinKai02-W05.ttf',
    url: 'https://cdn.jsdelivr.net/gh/tw93/Kami@main/assets/fonts/TsangerJinKai02-W05.ttf',
  },
]

const MIN_BYTES = 1_000_000

async function ensureFont({ name, url }) {
  const dest = path.join(fontDir, name)
  try {
    const info = await stat(dest)
    if (info.size >= MIN_BYTES) return
  } catch {
    // missing or too small
  }
  console.log(`[fonts] downloading ${name}…`)
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(`failed to download ${name}: HTTP ${res.status}`)
  }
  const buf = Buffer.from(await res.arrayBuffer())
  if (buf.length < MIN_BYTES) {
    throw new Error(`downloaded ${name} looks too small (${buf.length} bytes)`)
  }
  await writeFile(dest, buf)
}

await mkdir(fontDir, { recursive: true })
await Promise.all(files.map(ensureFont))
console.log('[fonts] ready')
