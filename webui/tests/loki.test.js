import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { SourceTextModule, SyntheticModule } from 'node:vm'

const formatModule = new SourceTextModule(
  await readFile(new URL('../src/utils/format.js', import.meta.url), 'utf8'),
)
await formatModule.link(() => { throw new Error('Unexpected format dependency') })
const apiModule = new SyntheticModule(['default'], function () {
  this.setExport('default', {})
})
const lokiModule = new SourceTextModule(
  await readFile(new URL('../src/utils/loki.js', import.meta.url), 'utf8'),
)
await lokiModule.link(specifier => {
  if (specifier === './api') return apiModule
  if (specifier === './format') return formatModule
  throw new Error(`Unexpected dependency: ${specifier}`)
})
await lokiModule.evaluate()
const { formatLogLine } = lokiModule.namespace

for (const [timezone, expected] of [
  ['Asia/Shanghai', '2026/9/10 08:00:00'],
  ['America/New_York', '2026/9/9 20:00:00'],
]) {
  test(`formats equivalent UTC and +08 timestamps in ${timezone}`, () => {
    const originalTimezone = process.env.TZ
    process.env.TZ = timezone
    try {
      for (const time of ['2026-09-10T00:00:00Z', '2026-09-10T08:00:00+08:00']) {
        for (const source of ['parsed', 'row']) {
          const parsed = { timestamp: time, level: 'INFO', message: 'ready' }
          if (source === 'parsed') parsed.time = time
          const row = {
            time: source === 'parsed' ? '2026-09-09T00:00:00Z' : time,
            container: 'rag',
            parsed,
            line: JSON.stringify(parsed),
          }
          const original = structuredClone(row)

          assert.equal(formatLogLine(row), `${expected} rag INFO ready`)
          assert.deepEqual(row, original)
        }
      }
    } finally {
      if (originalTimezone === undefined) delete process.env.TZ
      else process.env.TZ = originalTimezone
    }
  })
}

test('preserves unparsed log text verbatim', () => {
  const line = '2026-09-10T00:00:00Z raw log message'

  assert.equal(formatLogLine({ line, time: '2026-09-10T00:00:00Z' }), line)
})

test('preserves the message without adding a missing timestamp', () => {
  assert.equal(formatLogLine({ parsed: { message: 'ready' } }), 'ready')
})
