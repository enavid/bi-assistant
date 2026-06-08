// Smoke tests — verify the test environment is wired correctly.
// Add component and hook tests alongside their source files as the app grows.

describe('test environment', () => {
  it('runs', () => {
    expect(1 + 1).toBe(2)
  })

  it('has DOM globals', () => {
    const el = document.createElement('div')
    el.textContent = 'hello'
    expect(el.textContent).toBe('hello')
  })
})
