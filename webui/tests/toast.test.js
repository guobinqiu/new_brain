import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import * as toast from '../src/utils/toast.js'

const { errorMessage } = toast

for (const retryable of [true, false]) {
  test(`index errors display retryable=${retryable} and traceId`, () => {
    const data = { success: false, retryable, traceId: 'trace-123', file_id: 'file-123' }
    assert.equal(errorMessage({ message: 'HTTP 502', response: { data } }),
      `索引失败，${retryable ? '可重试' : '不可重试'}（traceId: trace-123）`)
  })

  test(`file list errors display retryable=${retryable} and traceId`, () => {
    assert.equal(typeof toast.indexErrorMessage, 'function')
    assert.equal(toast.indexErrorMessage({ retryable, traceId: 'trace-123' }),
      `索引失败，${retryable ? '可重试' : '不可重试'}（traceId: trace-123）`)
  })
}

test('file list errors hide null and legacy raw errors', () => {
  assert.equal(typeof toast.indexErrorMessage, 'function')
  for (const error of [null, undefined, 'internal raw error', {}, []]) {
    assert.equal(toast.indexErrorMessage(error), '')
  }
  assert.equal(toast.indexErrorMessage({ retryable: false, traceId: '' }), '索引失败，不可重试')
})

test('old index error fields are not interpreted', () => {
  const data = { error: 'internal raw error', code: 'OLD_CODE', message: 'old message', file_id: 'a', trace_id: 'b' }
  assert.equal(errorMessage({ response: { data } }, 'fallback'), 'fallback')
  assert.equal(toast.indexErrorMessage(data), '')
})

test('old error fields do not override FastAPI detail', () => {
  assert.equal(errorMessage({ response: { data: { error: null, detail: 'unauthorized' } } }), 'unauthorized')
})

test('index errors only display retryable and traceId even with extra raw fields', () => {
  const data = { success: false, retryable: false, traceId: 'trace-123', file_id: 'file-123', error: 'internal raw error', code: 'OLD_CODE', message: 'old message', trace_id: 'old-trace' }
  assert.equal(errorMessage({ response: { data } }), '索引失败，不可重试（traceId: trace-123）')
  assert.equal(toast.indexErrorMessage(data), '索引失败，不可重试（traceId: trace-123）')
})

test('other endpoints still display their detail', () => {
  assert.equal(errorMessage({ response: { data: { detail: 'unauthorized' } } }), 'unauthorized')
  assert.equal(errorMessage({ response: { data: { detail: [{ msg: 'required' }] } } }), 'required')
  assert.equal(errorMessage({ response: { data: { detail: { reason: 'invalid' } } } }), '{"reason":"invalid"}')
  assert.equal(errorMessage({ response: { data: 'bad gateway' } }), 'bad gateway')
  assert.equal(errorMessage(new Error('network error')), 'network error')
  assert.equal(errorMessage({}, 'fallback'), 'fallback')
})

const uploadSource = readFileSync(new URL('../src/views/UploadView.vue', import.meta.url), 'utf8')
const uploadFunction = uploadSource.slice(uploadSource.indexOf('async function uploadFiles('), uploadSource.indexOf('async function fetchFiles('))

for (const outcome of ['success', 'failure', 'rejected', 'legacy', 'network', 'upload']) {
  test(`upload handles ${outcome} without automatic retries`, async () => {
    const messages = []
    const calls = []
    let refreshed = 0
    const data = { success: outcome === 'success', retryable: true, traceId: 'trace-123', file_id: 'file-123' }
    const axios = { post: async (url) => {
      calls.push(url)
      if (url.endsWith('/upload')) {
        if (outcome === 'upload') throw { response: { data: { detail: 'upload detail' } } }
        return { data: { file_id: 'file-123', s3_url: 's3://file' } }
      }
      if (outcome === 'rejected') throw { response: { data } }
      if (outcome === 'legacy') throw { response: { data: { error: 'internal raw error', code: 'OLD_CODE', message: 'old message', trace_id: 'old-trace' } } }
      if (outcome === 'network') throw new Error('internal network details')
      return { data }
    } }
    const upload = new Function('axios', 'API', 'currentAppId', 'showToast', 'errorMessage', 'indexErrorMessage', 'fetchFiles', 't', `${uploadFunction}; return uploadFiles`)(
      axios, '/api/rag', { value: 'app-123' }, (...args) => messages.push(args), errorMessage, toast.indexErrorMessage,
      async () => { refreshed++ }, (key, { count }) => `${key}:${count}`,
    )
    assert.equal(await upload([{ name: 'file.txt' }]), outcome === 'success')
    assert.equal(refreshed, 1)
    assert.equal(calls.length, outcome === 'upload' ? 1 : 3)
    const expected = outcome === 'success' ? ['success', 'upload.indexSubmitted:1']
      : ['error', `file.txt: ${outcome === 'upload' ? 'upload detail'
        : ['legacy', 'network'].includes(outcome) ? '索引失败'
        : '索引失败，可重试（traceId: trace-123）'}`]
    assert.deepEqual(messages, [expected])
  })
}
