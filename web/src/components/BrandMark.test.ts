import { createApp } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'

import BrandMark from './BrandMark.vue'

describe('BrandMark', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('renders the supplied project logo with an accessible name', () => {
    const host = document.createElement('div')
    document.body.append(host)
    const app = createApp(BrandMark, {
      alt: '妈妈炒股老奶奶 Logo',
      size: 'sm',
    })

    app.mount(host)

    const image = host.querySelector('img')
    expect(image?.getAttribute('src')).toBe('/mommy-chaogu-logo.jpg')
    expect(image?.getAttribute('alt')).toBe('妈妈炒股老奶奶 Logo')
    expect(host.querySelector('span')?.className).toContain('size-9')
    app.unmount()
  })
})
