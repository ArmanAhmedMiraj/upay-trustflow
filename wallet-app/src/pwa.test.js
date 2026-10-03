import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const root = path.resolve(import.meta.dirname, '..')
const read = (f) => fs.readFileSync(path.join(root, f), 'utf8')
const manifest = JSON.parse(read('public/manifest.webmanifest'))

function pngSize(file) {
  const buf = fs.readFileSync(path.join(root, 'public', file))
  expect(buf.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a') // it really is a PNG
  return [buf.readUInt32BE(16), buf.readUInt32BE(20)]
}

describe('installable app', () => {
  it('has a manifest a phone will accept', () => {
    expect(manifest.name).toBeTruthy()
    expect(manifest.short_name.length).toBeLessThanOrEqual(12)
    expect(manifest.start_url).toBe('/')
    expect(manifest.display).toBe('standalone')
    expect(manifest.theme_color).toMatch(/^#[0-9a-f]{6}$/i)
    expect(manifest.background_color).toMatch(/^#[0-9a-f]{6}$/i)
  })

  it('lists icons that exist and have the sizes they claim', () => {
    const sizes = manifest.icons.map((i) => i.sizes)
    expect(sizes).toContain('192x192')
    expect(sizes).toContain('512x512')
    expect(manifest.icons.some((i) => i.purpose === 'maskable')).toBe(true)
    for (const icon of manifest.icons) {
      const [w, h] = pngSize(icon.src.replace(/^\//, ''))
      expect(`${w}x${h}`).toBe(icon.sizes)
    }
    expect(pngSize('icons/apple-touch-icon.png')).toEqual([180, 180])
  })

  it('links everything from the page', () => {
    const html = read('index.html')
    expect(html).toContain('rel="manifest" href="/manifest.webmanifest"')
    expect(html).toContain('apple-touch-icon')
    expect(html).toContain('name="theme-color"')
    expect(html).toContain('viewport-fit=cover')
  })

  it('has a service worker that never touches the wallet API', () => {
    const sw = read('public/sw.js')
    expect(sw).toContain("addEventListener('fetch'")
    expect(sw).toContain("request.method !== 'GET'")
    expect(sw).toContain('url.origin !== self.location.origin')       // cross-site calls (the API) pass straight through
    expect(read('src/main.jsx')).toContain("serviceWorker.register('/sw.js')")
    expect(read('src/main.jsx')).toContain('import.meta.env.PROD')   // registered only in the built app
  })
})
